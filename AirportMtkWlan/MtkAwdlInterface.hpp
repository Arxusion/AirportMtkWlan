// Tahoe AWDL interface for registration and host-side configuration.
#pragma once
#if defined(MTK_NATIVE_AWDL) && defined(AIRPORT_WCL) && __IO80211_TARGET == __MAC_26_0
#include <Airport/macOS26/IO80211AWDLProtocol.h>
#include <Airport/macOS26/IOSkywalkQueueFactories.h>
#include "MtkAwdlConfiguration.hpp"
#include "MtkAwdlNeighbors.hpp"
#include <HAL/MtkAwdlAnnouncement.hpp>
#include <HAL/MtkAwdlPeerIdentity.hpp>
#include <HAL/MtkAwdlData.hpp>
#include <HAL/Awdl/AWDLPeerSchedule.hpp>
#include <IOKit/IOTimerEventSource.h>

struct ieee80211com;
class AirportItlwm;

class MtkAWDLInterface final : public IO80211AWDLProtocol {
    OSDeclareDefaultStructors(MtkAWDLInterface)
public:
    bool prepareConfiguration(const ieee80211com &, const MtkAwdl::PeerIdentity &);
    IOReturn initializeNetwork(IO80211Controller *, IOWorkLoop *, const ether_addr &);
    void observeAction(IO80211Controller *, mbuf_t, uint32_t channel, int32_t rssi);
    IOReturn enableIPv6(AirportItlwm *);
    void observeData(mbuf_t, uint32_t);
    void stop(IOService *) override;
    void free() override;
    IOReturn setMacAddress(ether_addr &) override;

#define MTK_AWDL_DIAGNOSTIC(method, type) \
    IOReturn method(type *) override { return record(#method); }
    IOReturn getSSID(apple80211_ssid_data *) override;
    IOReturn getCHANNEL(apple80211_channel_data *) override;
    IOReturn getBSSID(apple80211_bssid_data *) override;
    IOReturn getSTATE(apple80211_state_data *) override;
    IOReturn getAWDL_SYNC_PARAMS(apple80211_awdl_sync_params *) override;
    IOReturn getAWDL_SYNC_ENABLED(apple80211_awdl_sync_enabled *) override;
    MTK_AWDL_DIAGNOSTIC(getAWDL_EXTENSION_STATE_MACHINE_PARAMETERS, apple80211_awdl_extension_state_machine_parameter)
    IOReturn getAWDL_ELECTION_ID(apple80211_awdl_election_id *) override;
    IOReturn getAWDL_ELECTION_METRIC(apple80211_awdl_election_metric *) override;
    IOReturn getAWDL_SYNCHRONIZATION_CHANNEL_SEQUENCE(apple80211_awdl_sync_channel_sequence *) override;
    IOReturn getPEER_CACHE_MAXIMUM_SIZE(apple80211_peer_cache_maximum_size *) override;
    IOReturn getAWDL_MASTER_CHANNEL(apple80211_awdl_master_channel *) override;
    IOReturn getAWDL_SYNC_STATE(apple80211_awdl_sync_state *) override;
    IOReturn getAWDL_ELECTION_RSSI_THRESHOLDS(apple80211_awdl_election_rssi_thresholds *) override;
    MTK_AWDL_DIAGNOSTIC(getAWDL_PRESENCE_MODE, apple80211_awdl_presence_mode)
    MTK_AWDL_DIAGNOSTIC(getAWDL_ELECTION_PARAMS, apple80211_awdl_election_params)
    MTK_AWDL_DIAGNOSTIC(getAWDL_DEVICE_CAPABILITIES, apple80211_awdl_device_capabilities)
    IOReturn getAWDL_SECONDARY_MASTER_CHANNEL(apple80211_awdl_secondary_master_channel *) override;
    MTK_AWDL_DIAGNOSTIC(getAWDL_AF_TX_MODE, apple80211_awdl_af_tx_mode)
    IOReturn getAWDL_MIN_RATE(apple80211_awdl_min_rate *) override;
    MTK_AWDL_DIAGNOSTIC(getAWDL_ENCRYPTION_TYPE, apple80211_encrypt)
    MTK_AWDL_DIAGNOSTIC(getAWDL_TXCAL_PERIOD, apple80211_awdl_txcal_period)
    MTK_AWDL_DIAGNOSTIC(getAWDL_DEV_STATS, apple80211_awdl_dev_stats)
    MTK_AWDL_DIAGNOSTIC(getAWDL_DFSP_CONFIG, apple80211_awdl_dfsp_config)
    MTK_AWDL_DIAGNOSTIC(getAWDL_CCA, apple80211_awdl_cca)
    MTK_AWDL_DIAGNOSTIC(getAWDL_AF_SECONDARY_PAYLOAD_CAPABILITIES, apple80211_awdl_cap)
    MTK_AWDL_DIAGNOSTIC(getLLW_PARAMS, apple80211_llw_params)
    MTK_AWDL_DIAGNOSTIC(setSSID, apple80211_ssid_data)
    MTK_AWDL_DIAGNOSTIC(setCHANNEL, apple80211_channel_data)
    IOReturn setAWDL_SYNC_PARAMS(apple80211_awdl_sync_params *) override;
    IOReturn setAWDL_SYNC_ENABLED(apple80211_awdl_sync_enabled *) override;
    MTK_AWDL_DIAGNOSTIC(setAWDL_EXTENSION_STATE_MACHINE_PARAMETERS, apple80211_awdl_extension_state_machine_parameter)
    IOReturn setAWDL_ELECTION_ID(apple80211_awdl_election_id *) override;
    IOReturn setAWDL_BSSID(apple80211_awdl_bssid *) override;
    IOReturn setAWDL_ELECTION_METRIC(apple80211_awdl_election_metric *) override;
    IOReturn setAWDL_SYNCHRONIZATION_CHANNEL_SEQUENCE(apple80211_awdl_sync_channel_sequence *) override;
    IOReturn setAWDL_MASTER_CHANNEL(apple80211_awdl_master_channel *) override;
    IOReturn setAWDL_SYNC_STATE(apple80211_awdl_sync_state *) override;
    IOReturn setAWDL_ELECTION_RSSI_THRESHOLDS(apple80211_awdl_election_rssi_thresholds *) override;
    MTK_AWDL_DIAGNOSTIC(setAWDL_PRESENCE_MODE, apple80211_awdl_presence_mode)
    MTK_AWDL_DIAGNOSTIC(setPEER_CACHE_CONTROL, apple80211_peer_cache_control)
    MTK_AWDL_DIAGNOSTIC(setAWDL_OOB_REQUEST, apple80211_awdl_oob_request)
    IOReturn setAWDL_SYNC_FRAME_TEMPLATE(apple80211_awdl_sync_frame_template *) override;
    MTK_AWDL_DIAGNOSTIC(setAWDL_ELECTION_PARAMS, apple80211_awdl_election_params)
    MTK_AWDL_DIAGNOSTIC(setAWDL_PEER_TRAFFIC_REGISTRATION, apple80211_awdl_peer_traffic_registration)
    IOReturn setAWDL_SECONDARY_MASTER_CHANNEL(apple80211_awdl_secondary_master_channel *) override;
    MTK_AWDL_DIAGNOSTIC(setAWDL_AF_TX_MODE, apple80211_awdl_af_tx_mode)
    IOReturn setAWDL_MIN_RATE(apple80211_awdl_min_rate *) override;
    MTK_AWDL_DIAGNOSTIC(setAWDL_ENCRYPTION_KEYS, apple80211_key)
    MTK_AWDL_DIAGNOSTIC(setAWDL_ENCRYPTION_TYPE, apple80211_encrypt)
    IOReturn setAWDL_OOB_AUTO_REQUEST(apple80211_awdl_oob_request *) override;
    MTK_AWDL_DIAGNOSTIC(setAWDL_TXCAL_PERIOD, apple80211_awdl_txcal_period)
    MTK_AWDL_DIAGNOSTIC(setAWDL_AWDL_ADVERTISERS, awdl_peer_advert_add)
    MTK_AWDL_DIAGNOSTIC(setAWDL_DFSP_CONFIG, apple80211_awdl_dfsp_config)
    MTK_AWDL_DIAGNOSTIC(setAWDL_DFSP_UCSA_CONFIG, apple80211_awdl_dfsp_ucsa_config)
    MTK_AWDL_DIAGNOSTIC(setCOMPANION_SKYWALK_IF_CREATE, apple80211_companion_skywalk_if_create)
    MTK_AWDL_DIAGNOSTIC(setAWDL_OOB_SEC_PAYLOAD_REQUEST, apple80211_awdl_af_sec_payload_request)
    MTK_AWDL_DIAGNOSTIC(setLLW_PARAMS, apple80211_llw_params)
    MTK_AWDL_DIAGNOSTIC(setTX_RATE, apple80211_tx_rate)
    MTK_AWDL_DIAGNOSTIC(setP2P_COEX_PROTECTION, apple80211_p2p_coex_protection)
    MTK_AWDL_DIAGNOSTIC(setPSF_DWELL, apple80211_awdl_psf_dwell_params)
    MTK_AWDL_DIAGNOSTIC(setAWDL_CONFIG, apple80211_awdl_config_request)
    MTK_AWDL_DIAGNOSTIC(setAWDL_RTG_PEER_STATS_CONFIG, apple80211_rtg_peer_stats_cfg)
#undef MTK_AWDL_DIAGNOSTIC

private:
    IOReturn record(const char *, IOReturn result = kIOReturnUnsupported);
    template <typename Action>
    IOReturn configure(const char *operation, Action action)
    {
        if (!configurationLock)
            return record(operation, kIOReturnNotReady);
        IOLockLock(configurationLock);
        const IOReturn result = record(operation, action());
        IOLockUnlock(configurationLock);
        return result;
    }

    IOReturn submitAction(IO80211Controller *, mbuf_t, uint32_t channel, int32_t rssi);
    static void announcementTimerFired(OSObject *, IOTimerEventSource *);
    void sendAnnouncement(AirportItlwm *, uint64_t now);
    void refreshChannel(AirportItlwm *);
    uint8_t infraChannel = 0;
    uint8_t activeChannel = 0;
    void observePeerTiming(const uint8_t *, size_t, uint32_t, uint64_t rxUS);
    void syncHardwareMac(AirportItlwm *);
    void syncIPv6State(AirportItlwm *);
    void syncNeighbors(uint64_t nowUS);
    void serviceData(AirportItlwm *, uint64_t now);
    void drainDataCompletions();
    static uint64_t clockUS();
    enum { dataCapacity = 128 };
    struct DataFrame { uint16_t length; uint8_t bytes[MtkAwdl::ethernetMax]; };
    DataFrame *dataFrames = nullptr;
    IOSkywalkPacket *dataDone[dataCapacity] = {};
    MtkAwdlNeighborManager neighbors;
    uint64_t nextNdpSyncUS = 0;
    unsigned dataDoneCount = 0;
    unsigned dataHead = 0;
    unsigned dataQueued = 0;
    bool ipv6Enabled = false;
    uint64_t appliedHardwareMac = 0;
    bool hardwareMacActive = false;
    uint32_t dataOffered = 0;
    uint32_t dataRejected = 0;
    uint32_t dataTxQueued = 0;
    uint32_t dataAckQueued = 0;
    uint32_t dataRxSeen = 0;
    uint32_t dataRxUnicast = 0;
    uint32_t dataRxMulticast = 0;
    uint32_t dataRxParseFail = 0;
    uint32_t dataRxDelivered = 0;
    ItlAWDL::PeerSchedule peerSchedule = {};
    struct PeerObservation {
        uint8_t address[6] = {};
        uint32_t channel = 0;
        uint32_t frames = 0;
        uint32_t schedules = 0;
        uint64_t lastFrameUS = 0;
        uint64_t lastScheduleUS = 0;
        ItlAWDL::PeerSyncInfo sync = {};
        MtkAwdl::ArpaName arpa = MtkAwdl::ArpaName::Absent;
    };
    static constexpr unsigned peerObservationLimit = 8;
    PeerObservation observedPeers[peerObservationLimit];
    uint64_t nextPeerReviewUS = 0;
    MtkAwdl::PeerIdentity testPeer;
    uint8_t timingPeer[6] = {};
    PeerObservation &recordPeer(const uint8_t *, size_t, uint32_t, uint64_t, bool &);
    void reviewPeers(uint64_t);
    void publishTimingPeer();
    uint32_t targetFrames = 0;
    uint32_t targetSchedules = 0;
    enum class WindowState { NoSchedule, Stale, NoSlots, OffsetUnknown,
                             Collecting, LowAgreement, Waiting, Eligible };
    ItlAWDL::PeerWindowEvidence windowEvidence;
    uint32_t scheduleEpochs = 0;
    uint32_t scheduleGaps = 0;
    uint32_t phaseReanchors = 0;
    uint32_t windowDeferred = 0;
    uint32_t lateWindowBuilds = 0;
    uint32_t untimedServiceQueued = 0;
    WindowState lastWindowState = WindowState::NoSchedule;
    bool windowStatePublished = false;
    WindowState windowState(uint64_t) const;
    void publishWindowState(uint64_t);
    void noteSchedule(const ItlAWDL::PeerSyncInfo &, uint64_t);
    uint32_t verifiedAnnouncementsQueued = 0;
    uint32_t peerFirmwareBaseline = 0;
    uint64_t nextAnnouncement = 0;
    bool nextIsMI = false;
    void releaseNetwork();
    IOTimerEventSource *announcementTimer = nullptr;
    uint16_t announcementSequence = 0;
    uint32_t announcementAttempts = 0;
    uint32_t announcementsQueued = 0;
    uint32_t serviceAnnouncementsQueued = 0;
    uint32_t serviceRecordsQueued = 0;
    uint32_t masterIndicationRequests = 0;
    uint32_t masterIndicationAccepted = 0;
    uint64_t serviceRecordsReceived = 0;
    uint32_t masterIndicationLength = 0;
    bool masterIndicationHasAirDropPtr = false;
    uint8_t masterIndication[MtkAwdl::masterIndicationMax] = {};
    uint8_t masterIndicationSnapshot[MtkAwdl::masterIndicationMax] = {};
    MtkAwdl::AnnouncementCompletions lastCompletions;
    void publishCompletions(AirportItlwm *);
    uint8_t announcementTLVs[MtkAwdl::announcementTemplateMax + 44] = {};
    uint8_t announcementFrame[2048] = {};
    unsigned rxActionCandidates = 0;
    unsigned rxActionSubmitted = 0;
    unsigned rxActionRejected = 0;
    unsigned rxActionBeforeNativeReady = 0;
    unsigned rxActionWhileSyncOff = 0;
    unsigned configurationChanges = 0;
    unsigned syncEnableCalls = 0;
    IOLock *configurationLock = nullptr;
    MtkAwdlConfiguration configuration;
    static UInt32 acceptTransmit(OSObject *, IOSkywalkTxSubmissionQueue *, IOSkywalkPacket *const *, UInt32, void *);
    static UInt32 deferReceive(OSObject *, IOSkywalkRxSubmissionQueue *, IOSkywalkPacket *const *, UInt32, void *);
    IOWorkLoop *workLoop = nullptr;
    IOSkywalkPacketBufferPool *txPool = nullptr;
    IOSkywalkPacketBufferPool *rxPool = nullptr;
    IOEventSource *queues[4] = {};
    uint64_t requestedMac = 0;
    unsigned queuesAdded = 0;
    bool nativeStarted = false;
    bool registrationAttempted = false;
};

bool mtkAwdlTahoeAbiMatches();
#endif
