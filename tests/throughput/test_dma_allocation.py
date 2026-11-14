#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise actual DMA allocation functions for cache options, low addresses, reuse, and failures."""
import argparse
import os
from pathlib import Path
import subprocess

PRELUDE = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <vector>
using mach_vm_address_t = uint64_t;
using IOOptionBits = uint32_t;
using bus_size_t = uint32_t;
using bus_addr_t = uint64_t;
constexpr unsigned PAGE_SIZE = 4096;
constexpr IOOptionBits kIOMemoryPhysicallyContiguous = 0x10, kIOMapInhibitCache = 0x100;
int kernel_task;
std::vector<IOOptionBits> options;
uint64_t last_mask, next_address = 0x100000;
size_t last_size;
bool fail_alloc;
unsigned completes, releases;
struct IOBufferMemoryDescriptor {
    uint64_t address;
    static IOBufferMemoryDescriptor *inTaskWithPhysicalMask(int, IOOptionBits opt, size_t size, uint64_t mask) {
        options.push_back(opt); last_mask=mask; last_size=size;
        return fail_alloc ? nullptr : new IOBufferMemoryDescriptor{next_address};
    }
    void prepare() {}
    void complete() { ++completes; }
    void release() { ++releases; delete this; }
    uint64_t getPhysicalAddress() { return address; }
};
struct IOPhysicalSegment { uint64_t location, length; };
struct Mbuf { size_t length; std::vector<IOPhysicalSegment> segments; };
using mbuf_t=Mbuf *;
size_t mbuf_pkthdr_len(mbuf_t m) { return m->length; }
struct Cursor {
    unsigned getPhysicalSegmentsWithCoalesce(mbuf_t m, IOPhysicalSegment *out, unsigned limit) {
        assert(m->segments.size() <= limit);
        for (unsigned i=0;i<m->segments.size();++i) out[i]=m->segments[i];
        return m->segments.size();
    }
};
struct Segment { void *buf; uint64_t ds_addr; uint32_t ds_len; };
struct Map {
    IOBufferMemoryDescriptor *mem=nullptr;
    IOBufferMemoryDescriptor *dm_bounce_mem=nullptr;
    Cursor *cursor;
    mbuf_t dm_mbuf=nullptr;
    bool dm_bounce=false;
    unsigned dm_nsegs=0;
    bus_size_t dm_maxsize=2048, dm_mapsize=0, dm_bounce_size=0;
    Segment dm_segs[23] = {};
};
using bus_dmamap_t=Map *;
#define IOLog(...) ((void)0)
'''

MAIN = r'''
void dispose(Map &m) { if(m.dm_bounce_mem) { m.dm_bounce_mem->complete(); m.dm_bounce_mem->release(); m.dm_bounce_mem=nullptr; } }
int main() {
    auto ring=alloc_dma_memory(4096, PAGE_SIZE);
    assert(options.back()==(kIOMemoryPhysicallyContiguous | kIOMapInhibitCache));
    assert(last_mask==0xfffff000ULL && last_size==4096);
    ring->complete();ring->release();
    Cursor cursor; Map map; map.cursor=&cursor;
    Mbuf high{2048,{{0x100001000ULL,2048}}};
    assert(bus_dmamap_load(&map,&high)==0);
    assert(options.back()==kIOMemoryPhysicallyContiguous);
    assert(map.dm_bounce && map.dm_nsegs==1 && map.dm_segs[0].ds_addr==0x100000);
    assert(map.dm_segs[0].ds_len==2048 && last_mask==0xfffff000ULL);
    size_t allocations=options.size(); auto saved=map.dm_bounce_mem;
    assert(bus_dmamap_load(&map,&high)==0 && options.size()==allocations && map.dm_bounce_mem==saved);
    high.length=4096; high.segments[0].length=4096;
    unsigned old_releases=releases, old_completes=completes;
    assert(bus_dmamap_load(&map,&high)==0 && last_size==4096);
    assert(releases==old_releases+1 && completes==old_completes+1);
    assert(map.dm_bounce_size==4096 && options.back()==kIOMemoryPhysicallyContiguous);
    Mbuf low{512,{{0x200000,256},{0x201000,256}}};
    allocations=options.size();
    assert(bus_dmamap_load(&map,&low)==0 && !map.dm_bounce && map.dm_nsegs==2);
    assert(options.size()==allocations && map.dm_segs[1].ds_addr==0x201000);
    Map failed; failed.cursor=&cursor; fail_alloc=true;
    assert(bus_dmamap_load(&failed,&high)==1 && !failed.dm_bounce_mem);
    fail_alloc=false; next_address=0x100000000ULL;
    assert(bus_dmamap_load(&failed,&high)==1 && !failed.dm_bounce);
    assert(bus_dmamap_load(nullptr,&high)==1 && bus_dmamap_load(&map,nullptr)==1);
    dispose(map);dispose(failed);
    puts("PASS: bounce caching, ring defaults, 32-bit addresses, reuse/growth, and failure paths");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    text = (args.source / "mtk80211/compat.cpp").read_text()
    start = text.index("IOBufferMemoryDescriptor* alloc_dma_memory(")
    allocator = text[start:text.index("\nint bus_dmamem_alloc(", start)]
    start = text.index("int bus_dmamap_load(bus_dmamap_t map, mbuf_t mb)")
    loader = text[start:text.index("\nint bus_dmamap_load(bus_dma_tag_t", start)]
    output = Path(os.environ.get("MTK_TEST_BUILD_DIR", Path(__file__).resolve().parents[2] / "build/tests")) / "dma-allocation"
    output.mkdir(parents=True, exist_ok=True)
    cpp = output / "test.cpp"
    cpp.write_text(PRELUDE + allocator + loader + MAIN)
    binary = output / "test"
    subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g",
                    str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
