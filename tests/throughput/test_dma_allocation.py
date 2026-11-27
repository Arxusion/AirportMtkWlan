#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise actual DMA functions for mapping identity, 32-bit bounds, caching and release order."""
import argparse
import os
from pathlib import Path
import re
import subprocess

PRELUDE = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <vector>
using mach_vm_address_t = uint64_t;
using IOByteCount = uint64_t;
using addr64_t = uint64_t;
using IOOptionBits = uint32_t;
using bus_size_t = uint32_t;
using bus_addr_t = uint64_t;
using bus_dma_tag_t = int;
constexpr unsigned PAGE_SIZE = 4096;
constexpr IOOptionBits kIOMemoryPhysicallyContiguous = 0x10, kIOMapInhibitCache = 0x100;
constexpr unsigned kIODirectionInOut=3, kIODirectionOutIn=3;
constexpr int kIOReturnSuccess=0, MBUF_DONTWAIT=0;
constexpr int BUS_DMASYNC_PREREAD=1, BUS_DMASYNC_PREWRITE=2,
    BUS_DMASYNC_POSTREAD=4, BUS_DMASYNC_POSTWRITE=8;
int kernel_task;
std::vector<IOOptionBits> options;
uint64_t last_mask, next_address=0x100000, next_span=UINT64_MAX;
uint64_t next_cpu_address=0x900000000ULL;
size_t last_size;
bool fail_alloc=false, fail_prepare=false, mapper_enabled=false;
unsigned live=0, completes=0, releases=0, aliases=0;
struct IOMemoryDescriptor {
    uint64_t address, span, cpu_address;
    unsigned references=1, prepares=0;
    std::vector<uint8_t> bytes;
    IOMemoryDescriptor(uint64_t a,uint64_t n):address(a),span(n),cpu_address(next_cpu_address) {++live;}
    virtual ~IOMemoryDescriptor() {assert(!prepares);--live;}
    static IOMemoryDescriptor *withAddress(void *,uint32_t size,unsigned) {
        ++aliases;
        return new IOMemoryDescriptor(mapper_enabled?0x100200000ULL:next_cpu_address,size);
    }
    int prepare(unsigned=0) {if(fail_prepare)return 1; ++prepares;return 0;}
    void complete() {assert(prepares);--prepares;++completes;}
    void retain() {++references;}
    void release() {assert(references);++releases;if(!--references)delete this;}
    uint64_t getPhysicalSegment(uint64_t off,uint64_t *len) {
        assert(prepares);
        if(off>=span) {*len=0;return 0;}
        *len=span-off;return address+off;
    }
    uint64_t getPhysicalAddress() {uint64_t n;return getPhysicalSegment(0,&n);}
    void *getBytesNoCopy() {return bytes.data();}
};
struct IOBufferMemoryDescriptor : IOMemoryDescriptor {
    IOBufferMemoryDescriptor(uint64_t a,uint64_t n):IOMemoryDescriptor(a,n) {}
    static IOBufferMemoryDescriptor *inTaskWithPhysicalMask(int,IOOptionBits opt,size_t size,uint64_t mask) {
        options.push_back(opt);last_mask=mask;last_size=size;
        if(fail_alloc)return nullptr;
        auto mem=new IOBufferMemoryDescriptor(next_address,next_span==UINT64_MAX?size:next_span);
        mem->bytes.resize(size);return mem;
    }
};
struct IOPhysicalSegment {uint64_t location,length;};
struct Mbuf {size_t length;std::vector<IOPhysicalSegment> segments;std::vector<uint8_t> bytes;};
using mbuf_t=Mbuf *;
size_t mbuf_pkthdr_len(mbuf_t m) {return m->length;}
void mbuf_copydata(mbuf_t m,size_t off,size_t n,void *out) {
    assert(off+n<=m->bytes.size());memcpy(out,m->bytes.data()+off,n);
}
void mbuf_copyback(mbuf_t m,size_t off,size_t n,const void *in,int) {
    assert(off+n<=m->bytes.size());memcpy(m->bytes.data()+off,in,n);
}
void mbuf_inbound_modified(mbuf_t) {}
struct IOMbufNaturalMemoryCursor {
    static IOMbufNaturalMemoryCursor *withSpecification(uint32_t,int) {return new IOMbufNaturalMemoryCursor;}
    unsigned getPhysicalSegmentsWithCoalesce(mbuf_t m,IOPhysicalSegment *out,unsigned limit) {
        assert(limit==0 || m->segments.size()<=limit);
        for(unsigned i=0;i<m->segments.size();++i)out[i]=m->segments[i];
        return m->segments.size();
    }
    void release() {delete this;}
};
#define IOLog(...) ((void)0)
'''

MAIN = r'''
bus_dmamap_t new_map() {
    bus_dmamap_t map=nullptr;
    assert(bus_dmamap_create(0,2048,23,16383,0,0,&map)==0);
    return map;
}
int main() {
    for(bool mapped : {false,true}) {
        mapper_enabled=mapped;
        next_cpu_address=mapped?0x900000000ULL:next_address;
        bus_dma_segment_t ring{};int n=0;
        assert(bus_dmamem_alloc(0,8192,PAGE_SIZE,0,&ring,1,&n,0)==0 && n==1);
        assert(last_mask==0xfffff000ULL && last_size==8192);
        assert((options.back() & ~kIODirectionInOut)==(kIOMemoryPhysicallyContiguous|kIOMapInhibitCache));
        void *va=nullptr;assert(bus_dmamem_map(0,&ring,1,8192,&va,0)==0);
        auto map=new_map();
#ifdef LEGACY
        assert(bus_dmamap_load(0,map,va,8192,nullptr,0)==0);
        assert(map->dm_segs[0].ds_addr==(mapped?0x100200000ULL:ring.ds_addr));
        assert((map->dm_segs[0].ds_addr!=ring.ds_addr)==mapped);
        assert((uint32_t(map->dm_segs[0].ds_addr)!=map->dm_segs[0].ds_addr)==mapped);
        bus_dmamap_unload(0,map);
        ring.buf->complete();
#else
        assert(bus_dmamap_load(0,map,&ring,0)==0);
        assert(aliases==0 && map->mem==ring.buf);
        assert(map->dm_nsegs==1 && map->dm_segs[0].ds_addr==next_address);
        assert(map->dm_mapsize==8192 && map->dm_segs[0].ds_len==8192);
        assert((map->dm_segs[0].ds_addr!=ring.buf->cpu_address)==mapped);
        assert(bus_dmamap_load(0,map,&ring,0)==0);
        assert(ring.buf->prepares==2 && ring.buf->references==2);
        bus_dmamap_unload(0,map);
        fail_prepare=true;
        assert(bus_dmamap_load(0,map,&ring,0)==1 && !map->mem && !map->dm_nsegs);
        fail_prepare=false;
        assert(bus_dmamap_load(0,map,&ring,0)==0);
#endif
        bus_dmamem_free(0,&ring,1);
        bus_dmamap_destroy(0,map);
        assert(live==0);
    }
#ifdef LEGACY
    puts("Reproduced: rewrapping the ring loses its 32-bit mapping and truncates a high IOVA.");
    return 0;
#else
    auto map=new_map();
    Mbuf high{2048,{{0x100001000ULL,2048}},std::vector<uint8_t>(2048,0x5a)};
    assert(bus_dmamap_load(map,&high)==0);
    assert(options.back()==(kIOMemoryPhysicallyContiguous|kIODirectionInOut));
    assert(map->dm_bounce && map->dm_nsegs==1 && map->dm_segs[0].ds_addr==next_address);
    auto saved=map->dm_bounce_mem;size_t allocations=options.size();
    bus_dmamap_sync(0,map,0,2048,BUS_DMASYNC_PREWRITE);
    assert(saved->bytes==high.bytes);
    std::memset(saved->bytes.data()+100,0xa5,128);
    bus_dmamap_sync(0,map,100,128,BUS_DMASYNC_POSTREAD);
    assert(high.bytes[99]==0x5a && high.bytes[100]==0xa5 && high.bytes[227]==0xa5 && high.bytes[228]==0x5a);
    bus_dmamap_unload(0,map);
    assert(bus_dmamap_load(map,&high)==0 && options.size()==allocations && map->dm_bounce_mem==saved);
    high.length=4096;high.segments[0].length=4096;high.bytes.resize(4096);
    unsigned old_releases=releases,old_completes=completes;
    assert(bus_dmamap_load(map,&high)==0 && last_size==4096);
    assert(releases==old_releases+1 && completes==old_completes+1);
    Mbuf low{512,{{0x200000,256},{0x201000,256}},std::vector<uint8_t>(512)};
    allocations=options.size();
    assert(bus_dmamap_load(map,&low)==0 && !map->dm_bounce && map->dm_nsegs==2);
    assert(options.size()==allocations && map->dm_segs[1].ds_addr==0x201000);
    Mbuf edge{4096,{{0xfffff000ULL,4096}},std::vector<uint8_t>(4097)};
    assert(bus_dmamap_load(map,&edge)==0 && !map->dm_bounce);
    edge.length=4097;edge.segments[0].length=4097;
    assert(bus_dmamap_load(map,&edge)==0 && map->dm_bounce);
    bus_dmamap_destroy(0,map);assert(live==0);
    next_address=0xfffff000ULL;
    auto lastpage=alloc_dma_memory(4096,PAGE_SIZE);
    assert(lastpage);lastpage->complete();lastpage->release();
    assert(!alloc_dma_memory(4097,PAGE_SIZE));
    next_address=0x100000000ULL;assert(!alloc_dma_memory(4096,PAGE_SIZE));
    next_address=0x100001;assert(!alloc_dma_memory(4096,PAGE_SIZE));
    next_address=0;assert(!alloc_dma_memory(4096,PAGE_SIZE));
    next_address=0x100000;next_span=4095;assert(!alloc_dma_memory(4096,PAGE_SIZE));
    next_span=UINT64_MAX;fail_prepare=true;assert(!alloc_dma_memory(4096,PAGE_SIZE));
    fail_prepare=false;fail_alloc=true;
    auto failed=new_map();assert(bus_dmamap_load(failed,&high)==1 && !failed->dm_bounce_mem);
    fail_alloc=false;
    assert(bus_dmamap_load(nullptr,&high)==1 && bus_dmamap_load(failed,nullptr)==1);
    bus_dmamap_destroy(0,failed);assert(live==0);
    puts("PASS: mapping identity, inclusive 32-bit bounds, contiguity/alignment, cache reuse/growth, copies and failure cleanup. Hardware IOMMU validation remains separate.");
#endif
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--baseline-ref", help="Read an older implementation from Git into memory to reproduce the ring mapping defect")
    args = parser.parse_args()
    text = (args.source / "mtk80211/compat.cpp").read_text()
    if args.baseline_ref:
        text = subprocess.check_output(["git", "show", args.baseline_ref + ":mtk80211/compat.cpp"],
                                       cwd=args.source, text=True)
    header = (args.source / "mtk80211/compat.h").read_text()
    structs = re.search(r"typedef struct bus_dma_segment \{.*?\} bus_dma_segment_t;", header, re.S).group()
    structs += re.search(r"struct bus_dmamap \{.*?typedef struct bus_dmamap\* bus_dmamap_t;", header, re.S).group()
    prototypes = "void bus_dmamap_unload(bus_dma_tag_t,bus_dmamap_t);\n"
    code = PRELUDE + structs + prototypes + text[text.index("int bus_dmamap_create("):] + MAIN
    output = Path(os.environ.get("MTK_TEST_BUILD_DIR", args.source / "build/tests")) / "dma-allocation"
    output.mkdir(parents=True, exist_ok=True)
    binary = output / ("baseline" if args.baseline_ref else "test")
    flags = ["-DLEGACY=1"] if args.baseline_ref else []
    subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", *flags,
                    "-x", "c++", "-", "-o", str(binary)], input=code, text=True, check=True)
    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
