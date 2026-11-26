#if defined(MTK_NATIVE_AWDL) && defined(AIRPORT_WCL) && __IO80211_TARGET == __MAC_26_0
// The Tahoe ABI and Skywalk registration sequence are adapted from
// ForbiddenItlwm (GPL-2.0), commit dc0f0bfe52b3318017e02c0b8ea7a84a40d7a61d.
#include "AirportItlwmV2.hpp"
#include "MtkAwdlInterface.hpp"
#include <Airport/macOS26/IO80211ManagementBuffer.h>
#include <Airport/macOS26/IOSkywalkPacketView.h>
#include <HAL/MtkAwdlActionFrame.hpp>
#include <HAL/MtkAwdlDiagnostics.hpp>
#include <libkern/sysctl.h>

OSDefineMetaClassAndStructors(MtkAWDLInterface, IO80211AWDLProtocol)

extern "C" {
OSObject *nativePeerManager(IO80211SkywalkInterface *) __asm__("__ZN23IO80211SkywalkInterface14getPeerManagerEv");
OSObject *nativeFindAwdlPeer(OSObject *, uint8_t *) __asm__("__ZN22IO80211AWDLPeerManager12findAWDLPeerEPh");
const uint8_t *nativeGetPeerMac(OSObject *) __asm__("__ZN11IO80211Peer13getMacAddressEv");
const char *nativeGetPeerHostname(OSObject *) __asm__("__ZN15IO80211AWDLPeer11getHostnameEv");
extern const uintptr_t nativeAwdlVtable[] __asm__("__ZTV19IO80211AWDLProtocol");
void nativeAwdlDestructor() __asm__("__ZN19IO80211AWDLProtocolD1Ev");
void nativeWakeFlags() __asm__("__ZN25IOSkywalkNetworkInterface21getSupportedWakeFlagsEPj");
void nativeInterfaceCCA() __asm__("__ZN23IO80211SkywalkInterface15setInterfaceCCAE18apple80211_channeli");
void nativeStatsDump() __asm__("__ZN23IO80211SkywalkInterface9statsDumpEv");
void nativeSyncDPSStats() __asm__("__ZN23IO80211SkywalkInterface12syncDPSStatsEP26apple82011_postMessage_dps");
void nativeVirtualReserved15() __asm__("__ZN23IO80211VirtualInterface34_RESERVEDIO80211VirtualInterface15Ev");
void nativePureVirtual() __asm__("___cxa_pure_virtual");
}

bool mtkAwdlTahoeAbiMatches()
{
    int no_awdl = 0;
    if (PE_parse_boot_argn("-mtknoawdl", &no_awdl, sizeof(no_awdl)))
        return false;
    // Verify all 9 IO80211AWDLProtocol vtable slots against live kernel symbols across Tahoe builds.
    char build[32] = {};
    size_t length = sizeof(build) - 1;
    (void)sysctlbyname("kern.osversion", build, &length, nullptr, 0);

    const auto *slots = nativeAwdlVtable + 2;
    const uintptr_t pure = reinterpret_cast<uintptr_t>(&nativePureVirtual);
    return slots[0] == reinterpret_cast<uintptr_t>(&nativeAwdlDestructor) &&
        slots[300] == reinterpret_cast<uintptr_t>(&nativeWakeFlags) &&
        slots[380] == reinterpret_cast<uintptr_t>(&nativeInterfaceCCA) &&
        slots[420] == reinterpret_cast<uintptr_t>(&nativeStatsDump) &&
        slots[460] == reinterpret_cast<uintptr_t>(&nativeSyncDPSStats) &&
        slots[504] == reinterpret_cast<uintptr_t>(&nativeVirtualReserved15) &&
        slots[505] == pure && slots[567] == pure && !slots[568];
}

IOReturn MtkAWDLInterface::record(const char *operation, IOReturn result)
{
    // Report the last return code per callback. Keep payloads private.
    char key[112];
    snprintf(key, sizeof(key), "MtkAwdlConfig.%s", operation);
    const auto code = static_cast<UInt32>(result);
    auto *previous = copyProperty(key);
    auto *number = OSDynamicCast(OSNumber, previous);
    const bool changed = !number || number->unsigned32BitValue() != code;
    OSSafeReleaseNULL(previous);
    if (changed) {
        setProperty(key, code, 32);
        const unsigned event = __atomic_add_fetch(&configurationChanges, 1, __ATOMIC_RELAXED);
        if (event <= 48) {
            char eventKey[40];
            char detail[152];
            snprintf(eventKey, sizeof(eventKey), "MtkAwdlCallback%02u", event);
            snprintf(detail, sizeof(detail), "%llu us %s result=0x%x",
                     static_cast<unsigned long long>(clockUS()), operation, code);
            setProperty(eventKey, detail);
        }
        IOLog("MTK AWDL: configuration callback #%u %s result=0x%x\n", event, operation, code);
    }
    return result;
}

bool MtkAWDLInterface::prepareConfiguration(const ieee80211com &ic, const MtkAwdl::PeerIdentity &peer)
{
    testPeer = peer;
    memcpy(timingPeer, peer.address, sizeof(timingPeer));
    configurationLock = IOLockAlloc();
    if (!configurationLock)
        return false;
    for (unsigned i = 1; i <= IEEE80211_CHAN_MAX; ++i) {
        if (ic.ic_channels[i].ic_freq)
            configuration.addSupportedChannel(i);
    }
    (void)neighbors.init("awdl0");
    return true;
}

IOReturn MtkAWDLInterface::getSSID(apple80211_ssid_data *data)
{
    if (!data)
        return kIOReturnBadArgument;
    memset(data, 0, sizeof(*data));
    data->version = APPLE80211_VERSION;
    data->ssid_len = 4;
    memcpy(data->ssid_bytes, "AWDL", 4);
    return record(__func__, kIOReturnSuccess);
}

IOReturn MtkAWDLInterface::getCHANNEL(apple80211_channel_data *data)
{
    if (!data)
        return kIOReturnBadArgument;
    memset(data, 0, sizeof(*data));
    data->version = APPLE80211_VERSION;
    data->channel.version = APPLE80211_VERSION;
    const uint8_t ch = activeChannel ? activeChannel : 6;
    data->channel.channel = ch;
    data->channel.flags = APPLE80211_C_FLAG_20MHZ |
        ((ch <= 14) ? APPLE80211_C_FLAG_2GHZ : APPLE80211_C_FLAG_5GHZ);
    return record(__func__, kIOReturnSuccess);
}

IOReturn MtkAWDLInterface::getBSSID(apple80211_bssid_data *data)
{
    if (!data)
        return kIOReturnBadArgument;
    memset(data, 0, sizeof(*data));
    data->version = APPLE80211_VERSION;
    apple80211_awdl_bssid awdlBssid = {};
    if (configurationLock) {
        IOLockLock(configurationLock);
        const bool has = (configuration.bssid.read(&awdlBssid) == kIOReturnSuccess);
        IOLockUnlock(configurationLock);
        if (has) {
            memcpy(data->bssid.octet, awdlBssid.bssid, ETHER_ADDR_LEN);
            return record(__func__, kIOReturnSuccess);
        }
    }
    static constexpr uint8_t kDefaultAwdlBssid[6] = {0x00, 0x25, 0x00, 0xff, 0x94, 0x73};
    memcpy(data->bssid.octet, kDefaultAwdlBssid, ETHER_ADDR_LEN);
    return record(__func__, kIOReturnSuccess);
}

IOReturn MtkAWDLInterface::getSTATE(apple80211_state_data *data)
{
    if (!data)
        return kIOReturnBadArgument;
    memset(data, 0, sizeof(*data));
    data->version = APPLE80211_VERSION;
    data->state = activeChannel ? IEEE80211_S_RUN : IEEE80211_S_INIT;
    return record(__func__, kIOReturnSuccess);
}

IOReturn MtkAWDLInterface::getPEER_CACHE_MAXIMUM_SIZE(apple80211_peer_cache_maximum_size *data)
{
    if (!data)
        return kIOReturnBadArgument;
    memset(data, 0, sizeof(*data));
    data->version = APPLE80211_VERSION;
    data->max_peers = 32;
    return record(__func__, kIOReturnSuccess);
}

IOReturn MtkAWDLInterface::setAWDL_BSSID(apple80211_awdl_bssid *data)
{
    return configure(__func__, [&] { return configuration.bssid.set(data); });
}

IOReturn MtkAWDLInterface::getAWDL_ELECTION_ID(apple80211_awdl_election_id *data)
{
    return configure(__func__, [&] { return configuration.electionId.read(data); });
}

IOReturn MtkAWDLInterface::setAWDL_ELECTION_ID(apple80211_awdl_election_id *data)
{
    return configure(__func__, [&] { return configuration.electionId.set(data); });
}

IOReturn MtkAWDLInterface::getAWDL_ELECTION_METRIC(apple80211_awdl_election_metric *data)
{
    return configure(__func__, [&] { return configuration.electionMetric.read(data); });
}

IOReturn MtkAWDLInterface::setAWDL_ELECTION_METRIC(apple80211_awdl_election_metric *data)
{
    return configure(__func__, [&] { return configuration.electionMetric.set(data); });
}

IOReturn MtkAWDLInterface::getAWDL_MASTER_CHANNEL(apple80211_awdl_master_channel *data)
{
    return configure(__func__, [&] { return configuration.readMasterChannel(data); });
}

IOReturn MtkAWDLInterface::setAWDL_MASTER_CHANNEL(apple80211_awdl_master_channel *data)
{
    return configure(__func__, [&] {
        const IOReturn result = configuration.setMasterChannel(data);
        if (result == kIOReturnSuccess)
            setProperty("MtkAwdlMasterChannel", data->master_channel, 32);
        return result;
    });
}

IOReturn MtkAWDLInterface::getAWDL_SECONDARY_MASTER_CHANNEL(apple80211_awdl_secondary_master_channel *data)
{
    return configure(__func__, [&] { return configuration.readSecondaryMasterChannel(data); });
}

IOReturn MtkAWDLInterface::setAWDL_SECONDARY_MASTER_CHANNEL(apple80211_awdl_secondary_master_channel *data)
{
    return configure(__func__, [&] {
        const IOReturn result = configuration.setSecondaryMasterChannel(data);
        if (result == kIOReturnSuccess)
            setProperty("MtkAwdlSecondaryMasterChannel", data->secondary_master_channel, 32);
        return result;
    });
}

IOReturn MtkAWDLInterface::getAWDL_ELECTION_RSSI_THRESHOLDS(apple80211_awdl_election_rssi_thresholds *data)
{
    return configure(__func__, [&] { return configuration.electionRssiThresholds.read(data); });
}

IOReturn MtkAWDLInterface::setAWDL_ELECTION_RSSI_THRESHOLDS(apple80211_awdl_election_rssi_thresholds *data)
{
    // Copy the declared record only. Native internal callers may supply
    // additional fields outside this declaration.
    return configure(__func__, [&] { return configuration.electionRssiThresholds.set(data); });
}

IOReturn MtkAWDLInterface::getAWDL_MIN_RATE(apple80211_awdl_min_rate *data)
{
    return configure(__func__, [&] { return configuration.minRate.read(data); });
}

IOReturn MtkAWDLInterface::setAWDL_MIN_RATE(apple80211_awdl_min_rate *data)
{
    return configure(__func__, [&] { return configuration.minRate.set(data); });
}

IOReturn MtkAWDLInterface::getAWDL_SYNC_STATE(apple80211_awdl_sync_state *data)
{
    return configure(__func__, [&] { return configuration.readSyncState(data); });
}

IOReturn MtkAWDLInterface::setAWDL_SYNC_STATE(apple80211_awdl_sync_state *data)
{
    return configure(__func__, [&] {
        const IOReturn result = configuration.setSyncState(data);
        if (result == kIOReturnSuccess)
            setProperty("MtkAwdlSyncStateRequested", data->state, 32);
        return result;
    });
}

IOReturn MtkAWDLInterface::getAWDL_SYNC_PARAMS(apple80211_awdl_sync_params *data)
{
    return configure(__func__, [&] { return configuration.syncParams.read(data); });
}

IOReturn MtkAWDLInterface::setAWDL_SYNC_PARAMS(apple80211_awdl_sync_params *data)
{
    return configure(__func__, [&] { return configuration.syncParams.set(data); });
}

IOReturn MtkAWDLInterface::getAWDL_SYNC_ENABLED(apple80211_awdl_sync_enabled *data)
{
    return configure(__func__, [&] {
        const IOReturn result = configuration.readSyncEnabled(data);
        if (result == kIOReturnSuccess)
            setProperty("MtkAwdlSyncReadbackEnabled", data->enabled != 0);
        return result;
    });
}

IOReturn MtkAWDLInterface::setAWDL_SYNC_ENABLED(apple80211_awdl_sync_enabled *data)
{
    return configure(__func__, [&] {
        setProperty("MtkAwdlSyncEnableCalls", ++syncEnableCalls, 32);
        if (data)
            setProperty("MtkAwdlSyncEnableLastValue", data->enabled, 32);
        const IOReturn result = configuration.setSyncEnabled(data);
        if (result == kIOReturnSuccess) {
            if (!data->enabled) {
                masterIndicationLength = 0;
                masterIndicationHasAirDropPtr = false;
                setProperty("MtkAwdlMIAirDropPTR", UInt64(0), 32);
                setProperty("MtkAwdlMIServiceRecordStatus", "sync disabled");
                setProperty("MtkAwdlMIServicesCurrent", UInt64(0), 32);
                setProperty("MtkAwdlMIAirDrop", false);
            }
            setProperty("MtkAwdlSyncRequested", data->enabled != 0);
        }
        return result;
    });
}

IOReturn MtkAWDLInterface::getAWDL_SYNCHRONIZATION_CHANNEL_SEQUENCE(
    apple80211_awdl_sync_channel_sequence *data)
{
    return configure(__func__, [&] { return configuration.readSequence(data); });
}

IOReturn MtkAWDLInterface::setAWDL_SYNCHRONIZATION_CHANNEL_SEQUENCE(
    apple80211_awdl_sync_channel_sequence *data)
{
    return configure(__func__, [&] {
        const IOReturn result = configuration.setSequence(data);
        if (result == kIOReturnSuccess)
            setProperty("MtkAwdlSequenceLength", data->length, 32);
        return result;
    });
}

IOReturn MtkAWDLInterface::setAWDL_SYNC_FRAME_TEMPLATE(apple80211_awdl_sync_frame_template *data)
{
    return configure(__func__, [&] {
        const IOReturn result = configuration.setFrameTemplate(data);
        if (result == kIOReturnSuccess)
            setProperty("MtkAwdlTemplateBytes", configuration.frameTemplateLength(), 32);
        return result;
    });
}

IOReturn MtkAWDLInterface::setAWDL_OOB_AUTO_REQUEST(apple80211_awdl_oob_request *request)
{
    // Registration is already restricted to the audited 25G342 Tahoe ABI.
    // The callback runs synchronously under the controller's command gate.
    return configure(__func__, [&] {
        setProperty("MtkAwdlMIRequests", ++masterIndicationRequests, 32);
        auto reject = [this](const char *reason, IOReturn code) {
            setProperty("MtkAwdlMILastRejection", reason);
            return code;
        };
        if (!workLoop || !workLoop->inGate())
            return reject("outside shared gate", kIOReturnNotReady);
        if (!request)
            return reject("missing request", kIOReturnBadArgument);

        const auto *manager = nativePeerManager(this);
        if (!manager || strcmp(manager->getMetaClass()->getClassName(), "IO80211AWDLPeerManager") != 0)
            return reject("peer manager unavailable", kIOReturnNotReady);

        // Only accept the primary template owned by this interface's peer
        // manager. Never read through the address supplied in the request.
        // 25G342 updatePrimaryPayloadMI builds into state+0x2358 (1200 bytes),
        // stores its length at +0x2808 and passes pointer and length at +0x30/+0x28.
        const uint8_t *state = nullptr;
        memcpy(&state, reinterpret_cast<const uint8_t *>(manager) + 0x20, sizeof(state));
        if (!state)
            return reject("peer manager state unavailable", kIOReturnNotReady);
        const auto *ownedTemplate = state + 0x2358;
        uint32_t ownedLength = 0;
        memcpy(&ownedLength, state + 0x2808, sizeof(ownedLength));
        const uint8_t *supplied = nullptr;
        memcpy(&supplied, reinterpret_cast<const uint8_t *>(request) + 0x30, sizeof(supplied));
        const uint16_t length = request->data_len;
        if (supplied != ownedTemplate || length != ownedLength || !length ||
            length > sizeof(masterIndication))
            return reject("request does not match primary template", kIOReturnBadArgument);

        memcpy(masterIndicationSnapshot, ownedTemplate, length);
        MtkAwdl::ServiceSummary services;
        if (!MtkAwdl::inspectMasterIndication(masterIndicationSnapshot, length, services))
            return reject("invalid primary template", kIOReturnBadArgument);

        const bool changed = length != masterIndicationLength ||
            memcmp(masterIndication, masterIndicationSnapshot, length) != 0;
        memcpy(masterIndication, masterIndicationSnapshot, length);
        masterIndicationLength = length;
        masterIndicationHasAirDropPtr = services.airDropPtrs != 0;
        if (changed) {
            setProperty("MtkAwdlMIAirDropPTR", services.airDropPtrs, 32);
            setProperty("MtkAwdlMIAirDropOtherTypes", services.airDropOtherTypes, 32);
            setProperty("MtkAwdlMIAirDropBadLengths", services.airDropBadLengths, 32);
            setProperty("MtkAwdlMIAirDropBadTargets", services.airDropBadTargets, 32);
            setProperty("MtkAwdlMIAirDropShortTargets", services.airDropShortTargets, 32);
            setProperty("MtkAwdlMIAirDropCorroborated", services.airDropCorroborated, 32);
            setProperty("MtkAwdlMIAirDropTargetBytes", services.airDropTargetBytes, 32);
            setProperty("MtkAwdlMIAirDropTargetLabelBytes", services.airDropTargetLabelBytes, 32);
            setProperty("MtkAwdlMIAirDropOtherHints", services.airDropOtherHints, 32);
            setProperty("MtkAwdlMIServiceUnknownLayouts", services.serviceUnknownLayouts, 32);
            const char *status = services.airDropPtrs ? "AirDrop PTR decoded" :
                services.airDropBadLengths || services.airDropBadTargets ? "AirDrop PTR rejected" :
                services.airDropOtherHints || services.serviceUnknownLayouts ? "unresolved service record" :
                services.airDropOtherTypes ? "AirDrop owner with other DNS type" : "no AirDrop PTR recognized";
            setProperty("MtkAwdlMIServiceRecordStatus", status);
        }
        serviceRecordsReceived += services.records;
        setProperty("MtkAwdlMIAccepted", ++masterIndicationAccepted, 32);
        setProperty("MtkAwdlMIServicesReceived", serviceRecordsReceived, 64);
        if (changed) {
            setProperty("MtkAwdlMIBytes", length, 32);
            setProperty("MtkAwdlMIServicesCurrent", services.records, 32);
            setProperty("MtkAwdlMIAirDrop", services.airDrop);
            IOLog("MTK AWDL: native MI bytes=%u serviceTLVs=%u airDrop=%u\n",
                  length, services.records, unsigned(services.airDrop));
        }
        return kIOReturnSuccess;
    });
}

IOReturn MtkAWDLInterface::setMacAddress(ether_addr &address)
{
    // wifip2pd can continue with its requested address. Keep it local to this
    // virtual interface and leave the infrastructure MAC and radio untouched.
    uint64_t raw = 0;
    memcpy(&raw, &address, sizeof(address));
    if (!raw || (address.octet[0] & 1))
        return record("setMacAddress", kIOReturnBadArgument);
    __atomic_store_n(&requestedMac, raw, __ATOMIC_RELAXED);
    return record("setMacAddress", kIOReturnSuccess);
}

namespace {
// Tahoe's management input expects the peer address, channel and RSSI at
// these offsets. Match the native layout used by ForbiddenItlwm.
struct AwdlManagementMetadata {
    uint8_t peer[6];
    uint8_t reserved[6];
    uint32_t version;
    uint32_t channel;
    uint32_t channelFlags;
    uint8_t reservedBeforeRssi[20];
    int32_t rssi;
    uint8_t reservedAfterRssi[24];
};
static_assert(sizeof(AwdlManagementMetadata) == 72, "Tahoe AWDL management metadata size");
static_assert(__builtin_offsetof(AwdlManagementMetadata, version) == 12, "Tahoe AWDL channel offset");
static_assert(__builtin_offsetof(AwdlManagementMetadata, rssi) == 0x2c, "Tahoe AWDL RSSI offset");
}

IOReturn MtkAWDLInterface::submitAction(IO80211Controller *controller, mbuf_t packet,
                                       uint32_t channel, int32_t rssi)
{
    if (!nativeStarted || !workLoop || !workLoop->inGate()) {
        ++rxActionBeforeNativeReady;
        return kIOReturnNotReady;
    }

    apple80211_awdl_sync_enabled request = {};
    IOLockLock(configurationLock);
    configuration.readSyncEnabled(&request);
    IOLockUnlock(configurationLock);
    if (!request.enabled) {
        ++rxActionWhileSyncOff;
        return kIOReturnNotReady;
    }
    if (!packet || mbuf_next(packet) || mbuf_len(packet) != mbuf_pkthdr_len(packet) ||
        !channel || channel > IEEE80211_CHAN_MAX || rssi >= 0 || rssi <= -128)
        return kIOReturnBadArgument;

    const auto *frame = static_cast<const uint8_t *>(mbuf_data(packet));
    const size_t length = MtkAwdl::actionFrameLength(frame, mbuf_len(packet));
    if (!length)
        return kIOReturnBadArgument;

    const auto rxUS = clockUS();
    auto *pool = itlGetMgmtFramePool(controller);
    auto *buffer = pool ? pool->getBuffer() : nullptr;
    if (!buffer)
        return kIOReturnNoResources;
    auto *body = buffer->getBytesNoCopy();
    const size_t bodyLength = length - MtkAwdl::actionHeaderLength;
    if (!body || bodyLength > buffer->getCapacity()) {
        buffer->returnBuffer();
        return kIOReturnNoSpace;
    }
    memcpy(body, frame + MtkAwdl::actionHeaderLength, bodyLength);
    buffer->setLength(bodyLength);

    AwdlManagementMetadata metadata = {};
    memcpy(metadata.peer, frame + 10, sizeof(metadata.peer));
    metadata.version = APPLE80211_VERSION;
    metadata.channel = channel;
    metadata.channelFlags = channel <= 14 ? APPLE80211_C_FLAG_2GHZ : APPLE80211_C_FLAG_5GHZ;
    metadata.rssi = rssi;
    // The native handler consumes the buffer lease on every path.
    itlSubmitMgmtFrame(this, buffer, 12, &metadata, sizeof(metadata));
    observePeerTiming(frame, length, channel, rxUS);
    return kIOReturnSuccess;
}

void MtkAWDLInterface::observeAction(IO80211Controller *controller, mbuf_t packet,
                                     uint32_t channel, int32_t rssi)
{
    const unsigned sample = ++rxActionCandidates;
    const IOReturn result = submitAction(controller, packet, channel, rssi);
    if (result == kIOReturnSuccess)
        ++rxActionSubmitted;
    else
        ++rxActionRejected;
    // Keep a bounded amount of logging on the receive path.
    if (sample <= 8 || !(sample & (sample - 1))) {
        setProperty("MtkAwdlRxCandidates", rxActionCandidates, 32);
        setProperty("MtkAwdlRxSubmitted", rxActionSubmitted, 32);
        setProperty("MtkAwdlRxRejected", rxActionRejected, 32);
        setProperty("MtkAwdlRxBeforeNativeReady", rxActionBeforeNativeReady, 32);
        setProperty("MtkAwdlRxWhileSyncOff", rxActionWhileSyncOff, 32);
        setProperty("MtkAwdlRxChannel", channel, 32);
        setProperty("MtkAwdlRxLastResult", static_cast<UInt32>(result), 32);
        IOLog("MTK AWDL: action RX candidates=%u submitted=%u rejected=%u channel=%u rssi=%d result=0x%x\n",
              rxActionCandidates, rxActionSubmitted, rxActionRejected, channel, rssi,
              static_cast<UInt32>(result));
    }
}

uint64_t MtkAWDLInterface::clockUS()
{
    uint64_t nowNS = 0;
    absolutetime_to_nanoseconds(mach_absolute_time(), &nowNS);
    return nowNS / 1000;
}

void MtkAWDLInterface::publishTimingPeer()
{
    char peerAddress[18];
    snprintf(peerAddress, sizeof(peerAddress), "%02x:%02x:%02x:%02x:%02x:%02x",
             timingPeer[0], timingPeer[1], timingPeer[2], timingPeer[3], timingPeer[4], timingPeer[5]);
    setProperty("MtkAwdlTimingPeer", peerAddress);
}

MtkAWDLInterface::PeerObservation &MtkAWDLInterface::recordPeer(
    const uint8_t *frame, size_t length, uint32_t channel, uint64_t now, bool &hasSchedule)
{
    const auto *source = frame + 10;
    PeerObservation *entry = &observedPeers[0];
    for (auto &candidate : observedPeers) {
        if (candidate.frames && candidate.channel == channel &&
            !memcmp(candidate.address, source, sizeof(candidate.address))) {
            entry = &candidate;
            break;
        }
        if (candidate.lastFrameUS < entry->lastFrameUS)
            entry = &candidate;
    }
    if (!entry->frames || entry->channel != channel ||
        memcmp(entry->address, source, sizeof(entry->address))) {
        *entry = PeerObservation{};
        memcpy(entry->address, source, sizeof(entry->address));
        entry->channel = channel;
    }
    ++entry->frames;
    entry->lastFrameUS = now;
    const auto arpa = MtkAwdl::inspectArpaName(frame, length, testPeer.hostname);
    if (arpa != MtkAwdl::ArpaName::Absent && arpa >= entry->arpa)
        entry->arpa = arpa;
    ItlAWDL::PeerSyncInfo sync;
    hasSchedule = ItlAWDL::peerSyncFromAction(frame, length, &sync);
    if (hasSchedule) {
        ++entry->schedules;
        entry->sync = sync;
        entry->lastScheduleUS = now;
    }
    return *entry;
}

void MtkAWDLInterface::reviewPeers(uint64_t now)
{
    if (!nativeStarted || !workLoop || !workLoop->inGate() || now < nextPeerReviewUS)
        return;
    nextPeerReviewUS = now + 500000;
    auto *manager = nativePeerManager(this);
    if (!manager || strcmp(manager->getMetaClass()->getClassName(), "IO80211AWDLPeerManager"))
        manager = nullptr;

    constexpr uint8_t zero[6] = {};
    PeerObservation *matched = nullptr;
    unsigned matches = 0;
    unsigned index = 0;
    for (auto &entry : observedPeers) {
        unsigned slot = index++;
        if (!entry.frames)
            continue;
        const auto age = now - entry.lastFrameUS;
        const bool fresh = age < ItlAWDL::kPeerScheduleStaleUS;
        auto *peer = manager && fresh ? nativeFindAwdlPeer(manager, entry.address) : nullptr;
        const auto *nativeAddress = peer ? nativeGetPeerMac(peer) : nullptr;
        const bool sameAddress = nativeAddress && !memcmp(nativeAddress, entry.address, sizeof(entry.address));
        const char *name = sameAddress ? nativeGetPeerHostname(peer) : nullptr;
        const bool nameMatched = name && MtkAwdl::matchNativeHostname(name, testPeer.hostname);
        if (nameMatched && entry.channel == activeChannel && entry.lastScheduleUS &&
            now - entry.lastScheduleUS < ItlAWDL::kPeerScheduleStaleUS) {
            matched = &entry;
            ++matches;
        }
        char key[32], text[160];
        snprintf(key, sizeof(key), "MtkAwdlPeerCandidate%u", slot);
        snprintf(text, sizeof(text), "%02x:%02x:%02x:%02x:%02x:%02x chan=%u frames=%u sync=%u arpa=%u native=%s age_ms=%llu",
                 entry.address[0], entry.address[1], entry.address[2], entry.address[3], entry.address[4],
                 entry.address[5], entry.channel, entry.frames, entry.schedules, unsigned(entry.arpa),
                 nameMatched ? "matched" : name && *name ? "different-name" :
                 sameAddress ? "unnamed" : fresh ? "not-found" : "stale",
                 static_cast<unsigned long long>(age / 1000));
        setProperty(key, text);
    }

    if (matches != 1 || !testPeer.hostname[0] || memcmp(timingPeer, zero, sizeof(timingPeer)))
        return;
    memcpy(timingPeer, matched->address, sizeof(timingPeer));
    targetFrames = matched->frames;
    targetSchedules = matched->schedules;
    noteSchedule(matched->sync, matched->lastScheduleUS);
    setProperty("MtkAwdlPeerNameMatched", true);
    setProperty("MtkAwdlNativePeerMatched", true);
    setProperty("MtkAwdlTargetFrames", targetFrames, 32);
    setProperty("MtkAwdlTargetSchedules", targetSchedules, 32);
    setProperty("MtkAwdlTargetRxChannel", activeChannel, 32);
    publishTimingPeer();
}

void MtkAWDLInterface::observePeerTiming(const uint8_t *frame, size_t length, uint32_t channel, uint64_t now)
{
    const uint64_t own = __atomic_load_n(&requestedMac, __ATOMIC_RELAXED);
    constexpr uint8_t zero[6] = {};
    const auto *source = frame + 10;
    if ((source[0] & 1) || !memcmp(source, &own, 6) || !memcmp(source, zero, 6))
        return;
    bool hasSchedule = false;
    const auto &entry = recordPeer(frame, length, channel, now, hasSchedule);
    if (!memcmp(timingPeer, zero, sizeof(timingPeer))) {
        if (!testPeer.hostname[0] && activeChannel && channel == activeChannel && hasSchedule) {
            memcpy(timingPeer, source, sizeof(timingPeer));
            setProperty("MtkAwdlAutoTimingPeer", true);
            publishTimingPeer();
        } else {
            return;
        }
    } else if (memcmp(source, timingPeer, sizeof(timingPeer))) {
        return;
    }
    ++targetFrames;
    if (targetFrames <= 4 || !(targetFrames % 8)) {
        setProperty("MtkAwdlTargetFrames", targetFrames, 32);
        setProperty("MtkAwdlTargetRxChannel", channel, 32);
    }
    if (!activeChannel || channel != activeChannel)
        return;
    if (!hasSchedule)
        return;
    ++targetSchedules;
    if (targetSchedules <= 4 || !(targetSchedules % 8))
        setProperty("MtkAwdlTargetSchedules", targetSchedules, 32);
    noteSchedule(entry.sync, now);
}

void MtkAWDLInterface::noteSchedule(const ItlAWDL::PeerSyncInfo &sync, uint64_t now)
{
    using Update = ItlAWDL::PeerSchedule::Update;
    uint64_t into = 0;
    const bool hadAnchor = peerSchedule.fresh(now) && peerSchedule.eawUS;
    const uint32_t prior = hadAnchor ? peerSchedule.eawAt(now, &into) : 0;
    const auto update = peerSchedule.note(sync, now, activeChannel);
    const bool reanchored = update != Update::Stable;
    if (reanchored) {
        windowEvidence = {};
        ++scheduleEpochs;
        scheduleGaps += update == Update::Gap;
        phaseReanchors += update == Update::Phase;
        char sequence[80] = {};
        size_t used = 0;
        for (const auto channel : sync.channels)
            used += snprintf(sequence + used, sizeof(sequence) - used, "%s%u", used ? "," : "", channel);
        setProperty("MtkAwdlWindowPeerSequence", sequence);
    } else if (hadAnchor && into >= ItlAWDL::kPeerEdgeUS && peerSchedule.eawUS - into >= ItlAWDL::kPeerEdgeUS) {
        const bool wasKnown = peerSchedule.known();
        const auto oldOffset = peerSchedule.entryOffset();
        const bool previousMatch = wasKnown && peerSchedule.presentInEntry(prior);
        peerSchedule.notePeerEntry(prior, into);
        if (wasKnown != peerSchedule.known() || oldOffset != peerSchedule.entryOffset())
            windowEvidence = {};
        else if (wasKnown)
            windowEvidence.add(previousMatch);
    }
    if (reanchored || targetSchedules <= 8 || !(targetSchedules % 8)) {
        setProperty("MtkAwdlWindowRxSamples", UInt64(windowEvidence.samples), 32);
        setProperty("MtkAwdlWindowRxMatches", windowEvidence.matches(), 32);
        setProperty("MtkAwdlWindowChannelSlots", peerSchedule.presentEntries(), 32);
        setProperty("MtkAwdlWindowSeqChanges", peerSchedule.sequenceChanges, 32);
        setProperty("MtkAwdlWindowEpochs", scheduleEpochs, 32);
        setProperty("MtkAwdlWindowGapReanchors", scheduleGaps, 32);
        setProperty("MtkAwdlWindowPhaseReanchors", phaseReanchors, 32);
        setProperty("MtkAwdlWindowOffsetRefutations", peerSchedule.refutations, 32);
        setProperty("MtkAwdlWindowOffsetCalibrations", peerSchedule.calibrations, 32);
        setProperty("MtkAwdlWindowSlotOffset", UInt64(peerSchedule.entryOffset()), 32);
        setProperty("MtkAwdlWindowPeerAW", UInt64(sync.awCounter), 32);
        setProperty("MtkAwdlWindowPeerDownTU", UInt64(sync.downCounterTU), 32);
        setProperty("MtkAwdlWindowHostRxUS", now, 64);
        char phase[20];
        snprintf(phase, sizeof(phase), "%d us", peerSchedule.phaseErrorUS);
        setProperty("MtkAwdlWindowPhaseError", phase);
    }
}

MtkAWDLInterface::WindowState MtkAWDLInterface::windowState(uint64_t now) const
{
    if (!peerSchedule.valid)
        return WindowState::NoSchedule;
    if (!peerSchedule.fresh(now))
        return WindowState::Stale;
    if (!peerSchedule.presentEntries())
        return WindowState::NoSlots;
    if (!peerSchedule.known())
        return WindowState::OffsetUnknown;
    if (windowEvidence.samples < 8)
        return WindowState::Collecting;
    if (!windowEvidence.reliable())
        return WindowState::LowAgreement;
    return peerSchedule.inPresentAwStart(now, 4500) ? WindowState::Eligible : WindowState::Waiting;
}

void MtkAWDLInterface::publishWindowState(uint64_t now)
{
    const auto state = windowState(now);
    // Keep the reason stable across crossings between eligible/not-yet-due slots.
    const auto reason = state == WindowState::Eligible ? WindowState::Waiting : state;
    if (windowStatePublished && reason == lastWindowState)
        return;
    windowStatePublished = true;
    lastWindowState = reason;
    const char *labels[] = {"no schedule", "stale schedule", "no slots on this channel",
        "offset unresolved", "collecting samples", "low agreement", "window tracking", "window tracking"};
    setProperty("MtkAwdlWindowState", labels[unsigned(reason)]);
    IOLog("MTK AWDL: window state=%s agreement=%u/%u epochs=%u phaseReanchors=%u\n",
        labels[unsigned(reason)], windowEvidence.matches(), windowEvidence.samples,
        scheduleEpochs, phaseReanchors);
}

void MtkAWDLInterface::refreshChannel(AirportItlwm *controller)
{
    bool allowed = false;
    const uint8_t channel = controller->getAwdlChannel(allowed);
    if (infraChannel != channel) {
        infraChannel = channel;
        setProperty("MtkAwdlInfraChannel", channel, 32);
    }
    const uint8_t next = allowed ? channel : 0;
    if (next == activeChannel)
        return;

    activeChannel = next;
    for (auto &entry : observedPeers)
        entry = PeerObservation{};
    for (unsigned slot = 0; slot < peerObservationLimit; ++slot) {
        char key[32];
        snprintf(key, sizeof(key), "MtkAwdlPeerCandidate%u", slot);
        removeProperty(key);
    }
    nextPeerReviewUS = 0;
    setProperty("MtkAwdlNativePeerMatched", false);
    peerSchedule.reset();
    targetFrames = targetSchedules = 0;
    windowEvidence = {};
    scheduleEpochs = scheduleGaps = phaseReanchors = 0;
    if (testPeer.hostname[0]) {
        memset(timingPeer, 0, sizeof(timingPeer));
        removeProperty("MtkAwdlTimingPeer");
        setProperty("MtkAwdlPeerNameMatched", false);
    }
    setProperty("MtkAwdlTargetFrames", UInt64(0), 32);
    removeProperty("MtkAwdlTargetRxChannel");
    verifiedAnnouncementsQueued = 0;
    controller->readAwdlAnnouncementCompletions(lastCompletions);
    peerFirmwareBaseline = lastCompletions.verifiedServiceSent;
    nextAnnouncement = 0;
    nextIsMI = false;
    if (ipv6Enabled) {
        ipv6Enabled = false;
        dataRejected += dataQueued;
        dataQueued = 0;
        drainDataCompletions();
        for (auto *q : queues)
            if (q)
                q->disable();
        setRunningState(false);
        setProperty("MtkAwdlIPv6Enabled", false);
        setProperty("MtkAwdlQueuesEnabled", false);
    }
    setProperty("MtkAwdlActiveChannel", next, 32);
    removeProperty("MtkAwdlWindowPeerSequence");
    setProperty("MtkAwdlWindowRxSamples", UInt64(0), 32);
    setProperty("MtkAwdlWindowRxMatches", UInt64(0), 32);
    setProperty("MtkAwdlWindowChannelSlots", UInt64(0), 32);
    setProperty("MtkAwdlTargetSchedules", UInt64(0), 32);
    setProperty("MtkAwdlWindowAirDropPTRQueued", UInt64(0), 32);
    setProperty("MtkAwdlWindowAirDropPTRFirmwareSent", UInt64(0), 32);
    setProperty("MtkAwdlWindowCompletionLastUS", UInt64(0), 32);
    setProperty("MtkAwdlWindowCompletionMaxUS", UInt64(0), 32);
    IOLog("MTK AWDL: associated primary channel=%u, AWDL transmit channel=%u\n", channel, next);
}

void MtkAWDLInterface::announcementTimerFired(OSObject *owner, IOTimerEventSource *timer)
{
    auto *interface = static_cast<MtkAWDLInterface *>(owner);
    if (interface->isInactive())
        return;
    auto *controller = OSDynamicCast(AirportItlwm, interface->getProvider());
    auto now = clockUS();
    if (controller && mtk_awdl_diagnostics_enabled()) {
        interface->refreshChannel(controller);
        interface->syncHardwareMac(controller);
        interface->syncIPv6State(controller);
        interface->reviewPeers(now);
        interface->syncNeighbors(now);
        interface->publishWindowState(now);
        interface->publishCompletions(controller);
        interface->drainDataCompletions();
        now = clockUS();
        if (interface->activeChannel && now >= interface->nextAnnouncement)
            interface->sendAnnouncement(controller, now);
        if (interface->ipv6Enabled) {
            interface->serviceData(controller, now);
            interface->drainDataCompletions();
        }
    }
    uint64_t delayUS = 20000;
    if (interface->nextAnnouncement > now && interface->nextAnnouncement - now < delayUS)
        delayUS = interface->nextAnnouncement - now;
    if (interface->windowEvidence.reliable() &&
        (interface->ipv6Enabled || now >= interface->nextAnnouncement)) {
        const auto next = interface->peerSchedule.usUntilPresentAw(now);
        if (next && next < delayUS)
            delayUS = next;
    }
    if (interface->ipv6Enabled) {
        if (interface->dataQueued)
            delayUS = 300;
        else if (delayUS > 2000)
            delayUS = 2000;
    }
    timer->setTimeoutUS(unsigned(delayUS < 300 ? 300 : delayUS));
}

void MtkAWDLInterface::sendAnnouncement(AirportItlwm *controller, uint64_t nowUS)
{
    if (!configurationLock)
        return;
    const uint64_t address = __atomic_load_n(&requestedMac, __ATOMIC_RELAXED);
    uint8_t source[6];
    memcpy(source, &address, sizeof(source));

    size_t length = 0;
    MtkAwdl::ServiceSummary services;
    apple80211_awdl_sync_enabled request = {};
    IOLockLock(configurationLock);
    configuration.readSyncEnabled(&request);
    const bool useMI = masterIndicationLength && nextIsMI;
    const auto state = windowState(nowUS);
    const bool inWindow = state == WindowState::Eligible;
    if (useMI && state == WindowState::Waiting) {
        if (++windowDeferred <= 4 || !(windowDeferred % 16))
            setProperty("MtkAwdlWindowDeferred", windowDeferred, 32);
        IOLockUnlock(configurationLock);
        return;
    }
    const auto *nativeTemplate = useMI ? masterIndication : configuration.frameTemplate();
    const size_t nativeLength = useMI ? masterIndicationLength : configuration.frameTemplateLength();
    const bool ready = request.enabled && nativeLength;
    const bool built = ready && MtkAwdl::buildAnnouncement(source, activeChannel, announcementSequence, nowUS,
        nativeTemplate, nativeLength, announcementTLVs,
        sizeof(announcementTLVs), announcementFrame, sizeof(announcementFrame), &length, &services, useMI);
    IOLockUnlock(configurationLock);
    if (built && useMI && inWindow && !peerSchedule.inPresentAwStart(clockUS(), 4500)) {
        if (++lateWindowBuilds <= 4 || !(lateWindowBuilds % 8))
            setProperty("MtkAwdlWindowHostLate", lateWindowBuilds, 32);
        return;
    }
    nextAnnouncement = nowUS + 112640;
    if (!ready)
        return;

    const bool advertisesService = services.advertisesService();
    const bool verified = useMI && inWindow && services.airDropPtrs;
    const auto kind = verified ? MtkAwdl::TxKind::VerifiedService :
        advertisesService ? MtkAwdl::TxKind::Service : MtkAwdl::TxKind::Sync;
    const IOReturn result = built ? controller->transmitAwdlAnnouncement(
        announcementFrame, length, kind, activeChannel) : kIOReturnBadArgument;
    const uint32_t attempt = ++announcementAttempts;
    if (result == kIOReturnSuccess) {
        ++announcementsQueued;
        serviceAnnouncementsQueued += advertisesService;
        serviceRecordsQueued += services.records;
        nextIsMI = !nextIsMI;
        ++announcementSequence;
        if (verified)
            setProperty("MtkAwdlWindowAirDropPTRQueued", ++verifiedAnnouncementsQueued, 32);
        else if (useMI && services.airDropPtrs &&
                 (++untimedServiceQueued <= 4 || !(untimedServiceQueued % 8)))
            setProperty("MtkAwdlWindowUntimedPTRQueued", untimedServiceQueued, 32);
    }
    if (attempt <= 4 || !(attempt % 8) ||
        (result == kIOReturnSuccess && advertisesService && serviceAnnouncementsQueued == 1)) {
        setProperty("MtkAwdlTxAttempts", attempt, 32);
        setProperty("MtkAwdlTxQueued", announcementsQueued, 32);
        setProperty("MtkAwdlTxServiceQueued", serviceAnnouncementsQueued, 32);
        setProperty("MtkAwdlTxServiceRecordsQueued", serviceRecordsQueued, 32);
        setProperty("MtkAwdlTxLastResult", static_cast<UInt32>(result), 32);
    }
    if (attempt <= 4 || !(attempt & (attempt - 1)))
        IOLog("MTK AWDL: announcement channel=%u attempts=%u queued=%u serviceFrames=%u serviceTLVs=%u result=0x%x\n",
              activeChannel, attempt, announcementsQueued, serviceAnnouncementsQueued, serviceRecordsQueued,
              static_cast<UInt32>(result));
}

void MtkAWDLInterface::publishCompletions(AirportItlwm *controller)
{
    MtkAwdl::AnnouncementCompletions counts;
    if (!controller->readAwdlAnnouncementCompletions(counts) ||
        (counts.sent == lastCompletions.sent && counts.failed == lastCompletions.failed &&
         counts.dataSent == lastCompletions.dataSent && counts.dataFailed == lastCompletions.dataFailed))
        return;
    setProperty("MtkAwdlTxFirmwareSent", counts.sent, 32);
    setProperty("MtkAwdlTxFirmwareFailed", counts.failed, 32);
    setProperty("MtkAwdlTxFirmwareServiceSent", counts.serviceSent, 32);
    setProperty("MtkAwdlTxFirmwareServiceFailed", counts.serviceFailed, 32);
    setProperty("MtkAwdlTxFirmwareLastStatus", counts.lastStatus, 32);
    setProperty("MtkAwdlWindowAirDropPTRFirmwareSent", counts.verifiedServiceSent - peerFirmwareBaseline, 32);
    setProperty("MtkAwdlWindowCompletionLastUS", counts.verifiedCompletionLastUS, 32);
    setProperty("MtkAwdlWindowCompletionMaxUS", counts.verifiedCompletionMaxUS, 32);
    setProperty("MtkAwdlIPv6FirmwareSent", counts.dataSent, 32);
    setProperty("MtkAwdlIPv6UnicastFirmwareSent", counts.unicastReportedSent, 32);
    setProperty("MtkAwdlIPv6FirmwareFailed", counts.dataFailed, 32);
    if (!lastCompletions.serviceSent && counts.serviceSent)
        IOLog("MTK AWDL: firmware reported first service announcement sent\n");
    lastCompletions = counts;
}

void MtkAWDLInterface::syncHardwareMac(AirportItlwm *controller)
{
    if (!controller || !nativeStarted || !activeChannel || !workLoop || !workLoop->inGate())
        return;
    const uint64_t want = __atomic_load_n(&requestedMac, __ATOMIC_RELAXED);
    if (!want || (hardwareMacActive && appliedHardwareMac == want))
        return;
    uint8_t mac[6];
    memcpy(mac, &want, sizeof(mac));
    const IOReturn result = controller->setAwdlMacAddress(mac, true);
    setProperty("MtkAwdlDevUpdateResult", static_cast<UInt32>(result), 32);
    if (result == kIOReturnSuccess) {
        appliedHardwareMac = want;
        hardwareMacActive = true;
    } else {
        hardwareMacActive = false;
    }
    setProperty("MtkAwdlDevActive", hardwareMacActive);
}

void MtkAWDLInterface::syncIPv6State(AirportItlwm *controller)
{
    if (!controller || !nativeStarted || !configurationLock || !workLoop || !workLoop->inGate())
        return;
    apple80211_awdl_sync_enabled request = {};
    IOLockLock(configurationLock);
    configuration.readSyncEnabled(&request);
    IOLockUnlock(configurationLock);
    const bool want = activeChannel != 0 && request.enabled != 0;
    if (want && !ipv6Enabled) {
        if (!dataFrames)
            dataFrames = static_cast<DataFrame *>(IOMalloc(sizeof(DataFrame) * dataCapacity));
        if (!dataFrames)
            return;
        for (auto *q : queues)
            if (q)
                q->enable();
        ipv6Enabled = true;
        nextNdpSyncUS = 0;
        setProperty("MtkAwdlIPv6Enabled", true);
        setProperty("MtkAwdlAutoIPv6", true);
        setProperty("MtkAwdlQueuesEnabled", true);
        setRunningState(true);
        IOLog("MTK AWDL: enabled Skywalk queues and IPv6 data plane on channel=%u\n", activeChannel);
    } else if (!want && ipv6Enabled) {
        ipv6Enabled = false;
        dataRejected += dataQueued;
        dataQueued = 0;
        drainDataCompletions();
        for (auto *q : queues)
            if (q)
                q->disable();
        setRunningState(false);
        setProperty("MtkAwdlIPv6Enabled", false);
        setProperty("MtkAwdlQueuesEnabled", false);
    }
}

IOReturn MtkAWDLInterface::enableIPv6(AirportItlwm *controller)
{
    if (!nativeStarted || !workLoop || !workLoop->inGate() || isInactive())
        return kIOReturnNotReady;
    refreshChannel(controller);
    if (!activeChannel)
        return kIOReturnNotReady;
    syncHardwareMac(controller);
    if (ipv6Enabled)
        return kIOReturnSuccess;
    if (!dataFrames)
        dataFrames = static_cast<DataFrame *>(IOMalloc(sizeof(DataFrame) * dataCapacity));
    if (!dataFrames)
        return kIOReturnNoMemory;

    for (auto *q : queues)
        if (q)
            q->enable();
    ipv6Enabled = true;
    setProperty("MtkAwdlIPv6Enabled", true);
    setProperty("MtkAwdlQueuesEnabled", true);
    setRunningState(true);
    nextNdpSyncUS = 0;
    syncNeighbors(clockUS());
    return kIOReturnSuccess;
}

void MtkAWDLInterface::syncNeighbors(uint64_t nowUS)
{
    if (!nativeStarted || (!ipv6Enabled && nextNdpSyncUS == UINT64_MAX))
        return;
    if (ipv6Enabled && nowUS < nextNdpSyncUS)
        return;
    nextNdpSyncUS = ipv6Enabled ? (nowUS + 1000000ULL) : UINT64_MAX;

    uint8_t macs[MtkAwdlNdp::kMaxPeers][6] = {};
    size_t count = 0;
    constexpr uint8_t zero[6] = {};

    if (ipv6Enabled) {
        if (memcmp(timingPeer, zero, sizeof(timingPeer)) != 0 && count < MtkAwdlNdp::kMaxPeers) {
            memcpy(macs[count++], timingPeer, 6);
        }
        for (const auto &entry : observedPeers) {
            if (!entry.frames || (nowUS - entry.lastFrameUS) >= ItlAWDL::kPeerScheduleStaleUS)
                continue;
            bool dup = false;
            for (size_t i = 0; i < count; ++i) {
                if (memcmp(macs[i], entry.address, 6) == 0) {
                    dup = true;
                    break;
                }
            }
            if (!dup && count < MtkAwdlNdp::kMaxPeers)
                memcpy(macs[count++], entry.address, 6);
        }
    }

    neighbors.updateDesiredState(ipv6Enabled && activeChannel != 0, nowUS * 1000ULL, macs, count);
    const auto st = neighbors.snapshotStats();
    setProperty("MtkAwdlNdpEnabled", st.enabled);
    setProperty("MtkAwdlNdpRouteOwned", st.routeOwned);
    setProperty("MtkAwdlNdpNeighbors", st.activeNeighbors, 32);
    setProperty("MtkAwdlNdpRouteAdds", st.routeAdds, 32);
    setProperty("MtkAwdlNdpNeighborAdds", st.neighborAdds, 32);
    setProperty("MtkAwdlNdpErrors", st.errors, 32);
}

UInt32 MtkAWDLInterface::acceptTransmit(OSObject *owner, IOSkywalkTxSubmissionQueue *,
                                      IOSkywalkPacket *const *packets, UInt32 count, void *)
{
    auto *self = static_cast<MtkAWDLInterface *>(owner);
    if (!self->workLoop || !self->workLoop->inGate() || !self->ipv6Enabled || !packets)
        return 0;
    unsigned accepted = 0;
    for (; accepted < count && self->dataDoneCount < dataCapacity; ++accepted) {
        if (!packets[accepted])
            break;
        auto *packet = reinterpret_cast<ItlSkywalkPacketView *>(packets[accepted]);
        const auto length = packet->getDataLength();
        const auto offset = itlPacketGetDataOffset(packet);
        const auto *base = reinterpret_cast<const uint8_t *>(packet->getDataVirtualAddress());
        const bool valid = packet->getPacketBufferCount() == 1 && base && offset < 2048 &&
            length <= 2048U - offset && length >= 54 && length <= MtkAwdl::ethernetMax;
        if (valid && self->dataQueued < dataCapacity) {
            auto &slot = self->dataFrames[(self->dataHead + self->dataQueued) % dataCapacity];
            slot.length = uint16_t(length);
            memcpy(slot.bytes, base + offset, length);
            ++self->dataQueued;
        } else {
            ++self->dataRejected;
        }
        self->dataDone[self->dataDoneCount++] = packets[accepted];
    }
    self->dataOffered += accepted;
    if (self->dataOffered <= 4 || (self->dataOffered / 8 != (self->dataOffered - accepted) / 8))
        self->setProperty("MtkAwdlIPv6SkywalkAccepted", self->dataOffered, 32);
    return accepted;
}

void MtkAWDLInterface::drainDataCompletions()
{
    if (!dataDoneCount)
        return;
    const auto result = itlTxComplete(queues[1], reinterpret_cast<void *const *>(dataDone),
                                      dataDoneCount, 0);
    if (result == kIOReturnSuccess)
        dataDoneCount = 0;
    else
        setProperty("MtkAwdlIPv6SkywalkCompletionError", uint32_t(result), 32);
}

void MtkAWDLInterface::serviceData(AirportItlwm *controller, uint64_t now)
{
    if (!activeChannel || !dataQueued)
        return;

    // Defer briefly only when we have reliable timing showing the peer is off-channel
    // and the queue still has plenty of headroom. Never drop queued handshake packets.
    if (windowEvidence.reliable() && peerSchedule.timingUsable(now, false) &&
        peerSchedule.shouldPause(now) && dataQueued < dataCapacity / 2)
        return;
    const uint64_t address = __atomic_load_n(&requestedMac, __ATOMIC_RELAXED);
    constexpr uint8_t zero[6] = {};
    const unsigned budget = 12;
    unsigned processed = 0;
    while (dataQueued && processed++ < budget) {
        const auto &slot = dataFrames[dataHead];
        const auto *ethernet = slot.bytes;
        const bool group = ethernet[0] & 1;
        size_t length = 0;
        const bool valid = slot.length >= 54 && !memcmp(ethernet + 6, &address, 6) &&
            (group ? ethernet[0] == 0x33 && ethernet[1] == 0x33 :
                memcmp(ethernet, zero, sizeof(zero)) != 0) &&
            MtkAwdl::buildData(ethernet, slot.length, announcementSequence,
                announcementFrame, sizeof(announcementFrame), length);
        const auto result = valid ? controller->transmitAwdlAnnouncement(
            announcementFrame, length, group ? MtkAwdl::TxKind::GroupData : MtkAwdl::TxKind::Data, activeChannel)
            : kIOReturnBadArgument;
        if (result == kIOReturnBusy || result == kIOReturnNotReady)
            break;
        if (result == kIOReturnSuccess) {
            ++announcementSequence;
            ++dataTxQueued;
            dataAckQueued += !group;
            if (dataTxQueued <= 8 || !(dataTxQueued % 8)) {
                setProperty("MtkAwdlIPv6RadioQueued", dataTxQueued, 32);
                setProperty("MtkAwdlIPv6UnicastQueued", dataAckQueued, 32);
            }
        } else {
            ++dataRejected;
            setProperty("MtkAwdlIPv6TxRejected", dataRejected, 32);
        }
        dataHead = (dataHead + 1) % dataCapacity;
        --dataQueued;
    }
}

void MtkAWDLInterface::observeData(mbuf_t mbuf, uint32_t channel)
{
    if (!mbuf)
        return;
    const size_t length = mbuf_pkthdr_len(mbuf);
    if (length < 76 || length > 1600)
        return;
    uint8_t linear[1600];
    const uint8_t *frame = nullptr;
    if (!mbuf_next(mbuf) && mbuf_len(mbuf) == length) {
        frame = static_cast<const uint8_t *>(mbuf_data(mbuf));
    } else if (mbuf_copydata(mbuf, 0, length, linear) == 0) {
        frame = linear;
    }
    if (!frame)
        return;
    const uint64_t address = __atomic_load_n(&requestedMac, __ATOMIC_RELAXED);
    if (!memcmp(frame + 10, &address, 6))
        return;

    const auto seen = ++dataRxSeen;
    if (frame[4] & 1)
        ++dataRxMulticast;
    else
        ++dataRxUnicast;
    if (seen <= 8 || !(seen % 16)) {
        setProperty("MtkAwdlIPv6RadioRx", seen, 32);
        setProperty("MtkAwdlRxDataUnicast", dataRxUnicast, 32);
        setProperty("MtkAwdlRxDataMulticast", dataRxMulticast, 32);
    }
    if (!ipv6Enabled || !activeChannel || channel != activeChannel)
        return;

    const bool fcs = MtkAwdl::hasFcs(frame, length);
    ItlAWDL::DataFrameView view;
    if (ItlAWDL::parseDataFrame(frame, length, fcs, &view) != ItlAWDL::ParseResult::Valid ||
        !MtkAwdl::localTraffic(view.ip.bytes, view.ip.length)) {
        if (++dataRxParseFail <= 8 || !(dataRxParseFail % 16))
            setProperty("MtkAwdlRxDataParseFail", dataRxParseFail, 32);
        return;
    }
    const auto *destination = view.destination;
    if (destination[0] & 1) {
        if (destination[0] != 0x33 || destination[1] != 0x33 || view.ip.bytes[24] != 0xff ||
            memcmp(destination + 2, view.ip.bytes + 36, 4))
            return;
    } else if (memcmp(destination, &address, 6)) {
        return;
    }

    auto *pool = reinterpret_cast<ItlSkywalkPoolView *>(rxPool);
    ItlSkywalkPacketView *packet = nullptr;
    IOReturn result = pool->allocatePacket(1, &packet, 1);
    if (result != kIOReturnSuccess || !packet) {
        setProperty("MtkAwdlIPv6RxError", uint32_t(result), 32);
        setProperty("MtkAwdlRxErrorStage", "alloc");
        return;
    }

    const char *errorStage = "prep";
    result = packet->prepareWithQueue(queues[2], 0, 0);
    const bool prepared = result == kIOReturnSuccess;
    if (prepared) {
        errorStage = "meta";
        const unsigned wanted = 14 + unsigned(view.ip.length);
        result = itlPacketSetHeadroom(packet, 0);
        if (result == kIOReturnSuccess)
            result = itlPacketSetLinkHeaderLength(packet, 14);
        if (result == kIOReturnSuccess)
            result = packet->setDataLength(wanted);
        if (result == kIOReturnSuccess) {
            auto *out = reinterpret_cast<uint8_t *>(packet->getDataVirtualAddress());
            const unsigned offset = itlPacketGetDataOffset(packet);
            size_t written = 0;
            if (!out || packet->getPacketBufferCount() != 1 || packet->getDataLength() != wanted ||
                offset > 2048 - wanted || ItlAWDL::copyDataEthernet(view, out + offset,
                2048 - offset, &written) != ItlAWDL::BuildResult::Ready || written != wanted)
                result = kIOReturnBadArgument;
        }
        if (result == kIOReturnSuccess) {
            errorStage = "enq";
            result = itlRxEnqueue(queues[3], &packet, 1, 0);
        }
        if (result == kIOReturnSuccess) {
            ++dataRxDelivered;
            if (dataRxDelivered == 1)
                IOLog("MTK AWDL: first IPv6 packet delivered to awdl0 (%u bytes)\n", wanted);
            if (dataRxDelivered <= 8 || !(dataRxDelivered % 8))
                setProperty("MtkAwdlIPv6SkywalkDelivered", dataRxDelivered, 32);
            return;
        }
        packet->setDataLength(0);
        packet->completeWithQueue(queues[2], 0, 0);
    }
    pool->deallocatePacket(packet);
    setProperty("MtkAwdlIPv6RxError", uint32_t(result), 32);
    setProperty("MtkAwdlRxErrorStage", errorStage);
}

UInt32 MtkAWDLInterface::deferReceive(OSObject *, IOSkywalkRxSubmissionQueue *,
                                    IOSkywalkPacket *const *, UInt32, void *)
{
    return 0;
}

void MtkAWDLInterface::releaseNetwork()
{
    if (announcementTimer) {
        announcementTimer->disable();
        announcementTimer->cancelTimeout();
        workLoop->removeEventSource(announcementTimer);
        OSSafeReleaseNULL(announcementTimer);
    }
    neighbors.destroy();
    if (workLoop && hardwareMacActive) {
        workLoop->runAction([](OSObject *owner, void *, void *, void *, void *) -> IOReturn {
            auto *self = static_cast<MtkAWDLInterface *>(owner);
            if (auto *controller = OSDynamicCast(AirportItlwm, self->getProvider()))
                controller->setAwdlMacAddress(nullptr, false);
            self->hardwareMacActive = false;
            self->appliedHardwareMac = 0;
            return kIOReturnSuccess;
        }, this);
    }
    if (workLoop && dataFrames) {
        workLoop->runAction([](OSObject *owner, void *, void *, void *, void *) -> IOReturn {
            auto *self = static_cast<MtkAWDLInterface *>(owner);
            self->ipv6Enabled = false;
            self->queues[0]->disable();
            self->drainDataCompletions();
            if (self->dataDoneCount)
                self->setProperty("MtkAwdlIPv6SkywalkPendingAtStop", self->dataDoneCount, 32);
            return kIOReturnSuccess;
        }, this);
        IOFree(dataFrames, sizeof(DataFrame) * dataCapacity);
        dataFrames = nullptr;
    }
    if (registrationAttempted) {
        registrationAttempted = false;
        deregisterEthernetInterface(0);
    }
    while (queuesAdded) {
        auto *queue = queues[--queuesAdded];
        queue->disable();
        workLoop->removeEventSource(queue);
    }
    for (auto &queue : queues)
        OSSafeReleaseNULL(queue);
    OSSafeReleaseNULL(txPool);
    OSSafeReleaseNULL(rxPool);
    OSSafeReleaseNULL(workLoop);
}

void MtkAWDLInterface::stop(IOService *provider)
{
    const bool started = nativeStarted;
    nativeStarted = false;
    releaseNetwork();
    if (started)
        IO80211AWDLProtocol::stop(provider);
}

void MtkAWDLInterface::free()
{
    if (nativeStarted)
        stop(getProvider());
    else
        releaseNetwork();
    if (configurationLock) {
        IOLockFree(configurationLock);
        configurationLock = nullptr;
    }
    IO80211AWDLProtocol::free();
}

IOReturn MtkAWDLInterface::initializeNetwork(IO80211Controller *controller,
                                            IOWorkLoop *sharedWorkLoop,
                                            const ether_addr &address)
{
    if (!controller || !sharedWorkLoop || nativeStarted)
        return kIOReturnBadArgument;

    auto stage = [this, controller](const char *name) {
        setProperty("MtkAwdlStage", name);
        controller->setProperty("MtkAwdlStage", name);
        IOLog("MTK AWDL: %s\n", name);
    };
    auto fail = [this, controller](IOReturn error) {
        stop(controller);
        return error;
    };

    uint64_t initialMac = 0;
    memcpy(&initialMac, &address, sizeof(address));
    uint64_t unsetMac = 0;
    __atomic_compare_exchange_n(&requestedMac, &unsetMac, initialMac, false,
        __ATOMIC_RELAXED, __ATOMIC_RELAXED);

    if (testPeer.hostname[0])
        setProperty("MtkAwdlPeerNameMatched", false);
    else
        publishTimingPeer();
    setProperty("MtkAwdlNativePeerMatched", false);
    setProperty("MtkAwdlTargetFrames", UInt64(0), 32);
    setProperty("MtkAwdlTargetSchedules", UInt64(0), 32);
    setProperty("MtkAwdlMIServiceRecordStatus", "waiting for native template");
    setProperty("MtkAwdlInfraChannel", UInt64(0), 32);
    setProperty("MtkAwdlActiveChannel", UInt64(0), 32);
    setProperty("MtkAwdlRadioSyncActive", false);
    setProperty("MtkAwdlSyncEnableCalls", UInt64(0), 32);
    setProperty("MtkAwdlMIRequests", UInt64(0), 32);
    setProperty("MtkAwdlMIAccepted", UInt64(0), 32);
    setProperty("MtkAwdlMIServicesReceived", UInt64(0), 64);
    setProperty("MtkAwdlTxFirmwareSent", UInt64(0), 32);
    setProperty("MtkAwdlTxFirmwareFailed", UInt64(0), 32);
    setProperty("MtkAwdlTxFirmwareServiceSent", UInt64(0), 32);
    setProperty("MtkAwdlTxFirmwareServiceFailed", UInt64(0), 32);
    setProperty("MtkAwdlWindowAirDropPTRFirmwareSent", UInt64(0), 32);
    stage("starting");
    if (!IO80211AWDLProtocol::start(controller))
        return kIOReturnError;
    nativeStarted = true;
    peerSchedule.assumeZero = true;
    workLoop = sharedWorkLoop;
    workLoop->retain();

    stage("allocating-pools");
    const IOSkywalkPacketBufferPool::PoolOptions options = {256, 256, 2048, 1, 4096, 0, 0};
    txPool = IOSkywalkPacketBufferPool::withName("mtk-awdl-tx", this, 0, &options);
    rxPool = IOSkywalkPacketBufferPool::withName("mtk-awdl-rx", this, 0, &options);
    if (!txPool || !rxPool)
        return fail(kIOReturnNoMemory);

    stage("allocating-queues");
    queues[0] = itlMakeTxSubmission(txPool, 128, 0, this, acceptTransmit, nullptr, 0);
    queues[1] = itlMakeTxCompletion(txPool, 128, 0, this, nullptr, nullptr, 0);
    queues[2] = itlMakeRxSubmission(rxPool, 128, 1, 0, this, deferReceive, nullptr, 0);
    queues[3] = itlMakeRxCompletion(rxPool, 128, 0, this, nullptr, nullptr, 0);
    for (auto *queue : queues) {
        if (!queue)
            return fail(kIOReturnNoMemory);
    }
    stage("adding-queues");
    for (auto *queue : queues) {
        const IOReturn result = workLoop->addEventSource(queue);
        if (result != kIOReturnSuccess)
            return fail(result);
        ++queuesAdded;
    }

    RegistrationInfo info = {};
    if (!initRegistrationInfo(&info, 1, sizeof(info)))
        return fail(kIOReturnBadArgument);
    // Native Tahoe AWDL Skywalk registration layout, as used by ForbiddenItlwm.
    auto put32 = [&info](size_t offset, UInt32 value) {
        memcpy(info.bytes + offset, &value, sizeof(value));
    };
    put32(0x0c, 3);
    put32(0x14, 2);
    put32(0x24, 0x80);
    put32(0x28, 0x80);
    const char *prefix = "awdl";
    memcpy(info.bytes + 0x30, &prefix, sizeof(prefix));
    put32(0x38, 0);
    const UInt16 headroom = 0x40;
    memcpy(info.bytes + 0x3c, &headroom, sizeof(headroom));
    put32(0x40, 4);
    put32(0x48, 1428);
    put32(0x4c, 1428);
    const uint64_t registeredMac = __atomic_load_n(&requestedMac, __ATOMIC_RELAXED);
    memcpy(info.bytes + 0x108, &registeredMac, sizeof(address));

    IOSkywalkPacketQueue *networkQueues[4];
    for (unsigned i = 0; i < 4; ++i)
        networkQueues[i] = reinterpret_cast<IOSkywalkPacketQueue *>(queues[i]);
    stage("registering");
    registrationAttempted = true;
    const IOReturn result = registerEthernetInterface(&info, networkQueues, 4, txPool, rxPool, 0);
    if (result != kIOReturnSuccess)
        return fail(result);

    if (auto *airport = OSDynamicCast(AirportItlwm, controller)) {
        airport->readAwdlAnnouncementCompletions(lastCompletions);
        peerFirmwareBaseline = lastCompletions.verifiedServiceSent;
    }
    setRunningState(false);
    announcementTimer = IOTimerEventSource::timerEventSource(this, announcementTimerFired);
    if (announcementTimer && workLoop->addEventSource(announcementTimer) == kIOReturnSuccess) {
        announcementTimer->setTimeoutMS(113);
        setProperty("MtkAwdlTxTimer", true);
    } else {
        OSSafeReleaseNULL(announcementTimer);
        setProperty("MtkAwdlTxTimer", false);
    }
    stage("registered");
    registerService();
    return kIOReturnSuccess;
}
#endif
