// AWDL Service Response TLV layout and name dictionary as in Wireshark's
// packet-awdl dissector. Only counts are kept; names are never published.
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace MtkAwdl {

inline bool localAirDropName(const uint8_t *name, size_t length, bool instance)
{
    constexpr char expected[] = "_airdrop._tcp.local";
    if (instance) {
        if (!length || !name[0] || name[0] > 63 || size_t(name[0]) + 1 >= length)
            return false;
        const size_t skip = name[0] + 1;
        name += skip;
        length -= skip;
    }
    // AWDL dictionary tokens encode suffixes directly, without DNS offsets.
    size_t matched = 0;
    bool ended = false;
    while (length) {
        size_t count = *name++;
        --length;
        if (count == 0 || (count == 0xc0 && length && *name == 0)) {
            if (count) { ++name; --length; }
            ended = true;
            continue;
        }
        if (ended || matched >= sizeof(expected) - 1)
            return false;
        const uint8_t *label = name;
        if (count == 0xc0 && length) {
            switch (*name++) {
            case 7: label = reinterpret_cast<const uint8_t *>(expected); count = 19; break;
            case 9: label = reinterpret_cast<const uint8_t *>(expected); count = 8; break;
            case 10: label = reinterpret_cast<const uint8_t *>(expected + 9); count = 10; break;
            case 12: label = reinterpret_cast<const uint8_t *>(expected + 14); count = 5; break;
            default: return false;
            }
            --length;
        } else {
            if (count > 63 || count > length)
                return false;
            name += count;
            length -= count;
        }
        if (matched && expected[matched++] != '.')
            return false;
        if (count > sizeof(expected) - 1 - matched)
            return false;
        for (size_t i = 0; i < count; ++i) {
            const auto byte = label[i];
            const auto lower = byte >= 'A' && byte <= 'Z' ? byte + ('a' - 'A') : byte;
            if (uint8_t(expected[matched++]) != lower)
                return false;
        }
    }
    return matched == sizeof(expected) - 1;
}

enum class PtrResult { Other, UnknownLayout, WrongType, BadLength, BadTarget, Valid };

inline PtrResult inspectAirDropPtr(const uint8_t *body, size_t bytes)
{
    if (!body || bytes < 2)
        return PtrResult::UnknownLayout;
    const size_t nameAndType = size_t(body[0]) | (size_t(body[1]) << 8);
    if (!nameAndType || nameAndType > bytes - 2)
        return PtrResult::UnknownLayout;
    if (!localAirDropName(body + 2, nameAndType - 1, false))
        return PtrResult::Other;
    if (body[1 + nameAndType] != 12)
        return PtrResult::WrongType;
    const size_t afterType = bytes - 2 - nameAndType;
    if (afterType < 4)
        return PtrResult::BadLength;
    const auto *rdata = body + 2 + nameAndType;
    const size_t length = size_t(rdata[0]) | (size_t(rdata[1]) << 8);
    if (length != afterType - 4)
        return PtrResult::BadLength;
    return localAirDropName(rdata + 4, length, true) ? PtrResult::Valid : PtrResult::BadTarget;
}

// Record names can be shortened in a template. Resolve a short PTR target
// only when a well-formed SRV record in the same template identifies it.
struct ServiceName {
    const uint8_t *bytes = nullptr;
    size_t length = 0;
};

inline bool serviceRecord(const uint8_t *body, size_t length, ServiceName &owner,
                          uint8_t &type, ServiceName &data)
{
    if (length < 7)
        return false;
    const size_t n = size_t(body[0]) | (size_t(body[1]) << 8);
    if (!n || n > length - 6)
        return false;
    const auto *rdata = body + 2 + n;
    const size_t bytes = size_t(rdata[0]) | (size_t(rdata[1]) << 8);
    if (bytes != length - 6 - n)
        return false;
    owner = {body + 2, n - 1};
    type = body[1 + n];
    data = {rdata + 4, bytes};
    return true;
}

inline size_t instanceLabel(ServiceName name)
{
    if (!name.length || !name.bytes[0] || name.bytes[0] > 63 ||
        size_t(name.bytes[0]) >= name.length)
        return 0;
    return name.bytes[0];
}

inline bool shortInstanceName(ServiceName name, size_t label)
{
    // The first label is the instance. Allow only an omitted domain or
    // its explicit empty terminator, and require a companion SRV below.
    const size_t tail = name.length - label - 1;
    const auto *suffix = name.bytes + label + 1;
    return tail == 0 || (tail == 1 && suffix[0] == 0) ||
        (tail == 2 && suffix[0] == 0xc0 && suffix[1] == 0);
}

inline bool sameName(ServiceName a, ServiceName b)
{
    if (a.length != b.length)
        return false;
    for (size_t i = 0; i < a.length; ++i) {
        const auto x = a.bytes[i];
        const auto y = b.bytes[i];
        if ((x >= 'A' && x <= 'Z' ? x + 32 : x) != (y >= 'A' && y <= 'Z' ? y + 32 : y))
            return false;
    }
    return true;
}

inline bool corroboratedAirDropTarget(ServiceName target, const uint8_t *tlvs, size_t length)
{
    const size_t label = instanceLabel(target);
    if (!label || !shortInstanceName(target, label))
        return false;
    const ServiceName instance = {target.bytes, label + 1};
    for (size_t offset = 0; offset < length;) {
        if (length - offset < 3)
            return false;
        const auto *tlv = tlvs + offset;
        const size_t bytes = size_t(tlv[1]) | (size_t(tlv[2]) << 8);
        if (bytes > length - offset - 3)
            return false;
        ServiceName owner, data;
        uint8_t type = 0;
        if (tlv[0] == 2 && serviceRecord(tlv + 3, bytes, owner, type, data) &&
            type == 33 && data.length >= 8 && (data.bytes[4] || data.bytes[5]) &&
            localAirDropName(owner.bytes, owner.length, true) &&
            instanceLabel(owner) == label && sameName(instance, {owner.bytes, label + 1}))
            return true;
        offset += bytes + 3;
    }
    return false;
}

inline bool isAirDropPtr(const uint8_t *body, size_t bytes)
{
    return inspectAirDropPtr(body, bytes) == PtrResult::Valid;
}

// An AirDrop label in an unrecognized record is an indicator only. It must
// never authorize the IPv6 stage or count as a valid service response.
inline bool hasAirDropNameHint(const uint8_t *body, size_t length)
{
    constexpr uint8_t label[] = {'_', 'a', 'i', 'r', 'd', 'r', 'o', 'p'};
    for (size_t offset = 0; offset < length; ++offset) {
        if (body[offset] == 0xc0 && length - offset >= 2 &&
            (body[offset + 1] == 7 || body[offset + 1] == 9))
            return true;
        if (body[offset] != sizeof(label) || length - offset <= sizeof(label))
            continue;
        size_t i = 0;
        for (; i < sizeof(label); ++i) {
            const auto c = body[offset + 1 + i];
            if (label[i] != (c >= 'A' && c <= 'Z' ? c + 32 : c))
                break;
        }
        if (i == sizeof(label))
            return true;
    }
    return false;
}
}
