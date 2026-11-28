#!/usr/bin/env python3
"""Host ASan/UBSan tests for the raw data RX ring.

The data ring optionally owns one contiguous preallocated block instead of
one mbuf per slot (mq_raw): descriptors point at fixed addresses inside the
block, records that span slots are carried across drain calls via
mq_partial, and a reset must drop any carried record.
"""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
mwx_src = (root / "SimpleMtkWlan/hal_mwx/MtkMwx.cpp").read_text()

def extract_fn(src: str, sig: str) -> str:
    idx = src.index(sig)
    start = src.rfind("\n\n", 0, idx)
    start = 0 if start == -1 else start + 2
    end = src.index("\n}\n", idx) + 3
    return src[start:end]

fn_buf_fill = extract_fn(mwx_src, "mwx_buf_fill(struct mwx_softc *sc, struct mwx_queue *q,")
fn_rx_deq = extract_fn(mwx_src, "mwx_dma_rx_dequeue(struct mwx_softc *sc, struct mwx_queue *q,")
fn_reset = extract_fn(mwx_src, "mwx_queue_reset(struct mwx_softc *sc, struct mwx_queue *q)\n{")

harness = r'''
#define TEST_HARNESS 1
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#define __packed __attribute__((packed))
#define DEVNAME(sc) "mwx0"
#define MWX_DEV_LOG(...) ((void)0)
#define KASSERT(x) assert(x)
#define htole16(x) (x)
#define htole32(x) (x)
#define le32toh(x) (x)

#define MT_DMA_CTL_DMA_DONE 0x80000000U
#define MT_DMA_CTL_LAST_SEC0 0x40000000U
#define MT_DMA_CTL_SD_LEN0(l) (((uint32_t)(l) & 0x3fffU) << 16)
#define MT_DNA_CTL_SD_GET_LEN0(c) (((c) >> 16) & 0x3fffU)
#define MT_DMA_DESC_BASE 0x00
#define MT_DMA_RING_SIZE 0x04
#define MT_DMA_CPU_IDX 0x08
#define MT_DMA_DMA_IDX 0x0c
#define BUS_DMASYNC_PREREAD 0
#define BUS_DMASYNC_POSTREAD 1
#define BUS_DMASYNC_PREWRITE 2
#define BUS_DMASYNC_POSTWRITE 3
#define BUS_DMA_READ 0
#define BUS_DMA_NOWAIT 0
#define MT_RX_BUF_SIZE 2048
#define M_DONTWAIT 0
#define MWX_RX_RECORD_MAX 16384
typedef uint8_t UInt8;
typedef uint16_t UInt16;
typedef uint32_t UInt32;
typedef unsigned long long bus_addr_t;
typedef size_t bus_size_t;
typedef unsigned int u_int32_t;

struct mbuf { uint32_t len = 0; uint32_t pktlen = 0; mbuf *next = nullptr; uint8_t data[9000] = {}; };
struct mbuf_list { std::vector<mbuf*> items; };
#define mtod(m, t) (reinterpret_cast<t>((m)->data))
static int g_frees = 0;
static inline void m_freem(mbuf *m) { while (m) { mbuf *n = m->next; delete m; g_frees++; m = n; } }
static inline void mbuf_setlen(mbuf *m, int l) { m->len = l; }
static inline uint32_t mbuf_len(mbuf *m) { return m->len; }
static inline void mbuf_pkthdr_setlen(mbuf *m, int l) { m->pktlen = l; }
static inline uint32_t mbuf_pkthdr_len(mbuf *m) { return m->pktlen; }
static inline void mbuf_setnext(mbuf *m, mbuf *n) { m->next = n; }
static inline bool ml_empty(const mbuf_list *ml) { return ml->items.empty(); }
static inline void ml_enqueue(mbuf_list *ml, mbuf *m) { ml->items.push_back(m); }

static bool g_alloc_fail = false;
static int mbuf_allocpacket(int, size_t, u_int32_t *, mbuf **out) {
    if (g_alloc_fail) return 1;
    *out = new mbuf();
    return 0;
}

struct dmamap_t {
    size_t dm_mapsize = 8192;
    unsigned dm_nsegs = 1;
    struct { bus_addr_t ds_addr; size_t ds_len; } dm_segs[2] = {};
};
static inline void bus_dmamap_sync(void *, dmamap_t *, size_t, size_t, int) {}
static inline void bus_dmamap_unload(void *, dmamap_t *) {}
static inline int bus_dmamap_load_mbuf(void *, dmamap_t *map, mbuf *m, int) {
    map->dm_segs[0].ds_addr = 0x1000;
    map->dm_segs[0].ds_len = m->len;
    return 0;
}
static inline mbuf *MCLGETL(void *, int, int) { return new mbuf(); }

struct mwx_txwi { int dummy; };
struct mwx_softc { void *sc_dmat = nullptr; };
static inline void mwx_txwi_put(mwx_softc *, mwx_txwi *) {}
static int g_resets = 0;
static inline void mwx_reset(mwx_softc *) { g_resets++; }

struct mwx_queue_data { mbuf *md_mbuf = nullptr; mwx_txwi *md_txwi = nullptr; dmamap_t *md_map = nullptr;
    bus_addr_t md_paddr = 0; void *md_va = nullptr; };
struct mwx_desc { uint32_t buf0 = 0, ctrl = 0, buf1 = 0, info = 0; };
struct mwx_queue {
    uint32_t mq_regbase = 0;
    unsigned mq_count = 0;
    unsigned mq_prod = 0;
    unsigned mq_cons = 0;
    mwx_desc *mq_desc = nullptr;
    mwx_queue_data *mq_data = nullptr;
    dmamap_t *mq_map = nullptr;
    int mq_raw = 0;
    unsigned mq_buf_size = 2048;
    mbuf *mq_partial = nullptr, *mq_partial_tail = nullptr;
    bool mq_partial_discard = false;
    int mq_wakeme = 0;
    unsigned int mq_cleanup_state = 0;
};

static unsigned g_dma_idx = 0;
static inline uint32_t mwx_read(mwx_softc *, uint32_t addr) {
    return (addr & 0xff) == MT_DMA_DMA_IDX ? g_dma_idx : 0;
}
static inline void mwx_write(mwx_softc *, uint32_t, uint32_t) {}

static const unsigned SLOT = 8192;
static uint8_t slotmem[16 * SLOT];

static void setup_raw_q(mwx_queue &q, int count) {
    static dmamap_t qmap;
    q = mwx_queue{};
    q.mq_count = count;
    q.mq_regbase = 0x100;
    q.mq_map = &qmap;
    q.mq_raw = 1;
    q.mq_buf_size = SLOT;
    q.mq_data = new mwx_queue_data[count]();
    q.mq_desc = new mwx_desc[count]();
    for (int i = 0; i < count; i++) {
        q.mq_data[i].md_paddr = 0x40000000ULL + (bus_addr_t)i * SLOT;
        q.mq_data[i].md_va = slotmem + (size_t)i * SLOT;
    }
}
static void put_seg(mwx_queue &q, int i, uint32_t len, bool last) {
    q.mq_desc[i].ctrl = MT_DMA_CTL_DMA_DONE | MT_DMA_CTL_SD_LEN0(len) |
        (last ? MT_DMA_CTL_LAST_SEC0 : 0);
}
static void fill_mem(int slot, uint32_t len, uint8_t seed) {
    for (uint32_t k = 0; k < len; k++)
        slotmem[(size_t)slot * SLOT + k] = (uint8_t)(seed + k);
}
static void free_q(mwx_queue &q) { delete[] q.mq_data; delete[] q.mq_desc; }
'''

tests = r'''
static void test_buf_fill_raw_descriptor() {
    mwx_softc sc{};
    mwx_queue q{};
    q.mq_raw = 1;
    q.mq_buf_size = SLOT;
    mwx_queue_data md{};
    md.md_paddr = 0x40000000ULL;
    md.md_va = slotmem;
    mwx_desc d{};
    assert(mwx_buf_fill(&sc, &q, &md, &d) == 0);
    assert(d.buf0 == htole32(0x40000000U));
    assert(d.buf1 == 0 && d.info == 0);
    assert(d.ctrl == htole32(MT_DMA_CTL_SD_LEN0(SLOT) | MT_DMA_CTL_LAST_SEC0));
    assert(md.md_mbuf == nullptr);
}

static void test_single_slot_record() {
    mwx_softc sc{};
    mwx_queue q{};
    setup_raw_q(q, 4);
    fill_mem(0, 1500, 7);
    put_seg(q, 0, 1500, true);
    g_dma_idx = 1;
    mbuf_list received{};
    bool more = true;
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, &more);
    assert(received.items.size() == 1);
    mbuf *m = received.items.front();
    assert(mbuf_pkthdr_len(m) == 1500 && m->len == 1500);
    assert(m->next == nullptr);
    assert(m->data[0] == 7 && m->data[1499] == (uint8_t)(7 + 1499));
    assert(q.mq_cons == 1 && more == false);
    assert(q.mq_partial == nullptr);
    m_freem(m);
    free_q(q);
}

static void test_two_slots_one_drain() {
    mwx_softc sc{};
    mwx_queue q{};
    setup_raw_q(q, 4);
    fill_mem(0, 8000, 1);
    fill_mem(1, 500, 100);
    put_seg(q, 0, 8000, false);
    put_seg(q, 1, 500, true);
    g_dma_idx = 2;
    mbuf_list received{};
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.size() == 1);
    mbuf *m = received.items.front();
    assert(mbuf_pkthdr_len(m) == 8500);
    assert(m->len == 8000 && m->next != nullptr && m->next->len == 500);
    assert(m->data[0] == 1 && m->data[7999] == (uint8_t)(1 + 7999));
    assert(m->next->data[0] == 100 && m->next->data[499] == (uint8_t)(100 + 499));
    assert(q.mq_cons == 2 && q.mq_partial == nullptr);
    m_freem(m);
    free_q(q);
}

static void test_record_spans_drains() {
    mwx_softc sc{};
    mwx_queue q{};
    setup_raw_q(q, 4);
    fill_mem(0, 8000, 1);
    fill_mem(1, 500, 100);
    put_seg(q, 0, 8000, false);
    put_seg(q, 1, 500, true);
    mbuf_list received{};
    // First drain sees only slot 0: the half record is carried, nothing enqueued.
    g_dma_idx = 1;
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.empty());
    assert(q.mq_cons == 1);
    assert(q.mq_partial != nullptr && q.mq_partial->len == 8000);
    assert(q.mq_partial_tail == q.mq_partial);
    // Second drain completes the record from the carried state.
    g_dma_idx = 2;
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.size() == 1);
    mbuf *m = received.items.front();
    assert(mbuf_pkthdr_len(m) == 8500);
    assert(m->len == 8000 && m->next != nullptr && m->next->len == 500);
    assert(m->next->data[0] == 100);
    assert(q.mq_partial == nullptr && q.mq_cons == 2);
    m_freem(m);
    free_q(q);
}

static void test_record_max_discard() {
    mwx_softc sc{};
    mwx_queue q{};
    setup_raw_q(q, 8);
    fill_mem(0, SLOT, 1);
    fill_mem(1, SLOT, 2);
    fill_mem(2, 100, 3);
    put_seg(q, 0, SLOT, false);
    put_seg(q, 1, SLOT, false);
    put_seg(q, 2, 100, true);
    g_dma_idx = 3;
    mbuf_list received{};
    // 8192 + 8192 = 16384 fits; +100 crosses MWX_RX_RECORD_MAX: the whole
    // record is dropped as one unit, nothing is enqueued.
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.empty());
    assert(q.mq_cons == 3);
    assert(q.mq_partial == nullptr && q.mq_partial_discard == false);
    // The next record after the runaway is delivered normally.
    fill_mem(3, 300, 40);
    put_seg(q, 3, 300, true);
    g_dma_idx = 4;
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.size() == 1);
    assert(mbuf_pkthdr_len(received.items.front()) == 300);
    m_freem(received.items.front());
    free_q(q);
}

static void test_bad_len_slot_skipped() {
    mwx_softc sc{};
    mwx_queue q{};
    setup_raw_q(q, 8);
    fill_mem(0, 300, 5);
    put_seg(q, 0, 300, false);
    put_seg(q, 1, 9000, false);   // 9000 > mq_buf_size: invalid
    g_dma_idx = 2;
    mbuf_list received{};
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.empty());
    // The bad slot is skipped, not retried forever, and the carried
    // half record is dropped with it.
    assert(q.mq_cons == 2);
    assert(q.mq_partial == nullptr);
    // The ring keeps flowing afterwards.
    fill_mem(2, 400, 21);
    put_seg(q, 2, 400, true);
    g_dma_idx = 3;
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.size() == 1);
    assert(mbuf_pkthdr_len(received.items.front()) == 400);
    m_freem(received.items.front());
    free_q(q);
}

static void test_alloc_failure_keeps_descriptor() {
    mwx_softc sc{};
    mwx_queue q{};
    setup_raw_q(q, 4);
    fill_mem(0, 300, 5);
    fill_mem(1, 500, 50);
    put_seg(q, 0, 300, false);
    put_seg(q, 1, 500, true);
    mbuf_list received{};
    // Slot 0 alone: a half record is carried.
    g_dma_idx = 1;
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.empty());
    assert(q.mq_cons == 1);
    assert(q.mq_partial != nullptr && q.mq_partial->len == 300);
    // Allocation fails for the completing segment: the descriptor stays
    // ours (mq_cons not advanced) and the record waits for the next drain.
    g_alloc_fail = true;
    g_dma_idx = 2;
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.empty());
    assert(q.mq_cons == 1);
    assert(q.mq_partial != nullptr && q.mq_partial->len == 300);
    // Retry with allocation working completes the record.
    g_alloc_fail = false;
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.size() == 1);
    assert(mbuf_pkthdr_len(received.items.front()) == 800);
    assert(q.mq_partial == nullptr && q.mq_cons == 2);
    m_freem(received.items.front());
    free_q(q);
}

static void test_reset_drops_carried_record() {
    mwx_softc sc{};
    mwx_queue q{};
    setup_raw_q(q, 4);
    fill_mem(0, 300, 5);
    put_seg(q, 0, 300, false);
    g_dma_idx = 1;
    mbuf_list received{};
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(q.mq_partial != nullptr);
    int before = g_frees;
    mwx_queue_reset(&sc, &q);
    assert(q.mq_partial == nullptr && q.mq_partial_discard == false);
    assert(g_frees == before + 1);
    assert(q.mq_cons == 0 && q.mq_prod == 0);
    // The reset ring still receives frames.
    fill_mem(0, 200, 31);
    put_seg(q, 0, 200, true);
    g_dma_idx = 1;
    mwx_dma_rx_dequeue(&sc, &q, &received, 8, nullptr);
    assert(received.items.size() == 1);
    assert(mbuf_pkthdr_len(received.items.front()) == 200);
    m_freem(received.items.front());
    free_q(q);
}

int main() {
    test_buf_fill_raw_descriptor();
    test_single_slot_record();
    test_two_slots_one_drain();
    test_record_spans_drains();
    test_record_max_discard();
    test_bad_len_slot_skipped();
    test_alloc_failure_keeps_descriptor();
    test_reset_drops_carried_record();
    puts("PASS raw RX ring: descriptor format, slot spanning (same/next drain), record-max discard, bad-slot skip, alloc-failure retry, reset drop");
    return 0;
}
'''

out = Path(__file__).resolve().parent
cpp = out / "test-rx-raw-ring.cpp"
exe = out / "test-rx-raw-ring"
cpp.write_text("\n".join([harness, fn_buf_fill, fn_rx_deq, fn_reset, tests]))
subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", str(cpp), "-o", str(exe)], check=True)
subprocess.run([str(exe)], check=True)
