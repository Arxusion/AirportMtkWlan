// SPDX-License-Identifier: GPL-3.0-or-later
#include <HAL/MtkPerf.hpp>
#if MTK_PERF
#ifndef MTK_PERF_HOST
#include <IOKit/IOService.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSDictionary.h>
#endif

uint64_t mp_values[mp_count];
static const char *const mp_names[] = {
#define MP_NAME(n) #n,
    MP_FIELDS(MP_NAME)
#undef MP_NAME
};
static_assert(sizeof(mp_names) / sizeof(mp_names[0]) == mp_count, "counter names");

// Called under the main workloop gate. Replace the complete property atomically
// so readers never receive a partially populated snapshot. The current driver
// uses a single shared workloop/adapter; counters live for the kext session.
void mtk_perf_publish(IOService *nub)
{
    if (!nub) return;
    OSDictionary *d = OSDictionary::withCapacity(mp_count + 6);
    if (!d) return;
    bool ok = true;
    auto put = [&](const char *key, uint64_t value) {
        OSNumber *n = OSNumber::withNumber(value, 64);
        if (!n) { ok = false; return; }
        if (!d->setObject(key, n)) ok = false;
        n->release();
    };
    for (unsigned i = 0; i < mp_count; ++i) {
        uint64_t v = i == mp_watchdog_busy ?
            __atomic_load_n(&mp_values[i], __ATOMIC_RELAXED) : mp_values[i];
        put(mp_names[i], v);
    }
    static uint64_t sequence, session_ticks;
    if (!session_ticks) session_ticks = mach_absolute_time();
    put("schema", MP_SCHEMA);
    put("sequence", sequence + 1);
    put("session_ticks", session_ticks);
    put("snapshot_ticks", mach_absolute_time());
    uint64_t ns = 0;
    absolutetime_to_nanoseconds(1000000000ULL, &ns);
    put("ns_per_billion_ticks", ns);
    put("bounce_sample_period", MP_BOUNCE_SAMPLE_PERIOD);
    if (ok && nub->setProperty("MtkThroughput", d)) ++sequence;
    d->release();
}
#endif
