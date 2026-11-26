// AWDL management frame validation for RX-only peer discovery. The wire
// format follows ForbiddenItlwm's AWDLFrameParser (GPL-2.0).
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace MtkAwdl {
constexpr size_t actionHeaderLength = 24;
constexpr size_t minimumFrameLength = 40;
constexpr size_t maximumFrameLength = 2304;

inline bool hasFcs(const uint8_t *frame, size_t length)
{
    const size_t end = length - 4;
    uint32_t crc = 0xffffffffu;
    for (size_t i = 0; i < end; ++i) {
        crc ^= frame[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320u : 0u);
    }
    const uint32_t trailer = uint32_t(frame[end]) | (uint32_t(frame[end + 1]) << 8) |
        (uint32_t(frame[end + 2]) << 16) | (uint32_t(frame[end + 3]) << 24);
    return ~crc == trailer;
}

// Returns the length of a complete validated frame, excluding a verified FCS.
inline size_t actionFrameLength(const uint8_t *frame, size_t length)
{
    if (!frame || length < minimumFrameLength || length > maximumFrameLength ||
        frame[0] != 0xd0 || (frame[1] & 0xc7) || (frame[22] & 0x0f))
        return 0;
    constexpr uint8_t bssid[] = {0x00, 0x25, 0x00, 0xff, 0x94, 0x73};
    constexpr uint8_t action[] = {0x7f, 0x00, 0x17, 0xf2, 0x08, 0x10};
    for (size_t i = 0; i < sizeof(bssid); ++i) {
        if (frame[16 + i] != bssid[i] || frame[actionHeaderLength + i] != action[i])
            return 0;
    }
    if (frame[30] != 0 && frame[30] != 3)
        return 0;

    if (length >= minimumFrameLength + 4 && hasFcs(frame, length))
        length -= 4;
    bool syncSeen = false;
    for (size_t offset = minimumFrameLength; offset < length;) {
        if (length - offset < 3)
            return 0;
        const uint8_t type = frame[offset];
        const size_t bytes = size_t(frame[offset + 1]) | (size_t(frame[offset + 2]) << 8);
        offset += 3;
        if (bytes > length - offset)
            return 0;
        if (type == 4) {
            if (bytes < 27 || syncSeen)
                return 0;
            syncSeen = true;
        }
        offset += bytes;
    }
    return syncSeen ? length : 0;
}
}
