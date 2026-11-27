//
//  compat.cpp
//  SimpleMtkWlan
//
//  Created by laobamac (王孝慈) on 2026/4/15.
//  Copyright © 2026 laobamac (王孝慈). All rights reserved.
//

/*
* Copyright (C) 2020  钟先耀
*
* This program is free software; you can redistribute it and/or modify
* it under the terms of the GNU General Public License as published by
* the Free Software Foundation; either version 2 of the License, or
* (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU General Public License for more details.
*/
//
//  compat.cpp
//  net80211
//
//  Copyright (c) 2012 Prashant Vaibhav. All rights reserved.
//

#include <HAL/MtkPerf.hpp>
#include "compat.h"
#include <IOKit/IOLib.h>
#include <sys/random.h>
#include <sys/param.h>
#include <sys/proc.h>

OSDefineMetaClassAndStructors(pci_intr_handle, OSObject)

int pci_get_capability(pci_chipset_tag_t chipsettag, pcitag_t pcitag, int capid, int *offsetp, pcireg_t *valuep) {
	uint8_t offset;
	UInt32 value = pcitag->findPCICapability(capid, &offset);
	if (valuep)
		*valuep = (pcireg_t)value;
	if (offsetp)
		*offsetp = offset;
	if (value == 0)
		return 0;
	else
		return 1;
}

pcireg_t pci_conf_read(pci_chipset_tag_t pc, pcitag_t tag, int reg) {
	return tag->configRead32(reg);
}

void pci_conf_write(pci_chipset_tag_t pc, pcitag_t tag, int reg, pcireg_t val) {
	tag->configWrite32(reg, val);
}

pcireg_t pci_mapreg_type(pci_chipset_tag_t pc, pcitag_t tag, int reg) {
	return 0; // XXX this is not needed on OS X, will always be memorymap
}

int pci_mapreg_map(const struct pci_attach_args *pa, int reg, pcireg_t type, int busflags, bus_space_tag_t *tagp,
		   bus_space_handle_t *handlep, bus_addr_t *basep, bus_size_t *sizep, bus_size_t maxsize)
{	
	IOMemoryMap* map = pa->pa_tag->mapDeviceMemoryWithRegister(reg);
	if (map == 0)
		return kIOReturnError;
	
	*handlep = reinterpret_cast<caddr_t>(map->getVirtualAddress());
	
	if (tagp)
		*tagp = map;
	if (basep)
		*basep = map->getVirtualAddress();
	if (sizep)
		*sizep = map->getSize();
	
	return 0;
}

int
pci_intr_map_msix(struct pci_attach_args *pa, int vec, pci_intr_handle_t *ihp)
{
    pci_chipset_tag_t pc = pa->pa_pc;
    pcitag_t tag = pa->pa_tag;
    pcireg_t reg;

    KASSERT(PCI_MSIX_VEC(vec) == vec, "PCI_MSIX_VEC(vec) == vec");

    if (pci_get_capability(pc, tag, PCI_CAP_MSIX, NULL, &reg) == 0)
        return 1;

    if (vec > PCI_MSIX_MC_TBLSZ(reg))
        return 1;
    
    return pci_intr_map_msi(pa, ihp);
}

int pci_intr_map_msi(struct pci_attach_args *paa, pci_intr_handle_t *ih) {
	if (paa == 0 || ih == 0)
		return 1;
	
	*ih = new pci_intr_handle();
	
	if (*ih == 0)
		return 1;
	
	(*ih)->dev = paa->pa_tag;  // pci device reference
	
	(*ih)->workloop = paa->workloop;
	
	return 0; // XXX not required on OS X
}

int pci_intr_map(struct pci_attach_args *paa, pci_intr_handle_t *ih) {
	return pci_intr_map_msi(paa, ih);
}

void interruptTrampoline(OSObject *ih, IOInterruptEventSource *, int count);
void interruptTrampoline(OSObject *ih, IOInterruptEventSource *, int count) {
	pci_intr_handle* _ih = OSDynamicCast(pci_intr_handle, ih);
	if (_ih == 0)
		return;
	(void)_ih->func(_ih->arg); // jump to actual interrupt handler
}

void* pci_intr_establish(pci_chipset_tag_t pc, pci_intr_handle_t ih, int level, int (*handler)(void *), void *arg) {
	ih->arg = arg;
	ih->func = handler;
	/*
	 * Register the MSI vector when the device exposes one. Index 0 is the
	 * legacy INTx line, which the device stops asserting once MSI is enabled.
	 * Registering the PCIMessaged index lets IOPCIFamily program the MSI
	 * address/data and set the enable bit itself.
	 */
	int intIndex = 0;
	for (int index = 0; ; index++) {
		int interruptType;
		if (ih->dev->getInterruptType(index, &interruptType) != kIOReturnSuccess)
			break;
		if (interruptType & kIOInterruptTypePCIMessaged) {
			intIndex = index;
			break;
		}
	}
	ih->intr = IOInterruptEventSource::interruptEventSource(ih, &interruptTrampoline, ih->dev, intIndex);
	mtk_dbg_log("SimpleMtkWlan: interrupt source index=%d (%s)\n", intIndex,
	    intIndex ? "msi" : "intx");
	
	if (ih->intr == 0)
		return 0;
	if (ih->workloop->addEventSource(ih->intr) != kIOReturnSuccess)
		return 0;
	
	ih->intr->enable();
	return ih;
}

void* pci_intr_establish(pci_chipset_tag_t pc, pci_intr_handle_t ih, int level, int (*handler)(void *), void *arg, const char *name) {
	return pci_intr_establish(pc, ih, level, handler, arg);
}

void pci_intr_disestablish(pci_chipset_tag_t pc, void *ih) {
	pci_intr_handle_t intr = (pci_intr_handle_t) ih;
	
	if (intr->workloop && intr->intr)
		intr->workloop->removeEventSource(intr->intr);
	if (intr->intr)
		intr->intr->release();
	intr->intr = 0;
	
	intr->dev = 0;
	
	intr->workloop = 0;
	
	intr->arg = 0;
	intr->func = 0;
	intr->release();
	intr = 0;
	ih = 0;
}

const char *pci_intr_string(pci_chipset_tag_t pc, pci_intr_handle_t ih) {
	return "msi";
}

uint64_t bus_space_read_8(bus_space_tag_t space, bus_space_handle_t handle, bus_size_t offset) {
    return *((uint64_t*)(handle + offset));
}

void bus_space_write_8(bus_space_tag_t space, bus_space_handle_t handle, bus_size_t offset, uint64_t value) {
    *((uint64_t*)(handle + offset)) = value;
}

uint32_t bus_space_read_4(bus_space_tag_t space, bus_space_handle_t handle, bus_size_t offset) {
	return *((uint32_t*)(handle + offset));
}

void bus_space_write_1(bus_space_tag_t space, bus_space_handle_t handle, bus_size_t offset, uint8_t value) {
    *((uint8_t*)(handle + offset)) = value;
}

void bus_space_write_4(bus_space_tag_t space, bus_space_handle_t handle, bus_size_t offset, uint32_t value) {
	*((uint32_t*)(handle + offset)) = value;
}

void bus_space_barrier(bus_space_tag_t space, bus_space_handle_t handle, bus_size_t offset, bus_size_t length, int flags) {
	return; // In OSX device memory access is always uncached and serialized (afaik!)
}

void bus_space_unmap(bus_space_tag_t space, bus_space_handle_t handle, bus_size_t size) {
	if (space)
		space->release();
}

int bus_dmamap_create(bus_dma_tag_t tag, bus_size_t size, int nsegments, bus_size_t maxsegsz, bus_size_t boundary, int flags, bus_dmamap_t *dmamp) {
	if (dmamp == 0)
		return 1;
	*dmamp = new bus_dmamap;
	memset(*dmamp, 0, sizeof(**dmamp));
	(*dmamp)->dm_maxsize = size;
	(*dmamp)->cursor = IOMbufNaturalMemoryCursor::withSpecification(maxsegsz, nsegments);
	if ((*dmamp)->cursor == 0)
		return 1;
	else
		return 0;
}

static bool dma_range_fits32(uint64_t address, uint64_t length)
{
	return length != 0 && address <= UINT32_MAX &&
	    length - 1 <= UINT32_MAX - address;
}

IOBufferMemoryDescriptor* alloc_dma_memory(size_t size, mach_vm_address_t alignment, IOOptionBits opts = kIOMemoryPhysicallyContiguous | kIOMapInhibitCache)
{
	uint64_t phymask = 0x00000000ffffffffull & (~(alignment - 1));
	IOBufferMemoryDescriptor *mem = IOBufferMemoryDescriptor::inTaskWithPhysicalMask(
	    kernel_task, opts | kIODirectionInOut, size, phymask);
	if (!mem)
		return 0;

	if (mem->prepare() != kIOReturnSuccess) {
		mem->release();
		return 0;
	}
	// getPhysicalSegment uses the system mapper's IOVM address when enabled.
	// Rings and bounce buffers require one aligned, entirely 32-bit DMA range.
	IOByteCount length = 0;
	bus_addr_t address = mem->getPhysicalSegment(0, &length);
	if (!address || length < size || !dma_range_fits32(address, size) ||
	    (address & (alignment - 1))) {
		mem->complete();
		mem->release();
		return 0;
	}
	return mem;
}


int bus_dmamem_alloc(bus_dma_tag_t tag, bus_size_t size, bus_size_t alignment, bus_size_t boundary, bus_dma_segment_t *segs, int nsegs, int *rsegs, int flags) {
	// Ignore flags and don't pass in the number of segments, it's not used in the driver (always 1 anyway)
	if (segs == 0)
		return 1;
	memset(segs, 0, sizeof(*segs));
	segs->buf = alloc_dma_memory(size, alignment);
	if (segs->buf == 0)
		return 1;
	segs->ds_addr = segs->buf->getPhysicalAddress();
	segs->ds_len = size;
	if (rsegs)
		*rsegs = 1;
	return 0;
}

/*
 * Cacheable variant of bus_dmamem_alloc(), for memory the CPU writes and
 * reads on the hot path: ring descriptors and TXWI. Reuses alloc_dma_memory()
 * so the 32-bit range, alignment and single-segment checks stay in one place.
 * Only x86_64 is switched over: on Apple silicon the descriptor writes are
 * already ordered and cached by the mapping the firmware expects.
 */
int bus_dmamem_alloc_cached(bus_dma_tag_t tag, bus_size_t size,
    bus_size_t alignment, bus_dma_segment_t *segs, int *rsegs) {
	if (segs == 0)
		return 1;
	memset(segs, 0, sizeof(*segs));
#if defined(__x86_64__)
	/* kIOMemoryPhysicallyContiguous without kIOMapInhibitCache: CPU-cached. */
	segs->buf = alloc_dma_memory(size, alignment, kIOMemoryPhysicallyContiguous);
#else
	segs->buf = alloc_dma_memory(size, alignment);
#endif
	if (segs->buf == 0)
		return 1;
	segs->ds_addr = segs->buf->getPhysicalAddress();
	segs->ds_len = size;
	if (rsegs)
		*rsegs = 1;
	return 0;
}

int bus_dmamem_map(bus_dma_tag_t tag, bus_dma_segment_t *segs, int nsegs, size_t size, void **kvap, int flags) {
	// ignore flags, the memory is already mapped as one segment by the call to bus_dmamem_alloc so just return the virtual address
	if (segs == 0 || segs->buf == 0 || kvap == 0)
		return 1;
	*kvap = segs->buf->getBytesNoCopy();
	return 0;
}

bus_addr_t bus_dmamap_get_paddr(bus_dma_segment_t seg) {
	if (seg.buf == 0)
		return 0;
	else
		return seg.ds_addr;
}

void bus_dmamap_sync(bus_dma_tag_t tag, bus_dmamap_t dmam, bus_addr_t offset, bus_size_t len, int ops) {
	/*
	 * Rings and TXWI are CPU-cacheable now, so ownership transitions need an
	 * explicit ordering point even for direct maps (no bounce copy): complete
	 * host writes before the doorbell, and let the CPU see device writes
	 * before reading them.
	 */
	if (ops & (BUS_DMASYNC_PREREAD | BUS_DMASYNC_POSTREAD))
		__sync_synchronize();
	if ((ops & (BUS_DMASYNC_PREWRITE | BUS_DMASYNC_POSTREAD)) == 0) {
		if (ops & BUS_DMASYNC_POSTWRITE)
			__sync_synchronize();
		return;
	}
	if (dmam == 0 || !dmam->dm_bounce || dmam->dm_bounce_mem == 0 ||
	    dmam->dm_mbuf == 0)
		return;

	void *bounce = dmam->dm_bounce_mem->getBytesNoCopy();
	if (bounce == 0)
		return;

	size_t copy_len = len;
	if (offset > dmam->dm_mapsize)
		return;
	if (copy_len > dmam->dm_mapsize - offset)
		copy_len = dmam->dm_mapsize - offset;
	if (copy_len == 0)
		return;

	if (ops & BUS_DMASYNC_PREWRITE) {
#if MTK_PERF
		mp_add(mp_bounce_tx_calls);
		mp_add(mp_bounce_tx_bytes, copy_len);
#endif
		mbuf_copydata(dmam->dm_mbuf, offset, copy_len,
		    (uint8_t *)bounce + offset);
		/* Publish the copied frame before the caller rings the doorbell. */
		__sync_synchronize();
	}
	if (ops & BUS_DMASYNC_POSTREAD) {
#if MTK_PERF
		mp_add(mp_bounce_rx_calls);
		mp_add(mp_bounce_rx_bytes, copy_len);
		MpTimer perf(mp_rx_bounce_sample_samples,
		    (mp_values[mp_bounce_rx_calls] % MP_BOUNCE_SAMPLE_PERIOD) == 0);
#endif
		mbuf_copyback(dmam->dm_mbuf, offset, copy_len,
		    (uint8_t *)bounce + offset, MBUF_DONTWAIT);
		mbuf_inbound_modified(dmam->dm_mbuf);
	}
}

void bus_dmamem_unmap(bus_dma_segment_t seg) {
	if (seg.buf == 0)
		return;
	seg.buf->complete();
}

void bus_dmamem_unmap(bus_dma_tag_t tag, void *kva, size_t size) {
	return;
}

void bus_dmamem_free(bus_dma_tag_t tag, bus_dma_segment_t *segs, int nsegs) {
	if (segs == 0)
		return;
	if (segs->buf == 0)
		return;
	segs->buf->complete();
	segs->buf->release();
	memset(segs, 0, sizeof(*segs));
}

void bus_dmamap_destroy(bus_dma_tag_t tag, bus_dmamap_t dmam) {
	if (dmam == 0)
		return;
	if (dmam->mem) {
		dmam->mem->complete();
		dmam->mem->release();
	}
	dmam->mem = 0;
	if (dmam->dm_bounce_mem) {
		dmam->dm_bounce_mem->complete();
		dmam->dm_bounce_mem->release();
	}
	dmam->dm_bounce_mem = 0;
	if (dmam->cursor)
		dmam->cursor->release();
	dmam->cursor = 0;
	delete dmam;
}

int bus_dmamap_load(bus_dmamap_t map, mbuf_t mb) {
	if (map == 0 || mb == 0)
		return 1;
	IOPhysicalSegment segs[23];
	if (map->mem) {
		map->mem->complete();
		map->mem->release();
		map->mem = 0;
	}
	map->dm_mbuf = mb;
	map->dm_bounce = false;
	map->dm_nsegs = map->cursor->getPhysicalSegmentsWithCoalesce(mb, segs, 0);
	if (map->dm_nsegs == 0)
		return 1;
	size_t pktlen = mbuf_pkthdr_len(mb);
	if (pktlen > UINT32_MAX)
		return 1;
	map->dm_mapsize = (bus_size_t)pktlen;
	bool needs_bounce = false;
	for (int i = 0; i < map->dm_nsegs; i++) {
		if (!dma_range_fits32(segs[i].location, segs[i].length)) {
			needs_bounce = true;
			break;
		}
	}
	if (needs_bounce) {
		static uint32_t bounce_log_count;
		bus_size_t bounce_size = map->dm_maxsize;
		if (bounce_size == 0 || bounce_size < pktlen)
			bounce_size = (bus_size_t)pktlen;
		if (map->dm_bounce_mem == 0 ||
		    map->dm_bounce_size < bounce_size) {
			if (map->dm_bounce_mem != 0) {
				map->dm_bounce_mem->complete();
				map->dm_bounce_mem->release();
				map->dm_bounce_mem = 0;
				map->dm_bounce_size = 0;
			}
			// Data bounce allocation follows YYavicWiFi@7cf5b938841505e1e7c8e92888784927ff79e862,
			// Source/YYavicMtkWlan/mtk80211/compat.cpp (GPL-3.0-or-later).
			// Use coherent caching for x86_64 PCIe DMA, retaining contiguous memory and 32-bit addresses.
			IOBufferMemoryDescriptor *mem =
			    alloc_dma_memory(bounce_size, PAGE_SIZE, kIOMemoryPhysicallyContiguous);
			if (mem == 0)
				return 1;
			map->dm_bounce_mem = mem;
			map->dm_bounce_size = bounce_size;
		}
		bus_addr_t addr = map->dm_bounce_mem->getPhysicalAddress();
		if (!dma_range_fits32(addr, pktlen)) {
			return 1;
		}
		map->dm_bounce = true;
		map->dm_nsegs = 1;
		map->dm_segs[0].buf = NULL;
		map->dm_segs[0].ds_addr = addr;
		map->dm_segs[0].ds_len = (bus_size_t)pktlen;
		if (bounce_log_count < 16) {
			IOLog("SimpleMtkWlan-dma: bounce mbuf map len=%zu bounce_size=%u dma=0x%llx\n",
			    pktlen, map->dm_bounce_size, (unsigned long long)addr);
			bounce_log_count++;
		}
		return 0;
	}
	for (int i = 0; i < map->dm_nsegs; i++) {
		map->dm_segs[i].buf = NULL;
		map->dm_segs[i].ds_addr = segs[i].location;
		map->dm_segs[i].ds_len = (bus_size_t)segs[i].length;
	}
	return 0;
}

int bus_dmamap_load(bus_dma_tag_t tag, bus_dmamap_t map, bus_dma_segment_t *seg, int flags) {
	if (map == 0 || seg == 0 || seg->buf == 0)
		return 1;
	bus_dmamap_unload(tag, map);
	// Preserve the allocation's contiguous 32-bit mapping. Rewrapping its virtual
	// address with withAddress() creates an independent mapping without that limit.
	IOMemoryDescriptor *mem = seg->buf;
	if (mem->prepare() != kIOReturnSuccess)
		return 1;
	mem->retain();
	map->mem = mem;
	map->dm_segs[0].buf = NULL;
	map->dm_segs[0].ds_addr = seg->ds_addr;
	map->dm_segs[0].ds_len = seg->ds_len;
	map->dm_nsegs = 1;
	map->dm_mapsize = seg->ds_len;
	return 0;
}

int bus_dmamap_load_mbuf(bus_dma_tag_t tag, bus_dmamap_t map, mbuf_t m, int flags) {
	return bus_dmamap_load(map, m);
}

void bus_dmamap_unload(bus_dma_tag_t tag, bus_dmamap_t map) {
	if (map == 0)
		return;
	if (map->mem) {
		map->mem->complete();
		map->mem->release();
		map->mem = 0;
	}
	map->dm_mbuf = 0;
	map->dm_bounce = false;
	map->dm_nsegs = 0;
	map->dm_mapsize = 0;
}
