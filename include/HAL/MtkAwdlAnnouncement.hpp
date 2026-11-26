// Fixed-channel announcement construction, based on ForbiddenItlwm (GPL-2.0).
#pragma once
#include "Awdl/AWDLLocalSchedule.hpp"
#include "MtkAwdlServiceRecord.hpp"

namespace MtkAwdl {
constexpr size_t announcementTemplateMax = 0x724;
constexpr size_t masterIndicationMax = 1200;

struct ServiceSummary {
    uint32_t records = 0;
    uint32_t airDropPtrs = 0;
    uint32_t airDropOtherTypes = 0;
    uint32_t airDropBadLengths = 0;
    uint32_t airDropBadTargets = 0;
    uint32_t airDropShortTargets = 0;
    uint32_t airDropCorroborated = 0;
    uint32_t airDropTargetBytes = 0;
    uint32_t airDropTargetLabelBytes = 0;
    uint32_t serviceUnknownLayouts = 0;
    uint32_t airDropOtherHints = 0;
    bool airDrop = false;

    void add(uint8_t type, const uint8_t *body, size_t length)
    {
        records += type == 2 && length != 0;
        if (type == 2) {
            const auto result = inspectAirDropPtr(body, length);
            airDropPtrs += result == PtrResult::Valid;
            airDropOtherTypes += result == PtrResult::WrongType;
            airDropBadLengths += result == PtrResult::BadLength;
            airDropBadTargets += result == PtrResult::BadTarget;
            serviceUnknownLayouts += result == PtrResult::UnknownLayout;
            airDropOtherHints += (result == PtrResult::Other || result == PtrResult::UnknownLayout) &&
                hasAirDropNameHint(body, length);
        }
        // Tahoe's AirDrop availability attribute (version, flags).
        airDrop |= type == 35 && length == 2 && body[0] == 1 && body[1] != 0;
    }

    bool advertisesService() const { return records != 0 || airDrop; }
};

inline void inspectShortAirDropTargets(const uint8_t *tlvs, size_t length, ServiceSummary &summary)
{
    if (!summary.airDropBadTargets)
        return;
    // The caller has already validated the entire TLV sequence.
    for (size_t offset = 0; offset < length;) {
        const auto *record = tlvs + offset;
        const size_t bytes = ItlAWDL::read16(record + 1);
        if (record[0] == 2 && inspectAirDropPtr(record + 3, bytes) == PtrResult::BadTarget) {
            ServiceName owner, target;
            uint8_t type = 0;
            if (serviceRecord(record + 3, bytes, owner, type, target)) {
                const size_t label = instanceLabel(target);
                summary.airDropTargetBytes = uint32_t(target.length);
                summary.airDropTargetLabelBytes = uint32_t(label);
                if (label && shortInstanceName(target, label)) {
                    ++summary.airDropShortTargets;
                    if (corroboratedAirDropTarget(target, tlvs, length)) {
                        ++summary.airDropCorroborated;
                        ++summary.airDropPtrs;
                        --summary.airDropBadTargets;
                    }
                }
            }
        }
        offset += bytes + 3;
    }
}

inline bool inspectMasterIndication(const uint8_t *bytes, size_t length, ServiceSummary &result)
{
    if (!bytes || !length || length > masterIndicationMax)
        return false;
    ServiceSummary services;
    bool election = false;
    for (size_t offset = 0; offset < length;) {
        if (length - offset < 3)
            return false;
        const uint8_t type = bytes[offset];
        const size_t bodyLength = ItlAWDL::read16(bytes + offset + 1);
        if (bodyLength > length - offset - 3)
            return false;
        election |= type == 24 && bodyLength >= 28;
        services.add(type, bytes + offset + 3, bodyLength);
        offset += 3 + bodyLength;
    }
    if (!election)
        return false;
    inspectShortAirDropTargets(bytes, length, services);
    result = services;
    return true;
}

enum class TxKind : uint8_t { Sync, Service, VerifiedService, Data, GroupData };

struct AnnouncementCompletions {
    uint32_t sent = 0;
    uint32_t failed = 0;
    uint32_t serviceSent = 0;
    uint32_t serviceFailed = 0;
    uint32_t lastStatus = 0;
    uint32_t verifiedServiceSent = 0;
    uint32_t verifiedCompletionLastUS = 0;
    uint32_t verifiedCompletionMaxUS = 0;
    uint32_t dataSent = 0;
    uint32_t dataFailed = 0;
    uint32_t unicastReportedSent = 0;
};

inline bool buildAnnouncement(const uint8_t *source, uint8_t channel, uint16_t sequence, uint64_t nowUS,
                              const uint8_t *nativeTemplate, size_t nativeLength,
                              uint8_t *tlvs, size_t tlvCapacity, uint8_t *output,
                              size_t outputCapacity, size_t *written, ServiceSummary *services, bool masterIndication)
{
    const uint8_t channelClass = ItlAWDL::globalOperatingClass20(channel);
    if (!channelClass || !source || !nativeTemplate || !nativeLength || nativeLength > announcementTemplateMax ||
        !tlvs || tlvCapacity < 44 || !output || !written || !services)
        return false;
    // Preserve Tahoe's service/identity records. Replace the channel and
    // timing description so the frame describes the channel actually used.
    tlvs[0] = 18;
    ItlAWDL::write16(tlvs + 1, 41);
    constexpr uint8_t header[] = {15, 3, 0, 3, 0xff, 0xff};
    for (unsigned i = 0; i < sizeof(header); ++i)
        tlvs[3 + i] = header[i];
    for (unsigned i = 0; i < 16; ++i) {
        tlvs[9 + i * 2] = channel;
        tlvs[10 + i * 2] = channelClass;
    }

    size_t used = 44;
    ServiceSummary summary;
    for (size_t offset = 0; offset < nativeLength;) {
        if (nativeLength - offset < 3)
            return false;
        const uint8_t type = nativeTemplate[offset];
        const size_t length = size_t(ItlAWDL::read16(nativeTemplate + offset + 1)) + 3;
        if (length > nativeLength - offset)
            return false;
        if (type != 4 && type != 18) {
            if (length > tlvCapacity - used)
                return false;
            for (size_t i = 0; i < length; ++i)
                tlvs[used + i] = nativeTemplate[offset + i];
            used += length;
            summary.add(type, nativeTemplate + offset + 3, length - 3);
        }
        offset += length;
    }

    ItlAWDL::SyncPrefix schedule = {channel, channel, 0,
        0, 16, 110, 0x1000, 16, 16, 0, 3, 3, 3, 3, {}};
    for (unsigned i = 0; i < 6; ++i)
        schedule.master[i] = source[i];
    uint8_t sync[73];
    size_t syncLength = 0;
    if (ItlAWDL::buildLocalFixedSchedule(schedule, 0, nowUS, 0, sync, sizeof(sync),
                                         &syncLength) != ItlAWDL::BuildResult::Ready)
        return false;
    ItlAWDL::LocalFrame frame = {{}, {255, 255, 255, 255, 255, 255},
        uint8_t(masterIndication ? 3 : 0), uint16_t(sequence & 4095),
        uint32_t(nowUS), uint32_t(nowUS), sync, syncLength, tlvs, used};
    for (unsigned i = 0; i < 6; ++i)
        frame.source[i] = source[i];
    if (ItlAWDL::buildLocalFrame(frame, output, outputCapacity, written) != ItlAWDL::BuildResult::Ready)
        return false;
    inspectShortAirDropTargets(tlvs, used, summary);
    *services = summary;
    return true;
}
}
