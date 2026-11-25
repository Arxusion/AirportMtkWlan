// Minimal nonaggregated AWDL IPv6 transport. Framing follows ForbiddenItlwm
// (GPL-2.0); this layer does not own Skywalk packets or radio descriptors.
#pragma once
#include "Awdl/AWDLDataFrame.hpp"

namespace MtkAwdl {
constexpr size_t ethernetMax = 1514;

inline bool linkLocal(const uint8_t *ip)
{
    return ip[0] == 0xfe && (ip[1] & 0xc0) == 0x80;
}

// The experimental link carries only directly connected IPv6, with either a
// link-local unicast destination or interface/link-local multicast.
inline bool localTraffic(const uint8_t *ip, size_t length)
{
    return ItlAWDL::validIPv6Payload(ip, length) && linkLocal(ip + 8) &&
        (linkLocal(ip + 24) || (ip[24] == 0xff && (ip[25] & 15) <= 2));
}

inline bool finalizeChecksum(uint8_t *ip, size_t total)
{
    if (!localTraffic(ip, total))
        return false;
    const size_t length = total - 40;
    uint8_t *const payload = ip + 40;
    size_t field;
    switch (ip[6]) {
    case 6:
        if (length < 20 || (payload[12] >> 4) < 5 || size_t(payload[12] >> 4) * 4 > length)
            return false;
        field = 16;
        break;
    case 17:
        if (length < 8 || ((size_t(payload[4]) << 8) | payload[5]) != length)
            return false;
        field = 6;
        break;
    case 58:
        if (length < 4)
            return false;
        field = 2;
        break;
    default:
        return false;
    }

    payload[field] = payload[field + 1] = 0;
    uint32_t sum = uint32_t(length) + ip[6];
    for (size_t i = 8; i < 40; i += 2)
        sum += (uint32_t(ip[i]) << 8) | ip[i + 1];
    for (size_t i = 0; i < length; i += 2)
        sum += (uint32_t(payload[i]) << 8) | (i + 1 < length ? payload[i + 1] : 0);
    while (sum >> 16)
        sum = (sum & 0xffff) + (sum >> 16);
    const uint16_t check = uint16_t(~sum);
    const uint16_t wire = !check && ip[6] == 17 ? 0xffff : check;
    payload[field] = uint8_t(wire >> 8);
    payload[field + 1] = uint8_t(wire);
    return true;
}

inline bool buildData(const uint8_t *ethernet, size_t length, uint16_t sequence,
                      uint8_t *output, size_t capacity, size_t &written)
{
    constexpr uint8_t bssid[] = {0, 0x25, 0, 0xff, 0x94, 0x73};
    if (length < 54 || length > ethernetMax || capacity < length + 26 ||
        ethernet[12] != 0x86 || ethernet[13] != 0xdd)
        return false;
    size_t payloadLength = 0;
    if (ItlAWDL::buildIPv6DataPayload(ethernet + 14, length - 14, sequence,
            output + 24, capacity - 24, &payloadLength) != ItlAWDL::BuildResult::Ready ||
        !finalizeChecksum(output + 40, payloadLength - 16))
        return false;
    for (size_t i = 0; i < 24; ++i)
        output[i] = 0;
    output[0] = 0x08;
    for (size_t i = 0; i < 6; ++i) {
        output[4 + i] = ethernet[i];
        output[10 + i] = ethernet[6 + i];
        output[16 + i] = bssid[i];
    }
    ItlAWDL::write16(output + 22, uint16_t((sequence & 4095) << 4));
    written = 24 + payloadLength;
    return true;
}
}
