/*
 * Privacy-safe, lock-free kernel routing & NDP helper for AirportMtkWlan AWDL.
 * Copyright (C) 2026 AirportMtkWlan Contributors.
 * Licensed under GNU GPL v3.0 or later.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace MtkAwdlNdp {

static constexpr size_t kMaxRouteMsgBytes = 256;
static constexpr size_t kMaxPeers = 16;
static constexpr uint64_t kPeerIdleExpireNS = 30ULL * 1000ULL * 1000ULL * 1000ULL;
static constexpr unsigned kRefreshIntervalPasses = 15;

struct Stats {
    bool enabled = false;
    bool routeOwned = false;
    uint32_t activeNeighbors = 0;
    uint32_t routeAdds = 0;
    uint32_t neighborAdds = 0;
    uint32_t neighborDeletes = 0;
    uint32_t errors = 0;
    int32_t lastErrno = 0;
    uint32_t passes = 0;
};

inline void fillEui64LinkLocal(uint8_t ip6[16], uint16_t scopeIfIndex, const uint8_t mac[6])
{
    memset(ip6, 0, 16);
    ip6[0] = 0xfe;
    ip6[1] = 0x80;
    ip6[2] = static_cast<uint8_t>((scopeIfIndex >> 8) & 0xff);
    ip6[3] = static_cast<uint8_t>(scopeIfIndex & 0xff);
    ip6[8] = static_cast<uint8_t>(mac[0] ^ 0x02);
    ip6[9] = mac[1];
    ip6[10] = mac[2];
    ip6[11] = 0xff;
    ip6[12] = 0xfe;
    ip6[13] = mac[3];
    ip6[14] = mac[4];
    ip6[15] = mac[5];
}

inline size_t alignRouteSockaddr(size_t saLen)
{
    if (saLen == 0)
        return sizeof(uint32_t);
    return 1U + ((saLen - 1U) | (sizeof(uint32_t) - 1U));
}

} // namespace MtkAwdlNdp

#if defined(KERNEL) && defined(MTK_NATIVE_AWDL) && defined(AIRPORT_WCL) && __IO80211_TARGET == __MAC_26_0
#include <IOKit/IOLocks.h>
#include <kern/thread_call.h>

class MtkAwdlNeighborManager {
public:
    bool init(const char *ifName = "awdl0");
    void destroy();

    void updateDesiredState(bool awdlActive, uint64_t nowNS,
                            const uint8_t (*peerMacs)[6], size_t peerCount);
    void stopBlocking();

    MtkAwdlNdp::Stats snapshotStats() const;

private:
    struct PeerSlot {
        bool used = false;
        bool owned = false;
        uint8_t mac[6] = {};
        uint64_t lastSeenNS = 0;
        uint32_t ifIndex = 0;
    };

    static void workerTrampoline(thread_call_param_t p0, thread_call_param_t p1);
    void runPass();
    bool ensureSocket();
    void closeSocket();
    int sendRouteMsg(const void *buf, size_t len);
    int programPrefixRoute(uint8_t rtmType, uint32_t ifIndex);
    int programNeighborHost(uint8_t rtmType, uint32_t ifIndex, const uint8_t mac[6]);

    char ifName[16] = {};
    IOLock *lock = nullptr;
    thread_call_t workCall = nullptr;
    void *routeSock = nullptr;
    bool initialized = false;
    bool stopping = false;
    bool enabled = false;

    bool desiredActive = false;
    uint32_t currentIfIndex = 0;
    bool prefixOwned = false;
    uint32_t passSeq = 0;
    uint64_t latestNowNS = 0;
    PeerSlot peers[MtkAwdlNdp::kMaxPeers] = {};
    MtkAwdlNdp::Stats stats = {};
};
#endif
