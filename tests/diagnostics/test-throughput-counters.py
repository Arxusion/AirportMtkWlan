#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile the actual collector with host ownership/failure stubs; verify enabled and disabled builds."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <map>
#include <string>
#include <thread>
#include <vector>
uint64_t now_ticks=100, clock_calls=0;
uint64_t mach_absolute_time() { ++clock_calls; return now_ticks++; }
void absolutetime_to_nanoseconds(uint64_t ticks, uint64_t *ns) { *ns=ticks*2; }
#include <HAL/MtkPerf.hpp>
int live=0, numbers=0, inserts=0, fail_number=0, fail_insert=0;
bool fail_dictionary=false, fail_publish=false;
struct Ref {
    unsigned refs=1;
    Ref() { ++live; }
    virtual ~Ref() { --live; }
    void retain() { ++refs; }
    void release() { assert(refs); if(!--refs) delete this; }
};
struct OSNumber: Ref {
    uint64_t value;
    explicit OSNumber(uint64_t v): value(v) {}
    static OSNumber *withNumber(uint64_t v, unsigned bits) {
        assert(bits==64);
        return ++numbers==fail_number ? nullptr : new OSNumber(v);
    }
};
struct OSDictionary: Ref {
    std::map<std::string, OSNumber *> values;
    ~OSDictionary() { for(auto &entry:values) entry.second->release(); }
    static OSDictionary *withCapacity(unsigned capacity) {
        assert(capacity==mp_count+6);
        return fail_dictionary ? nullptr : new OSDictionary;
    }
    bool setObject(const char *key, OSNumber *n) {
        if(++inserts==fail_insert) return false;
        assert(!values.count(key));
        n->retain(); values[key]=n; return true;
    }
    uint64_t get(const char *key) const { return values.at(key)->value; }
};
class IOService {
public:
    OSDictionary *property=nullptr;
    ~IOService() { if(property) property->release(); }
    bool setProperty(const char *key, OSDictionary *d) {
        assert(std::string(key)=="MtkThroughput");
        if(fail_publish) return false;
        d->retain();
        if(property) property->release();
        property=d; return true;
    }
};
#include "MtkPerf.cpp"
void reset_failures() {
    numbers=inserts=fail_number=fail_insert=0;
    fail_dictionary=fail_publish=false;
}
int main() {
    mp_add(mp_rx_desc,7); mp_set(mp_gauge_tx_free,32);
    mp_time(mp_rx_dequeue_samples,20); mp_time(mp_rx_dequeue_samples,10);
    assert(mp_values[mp_rx_dequeue_samples]==2);
    assert(mp_values[mp_rx_dequeue_ticks]==30 && mp_values[mp_rx_dequeue_max_ticks]==20);
    auto calls=clock_calls;
    { MpTimer disabled(mp_rx_refill_samples,false); now_ticks+=10; }
    assert(clock_calls==calls && mp_values[mp_rx_refill_samples]==0);
    { MpTimer enabled(mp_rx_refill_samples); now_ticks+=9; }
    assert(clock_calls==calls+2 && mp_values[mp_rx_refill_ticks]==10);
    for(unsigned i=0;i<128;i++) {
        mp_add(mp_bounce_rx_calls);
        MpTimer sampled(mp_rx_bounce_sample_samples,
            mp_values[mp_bounce_rx_calls]%MP_BOUNCE_SAMPLE_PERIOD==0);
    }
    assert(mp_values[mp_rx_bounce_sample_samples]==2 && clock_calls==calls+6);
    std::vector<std::thread> workers;
    for(int i=0;i<4;i++) workers.emplace_back([] {
        for(int j=0;j<25000;j++) mp_async_add(mp_watchdog_busy);
    });
    for(auto &worker:workers) worker.join();
    mtk_perf_publish(nullptr); assert(live==0);
    {
        IOService nub;
        mtk_perf_publish(&nub);
        auto first=nub.property;
        assert(first && first->values.size()==mp_count+6);
        assert(first->get("schema")==2 && first->get("sequence")==1);
        assert(first->get("watchdog_busy")==100000 && first->get("rx_desc")==7);
        assert(first->get("gauge_tx_free")==32 && first->get("bounce_sample_period")==64);
        assert(first->get("ns_per_billion_ticks")==2000000000);
        auto session=first->get("session_ticks"), ticks=first->get("snapshot_ticks");
        assert(ticks>=session && session>0);
        const int held=live;
        // Failure at any field must preserve the previous complete property and sequence.
        fail_dictionary=true; mtk_perf_publish(&nub); reset_failures();
        assert(nub.property==first && live==held);
        for(unsigned field=1;field<=mp_count+6;field++) {
            fail_number=field; mtk_perf_publish(&nub); reset_failures();
            assert(nub.property==first && live==held);
            fail_insert=field; mtk_perf_publish(&nub); reset_failures();
            assert(nub.property==first && live==held);
        }
        fail_publish=true; mtk_perf_publish(&nub); reset_failures();
        assert(nub.property==first && live==held);
        mp_add(mp_rx_desc);
        mtk_perf_publish(&nub);
        assert(nub.property!=first && live==held);
        assert(nub.property->get("sequence")==2 && nub.property->get("rx_desc")==8);
        assert(nub.property->get("session_ticks")==session);
        assert(nub.property->get("snapshot_ticks")>ticks);
    }
    assert(live==0);
    puts("PASS: timers, atomic contention counter, complete publication, and failure ownership");
}
'''


def main():
    output = Path(os.environ.get("MTK_TEST_BUILD_DIR", ROOT / "build/tests")) / "throughput-counters"
    output.mkdir(parents=True, exist_ok=True)
    cpp, binary = output / "test.cpp", output / "test"
    cpp.write_text(HARNESS)
    flags = ["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", "-pthread",
             "-I", str(ROOT / "SimpleMtkWlan"), "-I", str(ROOT / "include"), "-DMTK_PERF_HOST=1"]
    subprocess.run(flags + ["-DMTK_PERF=1", str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    cpp.write_text('#include "MtkPerf.cpp"\nstatic_assert(MTK_PERF==0,"default off");\nint main() {}\n')
    for mode in ([], ["-DMTK_PERF=0"]):
        subprocess.run(flags + mode + [str(cpp), "-o", str(binary)], check=True)
        symbols = subprocess.check_output(["nm", str(binary)], text=True)
        assert "mp_values" not in symbols and "mtk_perf_publish" not in symbols
        subprocess.run([str(binary)], check=True)
    print("PASS: default and explicit disabled collector contain no diagnostic symbols")


if __name__ == "__main__":
    main()
