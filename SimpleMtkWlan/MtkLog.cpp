//
//  MtkLog.cpp
//  SimpleMtkWlan
//

#include "MtkLog.hpp"
#include <IOKit/IOLib.h>
#include <libkern/libkern.h>
#include <libkern/OSAtomic.h>
#include <kern/clock.h>

/*
 * Persistent debug log. Early boot messages are lost from the unified log
 * (no uuidtext for OpenCore-injected kexts, small msgbuf), so every message
 * is also kept in a ring buffer and published as the "MtkDebugLog" property
 * on the PCI provider, where it survives a failed probe/start.
 */
#define MTK_DBG_BUF_SIZE (128 * 1024)
static char gMtkDbgBuf[MTK_DBG_BUF_SIZE];
static size_t gMtkDbgLen;
static volatile SInt32 gMtkDbgLock;
static IOService *gMtkDbgNub;

static void mtkDbgLock()
{
    while (!OSCompareAndSwap(0, 1, &gMtkDbgLock)) {}
}

static void mtkDbgUnlock()
{
    OSCompareAndSwap(1, 0, &gMtkDbgLock);
}

extern "C" void mtk_dbg_log(const char *fmt, ...)
{
    char line[512];
    uint64_t ns;
    va_list ap;
    int prefix;
    size_t len;

    absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
    prefix = snprintf(line, sizeof(line), "[%llu.%03llu] ",
        ns / 1000000000ULL, (ns / 1000000ULL) % 1000ULL);
    va_start(ap, fmt);
    vsnprintf(line + prefix, sizeof(line) - prefix, fmt, ap);
    va_end(ap);

    len = strnlen(line, sizeof(line));
    mtkDbgLock();
    if (gMtkDbgLen + len >= MTK_DBG_BUF_SIZE) {
        size_t drop = MTK_DBG_BUF_SIZE / 2;
        memmove(gMtkDbgBuf, gMtkDbgBuf + drop, gMtkDbgLen - drop);
        gMtkDbgLen -= drop;
    }
    memcpy(gMtkDbgBuf + gMtkDbgLen, line, len);
    gMtkDbgLen += len;
    gMtkDbgBuf[gMtkDbgLen] = 0;
    mtkDbgUnlock();
}

void mtk_dbg_publish()
{
    IOService *nub = gMtkDbgNub;
    char *copy;
    size_t len;

    if (nub == NULL)
        return;
    copy = (char *)IOMalloc(MTK_DBG_BUF_SIZE);
    if (copy == NULL)
        return;
    mtkDbgLock();
    len = gMtkDbgLen;
    memcpy(copy, gMtkDbgBuf, len);
    mtkDbgUnlock();
    copy[len] = 0;
    OSString *str = OSString::withCString(copy);
    IOFree(copy, MTK_DBG_BUF_SIZE);
    if (str != NULL) {
        nub->setProperty("MtkDebugLog", str);
        str->release();
    }
}

void mtk_dbg_set_nub(IOService *nub)
{
    gMtkDbgNub = nub;
}
