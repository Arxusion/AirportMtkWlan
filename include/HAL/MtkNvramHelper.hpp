//
//  MtkNvramHelper.hpp
//  SimpleMtkWlan
//
//  Shared NVRAM/boot-arg ASCII normalization and IODeviceTree /options reader
//  handling both OpenCore <string> (OSString) and <data> (OSData) properties.
//

#ifndef MtkNvramHelper_hpp
#define MtkNvramHelper_hpp

#include <stddef.h>
#include <stdint.h>
#include <string.h>

static inline size_t
mtkCopyTrimmedAscii(const char *src, size_t srcLen, char *dst, size_t dstSize)
{
    size_t len = 0;

    if (!dst || dstSize == 0)
        return 0;
    dst[0] = '\0';
    if (!src || srcLen == 0)
        return 0;

    while (len < srcLen && src[len] != '\0')
        len++;
    while (len > 0 && (src[len - 1] == ' ' || src[len - 1] == '\t' ||
                       src[len - 1] == '\r' || src[len - 1] == '\n'))
        len--;

    size_t start = 0;
    while (start < len && (src[start] == ' ' || src[start] == '\t' ||
                           src[start] == '\r' || src[start] == '\n'))
        start++;

    size_t copyLen = len - start;
    if (copyLen >= dstSize)
        copyLen = dstSize - 1;
    if (copyLen > 0)
        memcpy(dst, src + start, copyLen);
    dst[copyLen] = '\0';
    return copyLen;
}

static inline char
mtkParseBandOption(const char *raw, size_t rawLen)
{
    char buf[8];
    if (mtkCopyTrimmedAscii(raw, rawLen, buf, sizeof(buf)) == 0)
        return 0;
    if (buf[0] == '5' || buf[0] == '2')
        return buf[0];
    return 0;
}

static inline bool
mtkNormalizeCountryCode(const char *src, size_t srcLen, char out[3])
{
    char buf[8];
    if (!out)
        return false;
    out[0] = '\0';
    if (mtkCopyTrimmedAscii(src, srcLen, buf, sizeof(buf)) < 2)
        return false;

    char c0 = buf[0];
    char c1 = buf[1];
    if (c0 >= 'a' && c0 <= 'z')
        c0 = (char)(c0 - 'a' + 'A');
    if (c1 >= 'a' && c1 <= 'z')
        c1 = (char)(c1 - 'a' + 'A');

    auto isAlnumUpper = [](char c) {
        return (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
    };
    if (!isAlnumUpper(c0) || !isAlnumUpper(c1))
        return false;
    /* Reject Apple/dummy placeholder codes such as XX, XZ, ZZ */
    if (c0 == 'X' || (c0 == 'Z' && c1 == 'Z'))
        return false;

    out[0] = c0;
    out[1] = c1;
    out[2] = '\0';
    return true;
}

#if defined(KERNEL) && defined(__cplusplus)
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSString.h>

static inline bool
mtkReadNvramAscii(const char *primaryKey, const char *fallbackKey,
                  char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return false;
    out[0] = '\0';

    const IORegistryPlane *dt = IORegistryEntry::getPlane("IODeviceTree");
    if (!dt)
        return false;

    IORegistryEntry *opts = IORegistryEntry::fromPath("/options", dt);
    if (!opts)
        return false;

    bool found = false;
    const char *keys[2] = { primaryKey, fallbackKey };
    for (int i = 0; i < 2 && !found; i++) {
        if (!keys[i])
            continue;
        OSObject *obj = opts->copyProperty(keys[i]);
        if (!obj)
            continue;
        if (OSString *s = OSDynamicCast(OSString, obj)) {
            found = mtkCopyTrimmedAscii(s->getCStringNoCopy(), s->getLength(),
                                        out, outSize) > 0;
        } else if (OSData *d = OSDynamicCast(OSData, obj)) {
            found = mtkCopyTrimmedAscii((const char *)d->getBytesNoCopy(),
                                        d->getLength(), out, outSize) > 0;
        }
        obj->release();
    }

    opts->release();
    return found;
}
#endif /* KERNEL && __cplusplus */

#endif /* MtkNvramHelper_hpp */
