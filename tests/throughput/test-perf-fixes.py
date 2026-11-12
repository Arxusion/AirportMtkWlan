#!/usr/bin/env python3
"""Host ASan/UBSan tests for Issue #2 throughput and latency fixes."""
from pathlib import Path
import subprocess, re

root = Path(__file__).resolve().parents[2]
mwx_src = (root / "SimpleMtkWlan/hal_mwx/MtkMwx.cpp").read_text()
inp_src = (root / "mtk80211/openbsd/net80211/ieee80211_input.c").read_text()

def extract_fn(src: str, sig: str) -> str:
    idx = src.index(sig)
    # Walk back to start of return type line
    start = src.rfind("\n\n", 0, idx)
    start = 0 if start == -1 else start + 2
    end = src.index("\n}\n", idx) + 3
    return src[start:end]

fn_stream = extract_fn(mwx_src, "mwx_update_stream_caps(struct mwx_softc *sc)\n{")
fn_intr = extract_fn(mwx_src, "mwx_intr(void *arg)\n{")
fn_rx_deq = extract_fn(mwx_src, "mwx_dma_rx_dequeue(struct mwx_softc *sc,")
fn_rx_done = extract_fn(mwx_src, "mwx_dma_rx_done(struct mwx_softc *sc,")
fn_traffic = extract_fn(mwx_src, "mwx_traffic_active(struct mwx_softc *sc, uint64_t now_ns)\n{")
fn_bgscan = extract_fn(mwx_src, "mwx_bgscan(struct ieee80211com *ic)\n{")
fn_set_tx = extract_fn(mwx_src, "mt7921_mcu_set_tx(struct mwx_softc *sc, struct mwx_vif *mvif)\n{")
fn_rearm = extract_fn(inp_src, "ieee80211_input_ba_rearm_timeout(struct ieee80211_rx_ba *ba)\n{")

harness = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <vector>

#define __packed __attribute__((packed))
#define DEVNAME(sc) "mwx0"
#define MWX_DEV_LOG(...) ((void)0)
#define KASSERT(x) assert(x)
#define htole16(x) (x)
#define le32toh(x) (x)
#define AIRPORT_WCL 1

#define IEEE80211_TX_MCS_SET_DEFINED 0x01
#define IEEE80211_VHTCAP_SUPP_CHAN_WIDTH_160MHZ 0x00000004
#define IEEE80211_NUM_ACS 4
#define IEEE80211_F_QOS 0x00080000
#define IEEE80211_S_RUN 4
#define MWX_FLAG_SCANNING 0x01
#define MWX_FLAG_BGSCAN 0x02

#define MT_WFDMA0_HOST_INT_STA 0xd4200
#define MT_WFDMA0_HOST_INT_ENA 0xd4204
#define MT_MCU_CMD 0xd5000
#define MT_MCU_CMD_WAKE_RX_PCIE 0x01
#define MT_DMA_DMA_IDX 0x0c
#define MT_INT_RX_DONE_WM 0x00010000U
#define MT_INT_RX_DONE_DATA 0x00040000U
#define MT_INT_RX_DONE_WM2 0x00100000U
#define MT_INT_MCU_CMD 0x20000000U
#define MT_INT_TX_DONE_ALL 0x00000004U
#define MT_DMA_CTL_LAST_SEC0 0x40000000U
#define MT_DNA_CTL_SD_GET_LEN0(c) ((c) & 0x3fffU)
#define MCU_CE_CMD_SET_EDCA_PARMS 0x1d
#define BUS_DMASYNC_PREREAD 0
#define BUS_DMASYNC_POSTREAD 1
#define IEEE80211_BA_TO_REARM_NS (250ULL * 1000000ULL)
#define ifnet _ifnet

struct CTimeout { int unused; };
struct mbuf { uint32_t len = 0; uint32_t pktlen = 0; mbuf *next = nullptr; int seq = 0; };
struct mbuf_list { std::vector<mbuf*> items; };
static inline mbuf *mbuf_next(mbuf *m) { return m->next; }
static inline void mbuf_setnext(mbuf *m, mbuf *n) { m->next = n; }
static inline void mbuf_setlen(mbuf *m, int l) { m->len = l; }
static inline uint32_t mbuf_len(mbuf *m) { return m->len; }
static inline void mbuf_pkthdr_setlen(mbuf *m, int l) { m->pktlen = l; }
static inline uint32_t mbuf_pkthdr_len(mbuf *m) { return m->pktlen; }
static inline bool ml_empty(const mbuf_list *ml) { return ml->items.empty(); }
static inline void ml_enqueue(mbuf_list *ml, mbuf *m) { ml->items.push_back(m); }
static inline void m_freem(mbuf *m) {
    while (m) { mbuf *n = m->next; delete m; m = n; }
}
#define MBUF_LIST_INITIALIZER() {}

struct dmamap_t { size_t dm_mapsize = 0; };
struct mwx_queue_data { mbuf *md_mbuf = nullptr; dmamap_t *md_map = nullptr; };
struct mwx_desc { uint32_t buf0 = 0, ctrl = 0, buf1 = 0, info = 0; };
struct mwx_queue {
    int mq_cons = 0;
    int mq_count = 0;
    uint32_t mq_regbase = 0;
    mwx_queue_data *mq_data = nullptr;
    mwx_desc *mq_desc = nullptr;
    dmamap_t *mq_map = nullptr;
};
struct netstat_t { uint64_t inputPackets = 0, outputPackets = 0; };
struct _ifnet { netstat_t *netStat = nullptr; };
struct ieee80211_edca_ac_params {
    uint8_t ac_ecwmin, ac_ecwmax, ac_aifsn;
    uint16_t ac_txoplimit;
    uint8_t ac_acm;
};
struct ieee80211_he_mcs_nss_supp {
    uint16_t rx_mcs_80, tx_mcs_80, rx_mcs_160, tx_mcs_160, rx_mcs_80p80, tx_mcs_80p80;
};
struct ieee80211com {
    void *ic_softc = nullptr;
    _ifnet ic_if;
    int ic_state = 0;
    uint32_t ic_flags = 0;
    uint8_t ic_sup_mcs[10] = {};
    uint8_t ic_tx_mcs_set = 0;
    uint32_t ic_vhtcaps = 0;
    uint16_t ic_vht_rx_mcs_map = 0, ic_vht_tx_mcs_map = 0;
    ieee80211_he_mcs_nss_supp ic_he_mcs_nss_supp = {};
    ieee80211_edca_ac_params ic_edca_ac[4] = {};
    bool ic_wcl_scan_requested = false;
    bool ic_wcl_scan_restricted = false;
    uint8_t ic_wcl_scan_ssid_length = 0;
};
struct mwx_vif { uint8_t idx = 0, wmm_idx = 0; };
struct mwx_softc {
    ieee80211com sc_ic;
    struct { uint8_t num_streams = 0; } sc_capa;
    mwx_vif sc_vif;
    uint32_t sc_flags = 0;
    uint32_t sc_intr_mask = MT_INT_RX_DONE_ALL_STUB;
    uint32_t sc_intr_pending = 0;
    bool sc_suspended = false;
    bool sc_detaching = false;
    void *sc_dmat = nullptr;
    CTimeout *sc_intr_to = nullptr;
    mwx_queue sc_rxfwdlq, sc_rxmcuq, sc_rxq;
    uint64_t sc_last_bgscan_ns = 0;
    uint64_t sc_last_active_traffic_ns = 0;
    uint64_t sc_last_traffic_pkts = 0;
    uint64_t sc_last_traffic_check_ns = 0;
};
#undef MT_INT_RX_DONE_ALL_STUB
#define MT_INT_RX_DONE_ALL_INIT (MT_INT_RX_DONE_WM | MT_INT_RX_DONE_DATA | MT_INT_RX_DONE_WM2 | MT_INT_TX_DONE_ALL | MT_INT_MCU_CMD)

struct ieee80211_rx_ba {
    int ba_timeout_val = 0;
    CTimeout *ba_to = nullptr;
    uint64_t ba_to_last_ns = 0;
};

static uint64_t g_fake_ns = 1000000000ULL;
static inline void clock_get_uptime(uint64_t *t) { *t = g_fake_ns; }
static inline void absolutetime_to_nanoseconds(uint64_t t, uint64_t *ns) { *ns = t; }
static inline uint64_t mach_absolute_time() { return g_fake_ns; }

static int g_timeout_add_calls = 0;
static int g_timeout_last_val = 0;
static std::vector<int> g_intr_to_calls;
static void timeout_add_usec(CTimeout **, int us) { g_timeout_add_calls++; g_timeout_last_val = us; }
static void timeout_add_msec(CTimeout **, int ms) { g_intr_to_calls.push_back(ms); }

static uint32_t g_reg_sta = 0;
static uint32_t g_reg_ena = 0;
static std::deque<uint32_t> g_race_on_ena_restore;
static uint32_t g_rxq_dma_idx = 0;
static int g_rxq_dma_reads = 0;
static int g_fill_calls = 0;
static int g_process_calls = 0;
static int g_processed_pkts = 0;
static int g_hw_scan_calls = 0;
static std::vector<uint8_t> g_mcu_edca_payload;

static uint32_t mwx_read(mwx_softc *sc, uint32_t reg) {
    if (reg == MT_WFDMA0_HOST_INT_STA) return g_reg_sta;
    if (reg == MT_WFDMA0_HOST_INT_ENA) return g_reg_ena;
    if (reg == sc->sc_rxq.mq_regbase + MT_DMA_DMA_IDX) {
        g_rxq_dma_reads++;
        return g_rxq_dma_idx;
    }
    return 0;
}
static void mwx_write(mwx_softc *sc, uint32_t reg, uint32_t val) {
    if (reg == MT_WFDMA0_HOST_INT_STA) { g_reg_sta &= ~val; return; }
    if (reg == MT_WFDMA0_HOST_INT_ENA) {
        uint32_t prev = g_reg_ena;
        g_reg_ena = val;
        if (prev == 0 && val != 0 && !g_race_on_ena_restore.empty()) {
            g_reg_sta |= g_race_on_ena_restore.front();
            g_race_on_ena_restore.pop_front();
        }
    }
}
static void bus_dmamap_sync(void*, dmamap_t*, int, size_t, int) {}
static void bus_dmamap_unload(void*, dmamap_t*) {}
static void mwx_reset(mwx_softc*) { assert(false && "unexpected reset"); }
static int mwx_queue_fill(mwx_softc*, mwx_queue*) { g_fill_calls++; return 0; }
static void mwx_dma_rx_process(mwx_softc*, mbuf_list *ml) {
    g_process_calls++;
    g_processed_pkts += (int)ml->items.size();
    for (auto *m : ml->items) m_freem(m);
    ml->items.clear();
}
static void mwx_dma_tx_done(mwx_softc *sc) { (void)sc; }
static int mt7921_mcu_hw_scan(mwx_softc*, int) { g_hw_scan_calls++; return 0; }
static int mwx_mcu_send_msg(mwx_softc*, int cmd, void *data, int len, void*) {
    assert(cmd == MCU_CE_CMD_SET_EDCA_PARMS);
    auto *b = static_cast<const uint8_t*>(data);
    g_mcu_edca_payload.assign(b, b + len);
    return 0;
}

static uint32_t mwx_intr_calls = 0;
bool mwx_dma_rx_done(mwx_softc *sc, mwx_queue *q);
int mwx_intr(void *arg);
'''

harness = harness.replace("uint32_t sc_intr_mask = MT_INT_RX_DONE_ALL_STUB;", "uint32_t sc_intr_mask = MT_INT_RX_DONE_WM | MT_INT_RX_DONE_DATA | MT_INT_RX_DONE_WM2 | MT_INT_TX_DONE_ALL | MT_INT_MCU_CMD;")

tests = r'''
static void test_stream_caps() {
    mwx_softc sc{};
    sc.sc_capa.num_streams = 2;
    sc.sc_ic.ic_vhtcaps = IEEE80211_VHTCAP_SUPP_CHAN_WIDTH_160MHZ;
    mwx_update_stream_caps(&sc);
    assert(sc.sc_ic.ic_sup_mcs[0] == 0xff && sc.sc_ic.ic_sup_mcs[1] == 0xff);
    assert(sc.sc_ic.ic_vht_rx_mcs_map == 0xfffa && sc.sc_ic.ic_vht_tx_mcs_map == 0xfffa);
    assert(sc.sc_ic.ic_he_mcs_nss_supp.rx_mcs_80 == 0xfffa);
    assert(sc.sc_ic.ic_he_mcs_nss_supp.tx_mcs_80 == 0xfffa);
    assert(sc.sc_ic.ic_he_mcs_nss_supp.rx_mcs_160 == 0xfffa);
    assert(sc.sc_ic.ic_he_mcs_nss_supp.tx_mcs_160 == 0xfffa);

    sc.sc_capa.num_streams = 1;
    sc.sc_ic.ic_vhtcaps = 0;
    mwx_update_stream_caps(&sc);
    assert(sc.sc_ic.ic_sup_mcs[1] == 0x00);
    assert(sc.sc_ic.ic_vht_rx_mcs_map == 0xfffe);
    assert(sc.sc_ic.ic_he_mcs_nss_supp.rx_mcs_80 == 0xfffe);
    assert(sc.sc_ic.ic_he_mcs_nss_supp.rx_mcs_160 == 0xffff);
}

static void setup_rx_ring(mwx_queue &q, int count, int dma_idx) {
    static dmamap_t qmap{64}, dmap{2048};
    q.mq_count = count;
    q.mq_cons = 0;
    q.mq_regbase = 0x100;
    q.mq_map = &qmap;
    q.mq_data = new mwx_queue_data[count]();
    q.mq_desc = new mwx_desc[count]();
    for (int i = 0; i < dma_idx; i++) {
        q.mq_data[i].md_mbuf = new mbuf();
        q.mq_data[i].md_map = &dmap;
        // Every 2 descriptors form one packet to test LAST_SEC0 boundary preservation
        q.mq_desc[i].ctrl = 512U | ((i & 1) ? MT_DMA_CTL_LAST_SEC0 : 0);
    }
}

static void free_rx_ring(mwx_queue &q) {
    for (int i = 0; i < q.mq_count; i++) {
        if (q.mq_data[i].md_mbuf) m_freem(q.mq_data[i].md_mbuf);
    }
    delete[] q.mq_data;
    delete[] q.mq_desc;
}

static void test_intr_and_rx_budget() {
    mwx_softc sc{};
    CTimeout to{};
    sc.sc_intr_to = &to;
    // Race check: STA had TX_DONE, then RX_DONE_WM2 arrived just while ENA was 0!
    g_reg_sta = MT_INT_TX_DONE_ALL;
    g_race_on_ena_restore.push_back(MT_INT_RX_DONE_WM2);
    assert(mwx_intr(&sc) == 1);
    assert((g_reg_sta & sc.sc_intr_mask) == 0 && "race-window intr must not stay stranded");
    assert(g_reg_ena == sc.sc_intr_mask);
    assert(g_intr_to_calls.empty());

    // Bounded RX chunking: 600 descriptors = 300 packets (2 descs per pkt).
    // One mwx_dma_rx_done call processes 4 chunks * 64 = 256 packets, refills 4 times,
    // never breaks a multi-desc chain, only reads DMA_IDX once per chunk, and sets more=true.
    setup_rx_ring(sc.sc_rxq, 1024, 600);
    g_rxq_dma_idx = 600;
    g_rxq_dma_reads = g_fill_calls = g_process_calls = g_processed_pkts = 0;
    bool more = mwx_dma_rx_done(&sc, &sc.sc_rxq);
    assert(more == true);
    assert(g_processed_pkts == 256);
    assert(g_fill_calls == 4 && g_process_calls == 4);
    assert(g_rxq_dma_reads == 4);
    assert(sc.sc_rxq.mq_cons == 512);
    // Drain the remaining 44 packets -> more == false.
    more = mwx_dma_rx_done(&sc, &sc.sc_rxq);
    assert(more == false);
    assert(g_processed_pkts == 300);
    assert(sc.sc_rxq.mq_cons == 600);
    free_rx_ring(sc.sc_rxq);

    // Budget exhaustion under sustained interrupts schedules 1ms timer yield without losing STA bits.
    g_intr_to_calls.clear();
    g_race_on_ena_restore.clear();
    for (int i = 0; i < 8; i++) g_race_on_ena_restore.push_back(MT_INT_TX_DONE_ALL);
    g_reg_sta = MT_INT_TX_DONE_ALL;
    g_race_on_ena_restore.push_back(MT_INT_RX_DONE_WM2); // stays pending after max_passes
    // Wait: during loop, STA is re-read without restoring ENA until pass == max_passes.
    g_race_on_ena_restore.clear();
    setup_rx_ring(sc.sc_rxq, 1024, 600);
    g_rxq_dma_idx = 600;
    // Wait: mwx_dma_rx_done returns more=true on pass 0..7 if DMA_IDX stays ahead,
    // wait: after chunk drains 600 descriptors in 2 passes, make DMA_IDX keep advancing or test via race_on_ena_restore:
    g_reg_sta = MT_INT_RX_DONE_DATA;
    g_race_on_ena_restore.push_back(MT_INT_RX_DONE_WM2);
    free_rx_ring(sc.sc_rxq);
    setup_rx_ring(sc.sc_rxq, 4096, 3000); // > 8*256 = 2048 packets = 4096 wait make it 5000
    free_rx_ring(sc.sc_rxq);
    setup_rx_ring(sc.sc_rxq, 8192, 5000); // 2500 packets, 8 passes * 256 = 2048 -> still remaining!
    g_rxq_dma_idx = 5000;
    g_intr_to_calls.clear();
    g_race_on_ena_restore.clear();
    assert(mwx_intr(&sc) == 1);
    assert(g_intr_to_calls.size() == 1 && g_intr_to_calls[0] == 1);
    assert(sc.sc_intr_pending == MT_INT_RX_DONE_DATA);
    assert(g_reg_ena == sc.sc_intr_mask);
    // Next call (from timeout) drains the rest:
    assert(mwx_intr(&sc) == 1);
    assert(sc.sc_rxq.mq_cons == 5000);
    assert(sc.sc_intr_pending == 0);
    free_rx_ring(sc.sc_rxq);
}

static void test_ba_rearm_throttle() {
    ieee80211_rx_ba ba{};
    CTimeout to{};
    ba.ba_to = &to;
    ba.ba_timeout_val = 5000000; // 5 seconds
    g_timeout_add_calls = 0;

    // 100 packets over 100ms -> should rearm only once!
    for (int i = 0; i < 100; i++) {
        g_fake_ns = 1000000000ULL + (uint64_t)i * 1000000ULL;
        ieee80211_input_ba_rearm_timeout(&ba);
    }
    assert(g_timeout_add_calls == 1);
    // At +250ms, should rearm a second time!
    g_fake_ns += 250000000ULL;
    ieee80211_input_ba_rearm_timeout(&ba);
    assert(g_timeout_add_calls == 2);

    // Short timeout (20ms) clamps rearm interval to half (10ms)
    ieee80211_rx_ba short_ba{};
    short_ba.ba_to = &to;
    short_ba.ba_timeout_val = 20000; // 20ms
    g_timeout_add_calls = 0;
    g_fake_ns = 5000000000ULL;
    ieee80211_input_ba_rearm_timeout(&short_ba);
    g_fake_ns += 5000000ULL; // +5ms < 10ms
    ieee80211_input_ba_rearm_timeout(&short_ba);
    assert(g_timeout_add_calls == 1);
    g_fake_ns += 6000000ULL; // +11ms >= 10ms
    ieee80211_input_ba_rearm_timeout(&short_ba);
    assert(g_timeout_add_calls == 2);
}

static void test_edca_and_bgscan() {
    mwx_softc sc{};
    sc.sc_ic.ic_softc = &sc;
    netstat_t ns{};
    sc.sc_ic.ic_if.netStat = &ns;
    sc.sc_ic.ic_state = IEEE80211_S_RUN;
    sc.sc_ic.ic_flags = IEEE80211_F_QOS;
    // BE=0, BK=1, VI=2, VO=3 in OpenBSD
    sc.sc_ic.ic_edca_ac[0] = {4, 10, 3, 0, 0};
    sc.sc_ic.ic_edca_ac[1] = {4, 10, 7, 0, 0};
    sc.sc_ic.ic_edca_ac[2] = {3, 4, 2, 94, 0};
    sc.sc_ic.ic_edca_ac[3] = {2, 3, 2, 47, 1};
    assert(mt7921_mcu_set_tx(&sc, &sc.sc_vif) == 0);
    struct __packed edca_wire { uint16_t cw_min, cw_max, txop, aifs; uint8_t guard, acm; };
    struct __packed req_wire { edca_wire edca[4]; uint8_t bss_idx, qos, wmm_idx, pad; };
    assert(g_mcu_edca_payload.size() == sizeof(req_wire));
    auto *r = reinterpret_cast<const req_wire*>(g_mcu_edca_payload.data());
    assert(r->qos == 1);
    // MT7921 order: [0]=VI, [1]=VO, [2]=BE, [3]=BK
    assert(r->edca[0].aifs == 2 && r->edca[0].txop == 94 && r->edca[0].cw_min == 3);
    assert(r->edca[1].aifs == 2 && r->edca[1].txop == 47 && r->edca[1].acm == 1);
    assert(r->edca[2].aifs == 3 && r->edca[2].cw_min == 4 && r->edca[2].cw_max == 10);
    assert(r->edca[3].aifs == 7 && r->edca[3].cw_min == 4 && r->edca[3].cw_max == 10);

    // bgscan deferred during active streaming (>= 200 pps), allowed for explicit SSID
    g_hw_scan_calls = 0;
    g_fake_ns = 10000000000ULL;
    ns.inputPackets = 100; ns.outputPackets = 50;
    assert(mwx_bgscan(&sc.sc_ic) == 0);
    assert(g_hw_scan_calls == 1);
    sc.sc_flags = 0;
    g_fake_ns += 1000000000ULL;
    ns.inputPackets += 400; // 400 pps
    sc.sc_ic.ic_wcl_scan_requested = true;
    sc.sc_ic.ic_wcl_scan_restricted = true;
    sc.sc_ic.ic_wcl_scan_ssid_length = 0;
    assert(mwx_bgscan(&sc.sc_ic) == EBUSY);
    assert(g_hw_scan_calls == 1);
    // Explicit SSID scan still proceeds even under active traffic
    sc.sc_ic.ic_wcl_scan_ssid_length = 6;
    assert(mwx_bgscan(&sc.sc_ic) == 0);
    assert(g_hw_scan_calls == 2);
}

int main() {
    test_stream_caps();
    test_intr_and_rx_budget();
    test_ba_rearm_throttle();
    test_edca_and_bgscan();
    puts("PASS throughput/latency fixes: 2SS MCS maps, lost-MSI race recheck, bounded RX batching, BA timeout throttling, EDCA QOS & bgscan deferral");
    return 0;
}
'''

out = Path(__file__).resolve().parent
cpp = out / "test-perf-fixes.cpp"
exe = out / "test-perf-fixes"
cpp.write_text("\n".join([harness, fn_stream, fn_rx_deq, fn_rx_done, fn_intr, fn_traffic, fn_bgscan, fn_set_tx, fn_rearm, tests]))
subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", str(cpp), "-o", str(exe)], check=True)
subprocess.run([str(exe)], check=True)
