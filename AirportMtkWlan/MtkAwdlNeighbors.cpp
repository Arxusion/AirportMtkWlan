/*
 * Kernel PF_ROUTE IPv6 prefix (fe80::%awdl0/64) and permanent NDP peer
 * neighbor manager for AirportMtkWlan AWDL Beta. Runs purely off-gate in a
 * serialized thread_call so IOWorkLoop/driver paths never block on routing I/O.
 *
 * Copyright (C) 2026 AirportMtkWlan Contributors.
 * Licensed under GNU GPL v3.0 or later.
 */
#if defined(MTK_NATIVE_AWDL) && defined(AIRPORT_WCL) && __IO80211_TARGET == __MAC_26_0

#include "MtkAwdlNeighbors.hpp"

#include <IOKit/IOLib.h>
#include <libkern/OSAtomic.h>
#include <libkern/libkern.h>
#include <mach/mach_time.h>
#include <net/if_dl.h>
#include <net/if_types.h>
#include <net/kpi_interface.h>
#include <net/route.h>
#include <netinet/in.h>
#include <sys/errno.h>
#include <sys/kpi_socket.h>
#include <sys/socket.h>
#include <sys/uio.h>

extern "C" int PE_parse_boot_argn(const char *arg_string, void *arg_ptr, int max_len);

namespace {

size_t writeIn6(uint8_t *dst, const uint8_t addr16[16])
{
    struct sockaddr_in6 sa = {};
    sa.sin6_len = sizeof(sa);
    sa.sin6_family = AF_INET6;
    memcpy(sa.sin6_addr.s6_addr, addr16, 16);
    memcpy(dst, &sa, sizeof(sa));
    return MtkAwdlNdp::alignRouteSockaddr(sizeof(sa));
}

size_t writeLinkGateway(uint8_t *dst, uint16_t ifIndex, const char *ifName,
                        const uint8_t *mac6)
{
    uint8_t raw[64] = {};
    auto *sdl = reinterpret_cast<struct sockaddr_dl *>(raw);
    const size_t nlen = ifName ? strnlen(ifName, 12) : 0;
    const size_t alen = mac6 ? 6 : 0;
    const size_t body = sizeof(struct sockaddr_dl) - sizeof(sdl->sdl_data) + nlen + alen;
    sdl->sdl_len = static_cast<u_char>(body < sizeof(struct sockaddr_dl) ? sizeof(struct sockaddr_dl) : body);
    sdl->sdl_family = AF_LINK;
    sdl->sdl_index = ifIndex;
    sdl->sdl_type = IFT_ETHER;
    sdl->sdl_nlen = static_cast<u_char>(nlen);
    sdl->sdl_alen = static_cast<u_char>(alen);
    if (nlen)
        memcpy(sdl->sdl_data, ifName, nlen);
    if (alen)
        memcpy(sdl->sdl_data + nlen, mac6, alen);
    memcpy(dst, raw, sdl->sdl_len);
    return MtkAwdlNdp::alignRouteSockaddr(sdl->sdl_len);
}

static uint64_t monotonicNS()
{
    uint64_t ns = 0;
    absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
    return ns;
}

} // namespace

bool MtkAwdlNeighborManager::init(const char *ifaceName)
{
    if (initialized)
        return true;

    int ndpBoot = 1;
    PE_parse_boot_argn("amtk_awdl_ndp", &ndpBoot, sizeof(ndpBoot));
    enabled = (ndpBoot != 0);

    strlcpy(ifName, ifaceName ? ifaceName : "awdl0", sizeof(ifName));
    lock = IOLockAlloc();
    if (!lock)
        return false;

    workCall = thread_call_allocate_with_options(
        workerTrampoline, this,
        THREAD_CALL_PRIORITY_KERNEL, THREAD_CALL_OPTIONS_ONCE);
    if (!workCall) {
        IOLockFree(lock);
        lock = nullptr;
        return false;
    }

    stopping = false;
    stats = {};
    stats.enabled = enabled;
    initialized = true;
    return true;
}

void MtkAwdlNeighborManager::destroy()
{
    stopBlocking();
    if (workCall) {
        thread_call_free(workCall);
        workCall = nullptr;
    }
    closeSocket();
    if (lock) {
        IOLockFree(lock);
        lock = nullptr;
    }
    initialized = false;
}

void MtkAwdlNeighborManager::workerTrampoline(thread_call_param_t p0, thread_call_param_t)
{
    auto *self = static_cast<MtkAwdlNeighborManager *>(p0);
    if (self)
        self->runPass();
}

bool MtkAwdlNeighborManager::ensureSocket()
{
    if (routeSock)
        return true;
    socket_t so = nullptr;
    errno_t err = sock_socket(PF_ROUTE, SOCK_RAW, 0, nullptr, nullptr, &so);
    if (err != 0 || !so) {
        stats.errors++;
        stats.lastErrno = err ? err : EIO;
        return false;
    }
    int loop = 0;
    (void)sock_setsockopt(so, SOL_SOCKET, SO_USELOOPBACK, &loop, sizeof(loop));
    (void)sock_shutdown(so, SHUT_RD);
    routeSock = so;
    return true;
}

void MtkAwdlNeighborManager::closeSocket()
{
    if (routeSock) {
        sock_close(static_cast<socket_t>(routeSock));
        routeSock = nullptr;
    }
}

int MtkAwdlNeighborManager::sendRouteMsg(const void *buf, size_t len)
{
    if (!ensureSocket())
        return stats.lastErrno ? stats.lastErrno : EIO;
    struct iovec iov = {};
    iov.iov_base = const_cast<void *>(buf);
    iov.iov_len = len;
    struct msghdr msg = {};
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    size_t sent = 0;
    errno_t err = sock_send(static_cast<socket_t>(routeSock), &msg, 0, &sent);
    if (err == EBADF || err == EPIPE || err == ENOTCONN) {
        closeSocket();
        if (ensureSocket()) {
            sent = 0;
            err = sock_send(static_cast<socket_t>(routeSock), &msg, 0, &sent);
        }
    }
    return err;
}

int MtkAwdlNeighborManager::programPrefixRoute(uint8_t rtmType, uint32_t ifIndex)
{
    uint8_t buf[MtkAwdlNdp::kMaxRouteMsgBytes] = {};
    auto *rtm = reinterpret_cast<struct rt_msghdr *>(buf);
    size_t off = sizeof(*rtm);

    uint8_t dstAddr[16] = {};
    dstAddr[0] = 0xfe;
    dstAddr[1] = 0x80;
    dstAddr[2] = static_cast<uint8_t>((ifIndex >> 8) & 0xff);
    dstAddr[3] = static_cast<uint8_t>(ifIndex & 0xff);
    off += writeIn6(buf + off, dstAddr);
    off += writeLinkGateway(buf + off, static_cast<uint16_t>(ifIndex), ifName, nullptr);

    uint8_t mask64[16] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff};
    off += writeIn6(buf + off, mask64);

    rtm->rtm_msglen = static_cast<u_short>(off);
    rtm->rtm_version = RTM_VERSION;
    rtm->rtm_type = rtmType;
    rtm->rtm_index = static_cast<u_short>(ifIndex);
    rtm->rtm_flags = RTF_UP | RTF_STATIC | RTF_IFSCOPE;
    rtm->rtm_addrs = RTA_DST | RTA_GATEWAY | RTA_NETMASK;
    rtm->rtm_seq = static_cast<int>(++passSeq);
    return sendRouteMsg(buf, off);
}

int MtkAwdlNeighborManager::programNeighborHost(uint8_t rtmType, uint32_t ifIndex,
                                                const uint8_t mac[6])
{
    uint8_t buf[MtkAwdlNdp::kMaxRouteMsgBytes] = {};
    auto *rtm = reinterpret_cast<struct rt_msghdr *>(buf);
    size_t off = sizeof(*rtm);

    uint8_t dstAddr[16];
    MtkAwdlNdp::fillEui64LinkLocal(dstAddr, static_cast<uint16_t>(ifIndex), mac);
    off += writeIn6(buf + off, dstAddr);
    off += writeLinkGateway(buf + off, static_cast<uint16_t>(ifIndex), nullptr, mac);

    rtm->rtm_msglen = static_cast<u_short>(off);
    rtm->rtm_version = RTM_VERSION;
    rtm->rtm_type = rtmType;
    rtm->rtm_index = static_cast<u_short>(ifIndex);
    rtm->rtm_flags = RTF_UP | RTF_HOST | RTF_STATIC | RTF_IFSCOPE;
    rtm->rtm_addrs = RTA_DST | RTA_GATEWAY;
    rtm->rtm_seq = static_cast<int>(++passSeq);
    return sendRouteMsg(buf, off);
}

void MtkAwdlNeighborManager::updateDesiredState(bool awdlActive, uint64_t nowNS,
                                                const uint8_t (*peerMacs)[6], size_t peerCount)
{
    if (!initialized || !enabled || !lock || !workCall)
        return;

    IOLockLock(lock);
    if (stopping) {
        IOLockUnlock(lock);
        return;
    }
    desiredActive = awdlActive;
    latestNowNS = nowNS ? nowNS : monotonicNS();

    if (awdlActive && peerMacs) {
        for (size_t i = 0; i < peerCount; ++i) {
            const uint8_t *mac = peerMacs[i];
            if (!mac || (mac[0] & 1))
                continue;
            bool nonZero = false;
            for (int b = 0; b < 6; ++b)
                nonZero |= (mac[b] != 0);
            if (!nonZero)
                continue;

            int freeIdx = -1;
            int foundIdx = -1;
            int oldestIdx = 0;
            for (int s = 0; s < static_cast<int>(MtkAwdlNdp::kMaxPeers); ++s) {
                if (peers[s].used) {
                    if (memcmp(peers[s].mac, mac, 6) == 0) {
                        foundIdx = s;
                        break;
                    }
                    if (peers[s].lastSeenNS < peers[oldestIdx].lastSeenNS)
                        oldestIdx = s;
                } else if (freeIdx < 0) {
                    freeIdx = s;
                }
            }
            const int target = (foundIdx >= 0) ? foundIdx : (freeIdx >= 0 ? freeIdx : oldestIdx);
            if (foundIdx < 0) {
                if (peers[target].used && peers[target].owned && peers[target].ifIndex) {
                    // Mark old entry for eviction if table full.
                    peers[target].owned = false;
                }
                peers[target] = {};
                peers[target].used = true;
                memcpy(peers[target].mac, mac, 6);
            }
            peers[target].lastSeenNS = latestNowNS;
        }
    }
    IOLockUnlock(lock);

    thread_call_enter(workCall);
}

void MtkAwdlNeighborManager::runPass()
{
    if (!initialized || !lock)
        return;

    ifnet_t ifp = nullptr;
    uint32_t liveIfIndex = 0;
    if (ifnet_find_by_name(ifName, &ifp) == 0 && ifp) {
        liveIfIndex = ifnet_index(ifp);
        ifnet_release(ifp);
    }

    PeerSlot snapshot[MtkAwdlNdp::kMaxPeers] = {};
    bool wantActive = false;
    bool wasPrefixOwned = false;
    uint32_t prevIfIndex = 0;
    uint64_t nowNS = 0;
    uint32_t passNum = 0;

    IOLockLock(lock);
    wantActive = desiredActive && !stopping && enabled && liveIfIndex != 0;
    wasPrefixOwned = prefixOwned;
    prevIfIndex = currentIfIndex;
    nowNS = latestNowNS ? latestNowNS : monotonicNS();
    passNum = ++stats.passes;

    if (prevIfIndex && liveIfIndex != prevIfIndex) {
        // Interface re-attached under a new ifIndex: kernel dropped prior entries.
        prefixOwned = false;
        wasPrefixOwned = false;
        for (auto &slot : peers) {
            slot.owned = false;
            slot.ifIndex = 0;
        }
    }
    currentIfIndex = liveIfIndex;
    memcpy(snapshot, peers, sizeof(snapshot));
    IOLockUnlock(lock);

    const bool refresh = (passNum % MtkAwdlNdp::kRefreshIntervalPasses) == 0;
    bool nextPrefixOwned = wasPrefixOwned;

    if (wantActive) {
        if (!wasPrefixOwned || refresh) {
            int err = programPrefixRoute(RTM_ADD, liveIfIndex);
            if (err == 0) {
                nextPrefixOwned = true;
                stats.routeAdds++;
            } else if (err == EEXIST) {
                // Pre-existing route is shared cleanly, never claim ownership unless owned.
            } else {
                stats.errors++;
                stats.lastErrno = err;
            }
        }
        for (auto &slot : snapshot) {
            if (!slot.used)
                continue;
            const bool expired = (nowNS >= slot.lastSeenNS) &&
                                 ((nowNS - slot.lastSeenNS) >= MtkAwdlNdp::kPeerIdleExpireNS);
            if (expired) {
                if (slot.owned && slot.ifIndex == liveIfIndex) {
                    (void)programNeighborHost(RTM_DELETE, liveIfIndex, slot.mac);
                    stats.neighborDeletes++;
                }
                slot = {};
                continue;
            }
            if (!slot.owned || slot.ifIndex != liveIfIndex || refresh) {
                int err = programNeighborHost(RTM_ADD, liveIfIndex, slot.mac);
                if (err == EEXIST) {
                    (void)programNeighborHost(RTM_DELETE, liveIfIndex, slot.mac);
                    err = programNeighborHost(RTM_ADD, liveIfIndex, slot.mac);
                }
                if (err == 0) {
                    slot.owned = true;
                    slot.ifIndex = liveIfIndex;
                    stats.neighborAdds++;
                } else {
                    stats.errors++;
                    stats.lastErrno = err;
                }
            }
        }
    } else {
        for (auto &slot : snapshot) {
            if (slot.used && slot.owned && slot.ifIndex && liveIfIndex == slot.ifIndex) {
                (void)programNeighborHost(RTM_DELETE, slot.ifIndex, slot.mac);
                stats.neighborDeletes++;
            }
            slot = {};
        }
        if (wasPrefixOwned && prevIfIndex && (!liveIfIndex || liveIfIndex == prevIfIndex)) {
            (void)programPrefixRoute(RTM_DELETE, prevIfIndex);
        }
        nextPrefixOwned = false;
    }

    uint32_t activeCount = 0;
    IOLockLock(lock);
    prefixOwned = nextPrefixOwned;
    for (size_t i = 0; i < MtkAwdlNdp::kMaxPeers; ++i) {
        if (!wantActive) {
            peers[i] = {};
        } else if (!snapshot[i].used && peers[i].used && peers[i].lastSeenNS <= nowNS &&
                   (nowNS - peers[i].lastSeenNS) >= MtkAwdlNdp::kPeerIdleExpireNS) {
            peers[i] = {};
        } else if (snapshot[i].used && memcmp(peers[i].mac, snapshot[i].mac, 6) == 0) {
            peers[i].owned = snapshot[i].owned;
            peers[i].ifIndex = snapshot[i].ifIndex;
        }
        if (peers[i].used && peers[i].owned)
            activeCount++;
    }
    stats.routeOwned = prefixOwned;
    stats.activeNeighbors = activeCount;
    IOLockUnlock(lock);
}

void MtkAwdlNeighborManager::stopBlocking()
{
    if (!initialized || !lock)
        return;

    IOLockLock(lock);
    stopping = true;
    desiredActive = false;
    IOLockUnlock(lock);

    if (workCall)
        thread_call_cancel_wait(workCall);

    // Final synchronous delete pass while stopping = true.
    runPass();
    closeSocket();
}

MtkAwdlNdp::Stats MtkAwdlNeighborManager::snapshotStats() const
{
    if (!lock)
        return stats;
    IOLockLock(lock);
    MtkAwdlNdp::Stats copy = stats;
    IOLockUnlock(lock);
    return copy;
}

#endif
