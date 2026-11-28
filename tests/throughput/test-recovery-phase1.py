#!/usr/bin/env python3
"""Host ASan/UBSan tests for Phase 1 CAS TX cleanup, RX segment bounds, deaf-RX, and SER/DMA watchdog recovery."""
from pathlib import Path
import subprocess, tempfile

root = Path(__file__).resolve().parents[2]
mwx = (root / "SimpleMtkWlan/hal_mwx/MtkMwx.cpp").read_text()

def extract_fn(sig: str) -> str:
    idx = mwx.index(sig)
    start = mwx.rfind("\n\n", 0, idx)
    start = 0 if start == -1 else start + 2
    end = mwx.index("\n}\n", idx) + 3
    return mwx[start:end]

fn_cleanup = extract_fn("mwx_dma_tx_cleanup(struct mwx_softc *sc, struct mwx_queue *q)\n{")
fn_rx_deq = extract_fn("mwx_dma_rx_dequeue(struct mwx_softc *sc, struct mwx_queue *q,")
fn_req_rst = extract_fn("mwx_request_fullreset(struct mwx_softc *sc, const char *reason,")
fn_deaf = extract_fn("mwx_scan_check_rx_deaf(struct mwx_softc *sc, uint32_t complete_ch,")
fn_timeo = extract_fn("mwx_dma_timeo(void *arg)\n{")

harness = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#define BUS_DMASYNC_PREREAD 0
#define BUS_DMASYNC_POSTREAD 1
#define BUS_DMASYNC_PREWRITE 2
#define BUS_DMASYNC_POSTWRITE 3
#define IFF_RUNNING 0x40
#define MWX_KNOB_AUTORESET 0x04
#define MWX_FULLRESET_DMA_DISABLED 1
#define MWX_FULLRESET_SER 2
#define MWX_FULLRESET_DEAF_RX 3
#define MT_DMA_DMA_IDX 0x0c
#define MT_DMA_CTL_DMA_DONE 0x80000000U
#define MT_DMA_CTL_LAST_SEC0 0x40000000U
#define MT_DMA_CTL_SD_LEN0(l) (((uint32_t)(l) & 0x3fffU) << 16)
#define MT_DNA_CTL_SD_GET_LEN0(c) (((c) >> 16) & 0x3fffU)
#define MT_WFDMA0_GLO_CFG 0xd4208
#define MT_WFDMA0_GLO_CFG_TX_DMA_EN 1
#define MT_WFDMA0_GLO_CFG_RX_DMA_EN 4
#define MT_WFDMA0_HOST_INT_STA 0xd4200
#define MT_WFDMA0_HOST_INT_ENA 0xd4204
#define MT_CONN_ON_LPCTL 0x7c060010
#define MT_CONN_ON_MISC 0x7c0600f0
#define MT_MCU_CMD 0xd5000
#define MT_MCU_CMD_STOP_DMA 0x04
#define MT_MCU_CMD_STOP_DMA_FW_RELOAD 0x02
#define KASSERT(x) assert(x)
#define MWX_DEV_LOG(...) ((void)0)
#define htole32(x) (x)
#define le32toh(x) (x)
#define ifnet _ifnet

#define mtod(m, t) (reinterpret_cast<t>((m)->data))

struct mbuf { size_t len = 0, pktlen = 0; mbuf *next = nullptr; uint8_t data[9000] = {}; };
struct mbuf_list { std::vector<mbuf*> items; };
static void m_freem(mbuf *m) { while (m) { auto *n = m->next; delete m; m = n; } }
static void mbuf_setlen(mbuf *m, int l) { m->len = l; }
static uint32_t mbuf_len(mbuf *m) { return m->len; }
static void mbuf_pkthdr_setlen(mbuf *m, int l) { m->pktlen = l; }
static uint32_t mbuf_pkthdr_len(mbuf *m) { return m->pktlen; }
static void mbuf_setnext(mbuf *m, mbuf *n) { m->next = n; }
static void ml_enqueue(mbuf_list *ml, mbuf *m) { ml->items.push_back(m); }

struct dmamap_t { size_t dm_mapsize = 4096; };
struct mwx_queue_data { mbuf *md_mbuf = nullptr; void *md_txwi = nullptr; dmamap_t *md_map = nullptr;
    unsigned long long md_paddr = 0; void *md_va = nullptr; };
struct mwx_desc { uint32_t buf0 = 0, buf1 = 0, info = 0, ctrl = 0; };
struct mwx_queue {
    uint32_t mq_regbase = 0;
    unsigned mq_count = 8;
    unsigned mq_prod = 0;
    unsigned mq_cons = 0;
    mwx_desc *mq_desc = nullptr;
    mwx_queue_data *mq_data = nullptr;
    dmamap_t *mq_map = nullptr;
    int mq_wakeme = 0;
    unsigned int mq_cleanup_state = 0;
    int mq_raw = 0;
    unsigned mq_buf_size = 2048;
    mbuf *mq_partial = nullptr, *mq_partial_tail = nullptr;
    bool mq_partial_discard = false;
};
#define MWX_RX_RECORD_MAX 16384
#define M_DONTWAIT 0
static int mbuf_allocpacket(int, size_t, unsigned int *, mbuf **) { return 1; }
struct _ifnet { void *if_softc = nullptr; uint32_t if_flags = IFF_RUNNING; };
struct ieee80211com { _ifnet ic_if; };
struct mwx_softc {
    ieee80211com sc_ic;
    void *sc_dmat = nullptr;
    void *sc_nswq = (void*)1;
    void *sc_memh = (void*)1;
    void *sc_dma_to = nullptr;
    int sc_fullreset_task = 0;
    uint32_t sc_knobs = MWX_KNOB_AUTORESET;
    int8_t sc_resetting = 0;
    bool sc_detaching = false;
    volatile int8_t sc_suspended = 0;
    volatile int8_t sc_sys_suspended = 0;
    uint64_t sc_fullreset_last_at_us = 0;
    uint32_t sc_fullreset_last_reason = 0;
    uint32_t sc_dma_stalls = 0;
    int sc_dma_stall_logged = 0;
    uint32_t sc_ser_events = 0;
    uint32_t sc_rx_irq_rescues = 0;
    uint32_t sc_rx_deaf_resets = 0;
    uint32_t sc_rx_deaf_scans = 0;
    uint32_t sc_rx_deaf_channels = 0;
    uint32_t sc_rx_deaf_mdrdy = 0;
    uint32_t sc_rx_deaf_baseline = 0;
    uint32_t sc_scan_start_rx = 0;
    uint32_t sc_rx_pkt_normal = 0;
    uint32_t sc_rx_pkt_normal_mcu = 0;
    uint32_t sc_last_mcu_cmd = 0;
    mwx_queue sc_rxq, sc_rxmcuq, sc_rxfwdlq;
};

static uint64_t g_now_us = 1000000ULL;
static uint32_t g_glo = 5;
static uint32_t g_mcu_cmd = 0;
static int g_fullreset_tasks = 0, g_dma_to_rearms = 0, g_rx_done_calls = 0, g_tx_done_calls = 0, g_mwx_resets = 0;
static uint32_t g_dma_idx = 0;
static std::vector<uint32_t> g_dma_idx_seq;

static uint64_t mwx_now_us(void) { return g_now_us; }
static void wakeup(void *) {}
static void bus_dmamap_sync(void *, dmamap_t *, int, size_t, int) {}
static void bus_dmamap_unload(void *, dmamap_t *) {}
static void task_add(void *, int *) { g_fullreset_tasks++; }
static void timeout_add_sec(void **, int) { g_dma_to_rearms++; }
static void mwx_reset(mwx_softc *) { g_mwx_resets++; }
static void mwx_scan_reset_rx_deaf(mwx_softc *sc) {
    sc->sc_rx_deaf_scans = sc->sc_rx_deaf_channels = sc->sc_rx_deaf_mdrdy = sc->sc_rx_deaf_baseline = 0;
}
static bool mwx_dma_rx_done(mwx_softc *, mwx_queue *) { g_rx_done_calls++; return false; }
static void mwx_dma_tx_done(mwx_softc *) { g_tx_done_calls++; }
static void mwx_dump_dma_state(mwx_softc *, const char *) {}
static uint32_t mwx_read(mwx_softc *sc, uint32_t reg) {
    if (reg == MT_WFDMA0_GLO_CFG) return g_glo;
    if (reg == MT_MCU_CMD) return g_mcu_cmd;
    if (reg == sc->sc_rxq.mq_regbase + MT_DMA_DMA_IDX) {
        if (!g_dma_idx_seq.empty()) { uint32_t v = g_dma_idx_seq.front(); g_dma_idx_seq.erase(g_dma_idx_seq.begin()); return v; }
        return g_dma_idx;
    }
    return 0;
}
static void mwx_write(mwx_softc *, uint32_t reg, uint32_t val) { if (reg == MT_MCU_CMD) g_mcu_cmd &= ~val; }
static bool mwx_dma_rx_pending(mwx_softc *sc, mwx_queue *q) {
    if (!q->mq_count || !q->mq_desc || !q->mq_data) return false;
    uint32_t hw = mwx_read(sc, q->mq_regbase + MT_DMA_DMA_IDX);
    return hw < q->mq_count && hw != q->mq_cons;
}
''' + "\n" + fn_cleanup + "\n" + fn_rx_deq + "\n" + fn_req_rst + "\n" + fn_deaf + "\n" + fn_timeo + r'''
int main() {
    // 1. 3-state CAS TX cleanup avoids nested corruption and handles out-of-range DMA_IDX
    {
        mwx_softc sc = {};
        dmamap_t qmap{4096}, dmap{4096};
        mwx_desc desc[8] = {};
        mwx_queue_data qdata[8] = {};
        for (int i = 0; i < 8; i++) qdata[i].md_map = &dmap;
        qdata[0].md_mbuf = new mbuf;
        qdata[1].md_mbuf = new mbuf;
        mwx_queue q{0x100, 8, 2, 0, desc, qdata, &qmap, 0, 0};
        q.mq_regbase = 0x100;
        sc.sc_rxq.mq_regbase = 0x100;
        g_dma_idx = 2;
        mwx_dma_tx_cleanup(&sc, &q);
        assert(q.mq_cons == 2 && q.mq_cleanup_state == 0 && !qdata[0].md_mbuf && !qdata[1].md_mbuf);

        // Concurrent caller transitions RUNNING -> PENDING without modifying cons
        q.mq_cleanup_state = 1;
        mwx_dma_tx_cleanup(&sc, &q);
        assert(q.mq_cleanup_state == 2);

        // Hardware reads all-ones DMA_IDX (device gone): safely resets cleanup_state to IDLE
        q.mq_cleanup_state = 0;
        g_dma_idx = 0xffffffffU;
        mwx_dma_tx_cleanup(&sc, &q);
        assert(q.mq_cleanup_state == 0);
    }

    // 2. RX bounds guard rejects oversized LEN0 without writing past dm_mapsize
    {
        mwx_softc sc = {};
        dmamap_t qmap{4096}, dmap{2048};
        mwx_desc desc[8] = {};
        mwx_queue_data qdata[8] = {};
        for (int i = 0; i < 8; i++) qdata[i].md_map = &dmap;
        qdata[0].md_mbuf = new mbuf;
        desc[0].ctrl = MT_DMA_CTL_SD_LEN0(4096) | MT_DMA_CTL_LAST_SEC0 | MT_DMA_CTL_DMA_DONE; // exceeds 2048 dm_mapsize
        mwx_queue q{0x200, 8, 1, 0, desc, qdata, &qmap, 0, 0};
        sc.sc_rxq.mq_regbase = 0x200;
        g_dma_idx = 1;
        mbuf_list ml;
        bool more = true;
        mwx_dma_rx_dequeue(&sc, &q, &ml, 8, &more);
        assert(ml.items.empty() && !more && q.mq_cons == 1);
    }

    // 3. Deaf-RX scan detector & 30s autoreset cooldown + WFDMA stall & SER polling
    {
        mwx_softc sc = {};
        sc.sc_scan_start_rx = 100;
        sc.sc_rx_pkt_normal = 100;
        assert(!mwx_scan_check_rx_deaf(&sc, 10, 0, 0, 40)); // scan 1: below thresholds
        assert(mwx_scan_check_rx_deaf(&sc, 10, 0, 0, 30));  // scan 2: 2 scans, 20 ch, 70 mdrdy -> reset!
        assert(sc.sc_rx_deaf_resets == 1 && g_fullreset_tasks == 1);
        sc.sc_resetting = 0;
        // Cooldown blocks second immediate reset
        g_now_us += 5000000ULL;
        assert(!mwx_scan_check_rx_deaf(&sc, 16, 0, 0, 80));
        assert(!mwx_scan_check_rx_deaf(&sc, 16, 0, 0, 80));
        assert(g_fullreset_tasks == 1);
        // After 30s cooldown, SER poll triggers full reset
        g_now_us += 31000000ULL;
        g_glo = 5;
        g_mcu_cmd = MT_MCU_CMD_STOP_DMA;
        mwx_dma_timeo(&sc);
        assert(sc.sc_ser_events == 1 && g_fullreset_tasks == 2 && g_mcu_cmd == 0);
    }

    puts("PASS: 3-state CAS cleanup, RX length bounds, deaf-RX detector, 30s cooldown, and SER watchdog.");
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="mtk-rec-") as td:
    cpp = Path(td) / "rec.cpp"
    exe = Path(td) / "rec"
    cpp.write_text(harness)
    subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", str(cpp), "-o", str(exe)], check=True)
    r = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
    print(r.stdout, end="")
