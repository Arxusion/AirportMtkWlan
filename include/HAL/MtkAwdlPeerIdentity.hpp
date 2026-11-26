#pragma once
#include <stddef.h>
#include <stdint.h>

namespace MtkAwdl {
struct PeerIdentity {
    uint8_t address[6] = {};
    char hostname[64] = {};
};

inline unsigned lowerASCII(unsigned c)
{
    return c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c;
}

inline bool matchHostLabel(const uint8_t *label, size_t length, const char *name)
{
    if (!length || length > 63)
        return false;
    for (size_t i = 0; i < length; ++i) {
        if (!name[i] || lowerASCII(label[i]) != lowerASCII(uint8_t(name[i])))
            return false;
    }
    return !name[length];
}

inline bool matchNativeHostname(const char *hostname, const char *requested)
{
    // 25G342 actionFrameReport writes at most 30 characters and a terminator.
    if (!hostname)
        return false;
    size_t length = 0;
    while (length < 31 && hostname[length])
        ++length;
    if (length == 31)
        return false;
    constexpr char local[] = ".local";
    if (length > sizeof(local) - 1) {
        const size_t suffix = length - (sizeof(local) - 1);
        size_t i = 0;
        while (i < sizeof(local) - 1 &&
               lowerASCII(uint8_t(hostname[suffix + i])) == uint8_t(local[i]))
            ++i;
        if (i == sizeof(local) - 1)
            length = suffix;
    }
    return matchHostLabel(reinterpret_cast<const uint8_t *>(hostname), length, requested);
}

enum class ArpaName : uint8_t { Absent, Other, DnsLabel, PlainLabel };

inline ArpaName inspectArpaName(const uint8_t *frame, size_t length, const char *name)
{
    ArpaName found = ArpaName::Absent;
    for (size_t offset = 40; offset < length;) {
        if (length - offset < 3)
            return found;
        const auto *record = frame + offset;
        const size_t bytes = size_t(record[1]) | (size_t(record[2]) << 8);
        if (bytes > length - offset - 3)
            return found;
        if (record[0] == 16 && bytes >= 2) {
            found = ArpaName::Other;
            const auto *body = record + 4; // Skip the ARPA flags byte.
            const size_t bodyLength = bytes - 1;
            if (body[0] < bodyLength && matchHostLabel(body + 1, body[0], name))
                return ArpaName::DnsLabel;
            // Tahoe's actionFrameReport also reads a printable, terminated
            // host name directly from this offset.
            size_t n = 0;
            while (n < bodyLength && body[n] >= 0x20 && body[n] <= 0x7e)
                ++n;
            if (n <= 30) {
                char plain[31] = {};
                for (size_t i = 0; i < n; ++i)
                    plain[i] = char(body[i]);
                if (matchNativeHostname(plain, name))
                    return ArpaName::PlainLabel;
            }
        }
        offset += 3 + bytes;
    }
    return found;
}

inline bool matchHostname(const uint8_t *frame, size_t length, const char *name)
{
    const auto arpa = inspectArpaName(frame, length, name);
    return arpa == ArpaName::DnsLabel || arpa == ArpaName::PlainLabel;
}
}
