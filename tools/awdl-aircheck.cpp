// Offline classic pcap reader for AWDL tests on your own test devices.
#include <array>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <fstream>
#include <stdexcept>
#include <HAL/Awdl/AWDLPeerSchedule.hpp>
#include <HAL/MtkAwdlActionFrame.hpp>
#include <HAL/MtkAwdlAnnouncement.hpp>

using Address = std::array<uint8_t, 6>;

static Address mac(const char *string)
{
    unsigned n[6];
    char tail;
    if (std::sscanf(string, "%2x:%2x:%2x:%2x:%2x:%2x%c",
            &n[0], &n[1], &n[2], &n[3], &n[4], &n[5], &tail) != 6)
        throw std::runtime_error("Expected a colon-separated MAC address.");
    return {uint8_t(n[0]), uint8_t(n[1]), uint8_t(n[2]),
            uint8_t(n[3]), uint8_t(n[4]), uint8_t(n[5])};
}

static uint32_t read32(const uint8_t *bytes, bool little)
{
    uint32_t result = 0;
    for (unsigned i = 0; i < 4; ++i)
        result = (result << 8) | bytes[little ? 3 - i : i];
    return result;
}

static bool radiotap(const uint8_t *bytes, size_t length, size_t &headerLength, unsigned expectedFrequency)
{
    if (length < 8 || bytes[0] != 0)
        return false;
    headerLength = ItlAWDL::read16(bytes + 2);
    if (headerLength < 8 || headerLength > length)
        return false;
    const uint32_t fields = read32(bytes + 4, true);
    size_t offset = 8;
    uint32_t next = fields;
    while (next & 0x80000000u) {
        if (headerLength - offset < 4)
            return false;
        next = read32(bytes + offset, true);
        offset += 4;
    }
    if (fields & 1u)
        offset = ((offset + 7) & ~size_t(7)) + 8; // alignment and size of TSFT
    if (fields & 2u) {
        if (offset >= headerLength || (bytes[offset] & 0x40))
            return false; // bad FCS flag
        ++offset;
    }
    if (fields & 4u)
        ++offset; // rate
    if (fields & 8u) {
        offset = (offset + 1) & ~size_t(1);
        if (offset + 4 > headerLength || ItlAWDL::read16(bytes + offset) != expectedFrequency)
            return false;
    }
    return true;
}

static int check(const char *capture, const Address &local, const Address &peer, uint8_t channel)
{
    if (local == peer)
        throw std::runtime_error("The local and peer addresses must be different.");
    std::ifstream file(capture, std::ios::binary);
    uint8_t header[24];
    if (!file.read(reinterpret_cast<char *>(header), sizeof(header)))
        throw std::runtime_error("Cannot read the pcap header.");
    const auto magic = read32(header, false);
    const bool little = magic == 0xd4c3b2a1 || magic == 0x4d3cb2a1;
    const bool nano = magic == 0x4d3cb2a1 || magic == 0xa1b23c4d;
    if (!little && magic != 0xa1b2c3d4 && !nano)
        throw std::runtime_error("Use classic pcap, converted with editcap -F pcap if necessary.");
    const uint32_t link = read32(header + 20, little) & 0xffff;
    if (link != 127 && link != 105)
        throw std::runtime_error("Use a monitor capture with 802.11 or radiotap headers.");

    const unsigned frequency = (channel <= 13 ? 2407 : 5000) + channel * 5;
    ItlAWDL::PeerSchedule schedule = {};
    schedule.assumeZero = true;
    uint64_t peerFrames = 0, localFrames = 0, framesWithPTR = 0, records = 0;
    uint64_t unknown = 0, onChannel = 0, nearAwStart = 0, offChannel = 0;
    uint8_t packet[65536];
    while (file.read(reinterpret_cast<char *>(header), 16)) {
        const uint64_t now = uint64_t(read32(header, little)) * 1000000 +
            read32(header + 4, little) / (nano ? 1000 : 1);
        const auto captured = read32(header + 8, little);
        if (captured > sizeof(packet) || !file.read(reinterpret_cast<char *>(packet), captured))
            throw std::runtime_error("Truncated or oversized capture packet.");
        size_t prefix = 0;
        if (link == 127 && !radiotap(packet, captured, prefix, frequency))
            continue;
        const auto *frame = packet + prefix;
        const size_t length = MtkAwdl::actionFrameLength(frame, captured - prefix);
        if (!length)
            continue;

        if (!memcmp(frame + 10, peer.data(), 6)) {
            ItlAWDL::PeerSyncInfo info;
            if (ItlAWDL::peerSyncFromAction(frame, length, &info)) {
                ++peerFrames;
                uint64_t into = 0;
                const bool fresh = schedule.fresh(now) && schedule.eawUS;
                const auto prior = fresh ? schedule.eawAt(now, &into) : 0;
                if (schedule.note(info, now, channel) == ItlAWDL::PeerSchedule::Update::Stable)
                    schedule.notePeerEntry(prior, into);
            }
            continue;
        }
        if (memcmp(frame + 10, local.data(), 6))
            continue;
        ++localFrames;
        MtkAwdl::ServiceSummary services;
        for (size_t offset = MtkAwdl::minimumFrameLength; offset < length;) {
            const size_t size = ItlAWDL::read16(frame + offset + 1);
            services.add(frame[offset], frame + offset + 3, size);
            offset += 3 + size;
        }
        MtkAwdl::inspectShortAirDropTargets(frame + MtkAwdl::minimumFrameLength,
            length - MtkAwdl::minimumFrameLength, services);
        if (!services.airDropPtrs)
            continue;
        ++framesWithPTR;
        records += services.airDropPtrs;
        if (!schedule.timingUsable(now, false)) {
            ++unknown;
        } else if (schedule.presentInEntry(schedule.eawAt(now, nullptr))) {
            ++onChannel;
            nearAwStart += schedule.inPresentAwStart(now, 4500);
        } else {
            ++offChannel;
        }
    }
    std::printf("Peer schedule frames: %llu\nMac AWDL action frames: %llu\n"
                "Mac frames with valid AirDrop PTR: %llu (records=%llu)\n"
                "In peer's channel-%u slots: %llu (first 4.5 ms of AW: %llu)\n"
                "Outside peer's selected channel slots: %llu\nWithout fresh peer timing: %llu\n",
        (unsigned long long)peerFrames, (unsigned long long)localFrames,
        (unsigned long long)framesWithPTR, (unsigned long long)records,
        unsigned(channel), (unsigned long long)onChannel, (unsigned long long)nearAwStart,
        (unsigned long long)offChannel, (unsigned long long)unknown);
    return framesWithPTR && onChannel ? 0 : 2;
}

int main(int argc, char **argv)
{
    if (argc != 5) {
        std::fprintf(stderr, "Usage: %s capture.pcap mac-awdl-address iphone-awdl-address channel\n", argv[0]);
        return 1;
    }
    try {
        char *end = nullptr;
        const auto channel = std::strtoul(argv[4], &end, 10);
        if (end == argv[4] || *end || channel > 255 || !ItlAWDL::fixedScheduleChannel(uint8_t(channel)))
            throw std::runtime_error("Enter the monitored primary channel. DFS and 6 GHz are outside this test.");
        return check(argv[1], mac(argv[2]), mac(argv[3]), uint8_t(channel));
    } catch (const std::exception &exception) {
        std::fprintf(stderr, "%s\n", exception.what());
        return 1;
    }
}
