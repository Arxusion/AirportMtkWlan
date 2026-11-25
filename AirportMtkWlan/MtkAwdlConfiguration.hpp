// Host-side AWDL requests for Tahoe. The caller serializes all accesses.
#pragma once
#include <IOKit/IOReturn.h>
#include <Airport/apple80211_ioctl.h>

static_assert(sizeof(apple80211_awdl_sync_enabled) == 12 &&
    __builtin_offsetof(apple80211_awdl_sync_enabled, enabled) == 8,
    "Tahoe AWDL sync switch layout");
static_assert(sizeof(apple80211_awdl_sync_frame_template) == 16 &&
    __builtin_offsetof(apple80211_awdl_sync_frame_template, payload) == 8,
    "Tahoe AWDL frame template layout");

template <typename T>
class MtkAwdlRequestedValue {
public:
    IOReturn set(const T *request)
    {
        if (!request || request->version > APPLE80211_VERSION)
            return kIOReturnBadArgument;
        value = *request;
        value.version = APPLE80211_VERSION;
        present = true;
        return kIOReturnSuccess;
    }

    IOReturn read(T *reply) const
    {
        if (!reply)
            return kIOReturnBadArgument;
        if (!present)
            return kIOReturnNotReady;
        *reply = value;
        return kIOReturnSuccess;
    }

private:
    T value = {};
    bool present = false;
};

class MtkAwdlConfiguration {
public:
    void addSupportedChannel(uint32_t channel)
    {
        if (channel && channel < sizeof(supportedChannels))
            supportedChannels[channel] = true;
    }

    IOReturn setMasterChannel(const apple80211_awdl_master_channel *request)
    {
        if (!request || !supportsChannel(request->master_channel))
            return kIOReturnBadArgument;
        return masterChannel.set(request);
    }

    IOReturn readMasterChannel(apple80211_awdl_master_channel *reply) const
    {
        return masterChannel.read(reply);
    }

    IOReturn setSecondaryMasterChannel(const apple80211_awdl_secondary_master_channel *request)
    {
        // Zero represents an unset secondary channel.
        if (!request || (request->secondary_master_channel &&
            !supportsChannel(request->secondary_master_channel)))
            return kIOReturnBadArgument;
        return secondaryMasterChannel.set(request);
    }

    IOReturn readSecondaryMasterChannel(apple80211_awdl_secondary_master_channel *reply) const
    {
        return secondaryMasterChannel.read(reply);
    }

    IOReturn setSyncState(const apple80211_awdl_sync_state *request)
    {
        // The native protocol defines states 1 through 3. Record the host
        // request without starting wireless synchronization.
        if (!request || request->state < 1 || request->state > 3)
            return kIOReturnBadArgument;
        return syncState.set(request);
    }

    IOReturn readSyncState(apple80211_awdl_sync_state *reply) const
    {
        if (!reply)
            return kIOReturnBadArgument;
        if (syncState.read(reply) == kIOReturnNotReady)
            *reply = {APPLE80211_VERSION, 1};
        return kIOReturnSuccess;
    }

    IOReturn setSequence(const apple80211_awdl_sync_channel_sequence *request)
    {
        // Tahoe uses 12-byte entries after the 16-byte header. Keep the whole
        // request opaque so readback preserves the native channel encoding.
        constexpr size_t maxEntries = (sizeof(*request) - 16) / 12;
        if (!request || request->length > maxEntries)
            return kIOReturnBadArgument;
        return sequence.set(request);
    }

    IOReturn readSequence(apple80211_awdl_sync_channel_sequence *reply) const
    {
        return sequence.read(reply);
    }

    IOReturn setSyncEnabled(const apple80211_awdl_sync_enabled *request)
    {
        if (!request || request->version > APPLE80211_VERSION || request->enabled > 1)
            return kIOReturnBadArgument;
        syncEnabled = request->enabled != 0;
        return kIOReturnSuccess;
    }

    IOReturn readSyncEnabled(apple80211_awdl_sync_enabled *reply) const
    {
        if (!reply)
            return kIOReturnBadArgument;
        *reply = {};
        reply->version = APPLE80211_VERSION;
        reply->enabled = syncEnabled;
        return kIOReturnSuccess;
    }

    IOReturn setFrameTemplate(const apple80211_awdl_sync_frame_template *request)
    {
        // IO80211Family has already marshalled this kernel request. Copy the
        // payload inside the callback and never keep the borrowed pointer.
        if (!request || request->version > APPLE80211_VERSION ||
            request->payload_len > sizeof(templateBytes) ||
            (request->payload_len && !request->payload))
            return kIOReturnBadArgument;
        const auto *bytes = static_cast<const uint8_t *>(request->payload);
        for (size_t i = 0; i < request->payload_len; ++i)
            templateBytes[i] = bytes[i];
        for (size_t i = request->payload_len; i < templateLength; ++i)
            templateBytes[i] = 0;
        templateLength = request->payload_len;
        return kIOReturnSuccess;
    }

    uint32_t frameTemplateLength() const { return templateLength; }
    // Borrowed while the configuration lock is held.
    const uint8_t *frameTemplate() const { return templateBytes; }

    MtkAwdlRequestedValue<apple80211_awdl_sync_params> syncParams;
    MtkAwdlRequestedValue<apple80211_awdl_bssid> bssid;
    MtkAwdlRequestedValue<apple80211_awdl_election_metric> electionMetric;
    MtkAwdlRequestedValue<apple80211_awdl_election_id> electionId;
    MtkAwdlRequestedValue<apple80211_awdl_election_rssi_thresholds> electionRssiThresholds;
    MtkAwdlRequestedValue<apple80211_awdl_min_rate> minRate;

private:
    bool supportsChannel(uint32_t channel) const
    {
        return channel < sizeof(supportedChannels) && supportedChannels[channel];
    }

    bool supportedChannels[256] = {};
    MtkAwdlRequestedValue<apple80211_awdl_master_channel> masterChannel;
    MtkAwdlRequestedValue<apple80211_awdl_secondary_master_channel> secondaryMasterChannel;
    MtkAwdlRequestedValue<apple80211_awdl_sync_state> syncState;

    // Same conservative driver-owned storage limit as ForbiddenItlwm.
    uint8_t templateBytes[0x724] = {};
    uint32_t templateLength = 0;
    MtkAwdlRequestedValue<apple80211_awdl_sync_channel_sequence> sequence;
    bool syncEnabled = false;
};
