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
fn_aspm_dev = extract_fn(mwx_src, "mwx_pci_clear_aspm_dev(struct mwx_softc *sc,")
fn_aspm = extract_fn(mwx_src, "mwx_pci_disable_aspm(struct mwx_softc *sc,")
fn_start = extract_fn(mwx_src, "mwx_start(struct ifnet *ifp)\n{")
fn_txwi_enq = extract_fn(mwx_src, "mwx_dma_txwi_enqueue(struct mwx_softc *sc, struct mwx_queue *q,")
fn_tx_done = extract_fn(mwx_src, "mwx_dma_tx_done(struct mwx_softc *sc)\n{")
fn_rx = extract_fn(mwx_src, "mwx_rx(struct mwx_softc *sc, struct mbuf *m, struct mbuf_list *ml)\n{")
fn_rearm = extract_fn(inp_src, "ieee80211_input_ba_rearm_timeout(struct ieee80211_rx_ba *ba)\n{")

harness = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>
#include <vector>

#define __packed __attribute__((packed))
#define DEVNAME(sc) "mwx0"
#define MWX_DEV_LOG(...) ((void)0)
#define KASSERT(x) assert(x)
#define htole16(x) (x)
#define htole32(x) (x)
#define le32toh(x) (x)
#define AIRPORT_WCL 1

#define IEEE80211_TX_MCS_SET_DEFINED 0x01
#define IEEE80211_VHTCAP_SUPP_CHAN_WIDTH_160MHZ 0x00000004
#define IEEE80211_NUM_ACS 4
#define IEEE80211_F_QOS 0x00080000
#define IEEE80211_S_RUN 4
#define IEEE80211_F_TX_MGMT_ONLY 0x01
#define IEEE80211_ADDR_LEN 6
#define IEEE80211_ADDR_EQ(a, b) (memcmp((a), (b), 6) == 0)
#define IEEE80211_FC0_TYPE_MASK 0x0c
#define IEEE80211_FC0_TYPE_MGT 0x00
#define IEEE80211_FC0_TYPE_CTL 0x04
#define IEEE80211_FC0_TYPE_DATA 0x08
#define IEEE80211_FC0_SUBTYPE_MASK 0xf0
#define IEEE80211_FC0_SUBTYPE_BAR 0x80
#define IEEE80211_FC1_PROTECTED 0x40
#define IEEE80211_RXI_HWDEC 0x01
#define MWX_RXI_AMSDU_MASK 0x06
#define MWX_FLAG_SCANNING 0x01
#define MWX_FLAG_BGSCAN 0x02
#define IFF_UP 0x01
#define IFF_RUNNING 0x02

#define MT_WFDMA0_HOST_INT_STA 0xd4200
#define MT_WFDMA0_HOST_INT_ENA 0xd4204
#define MT_MCU_CMD 0xd5000
#define MT_MCU_CMD_WAKE_RX_PCIE 0x01
#define MT_DMA_CPU_IDX 0x08
#define MT_DMA_DMA_IDX 0x0c
#define MT_INT_RX_DONE_WM 0x00010000U
#define MT_INT_RX_DONE_DATA 0x00040000U
#define MT_INT_RX_DONE_WM2 0x00100000U
#define MT_INT_MCU_CMD 0x20000000U
#define MT_INT_TX_DONE_ALL 0x00000004U
#define MT_DMA_CTL_LAST_SEC0 0x40000000U
#define MT_DMA_CTL_SD_LEN0(l) ((uint32_t)(l) << 16)
#define MT_DNA_CTL_SD_GET_LEN0(c) ((c) & 0x3fffU)
#define MCU_CE_CMD_SET_EDCA_PARMS 0x1d
#define BUS_DMASYNC_PREREAD 0
#define BUS_DMASYNC_POSTREAD 1
#define BUS_DMASYNC_PREWRITE 2
#define BUS_DMASYNC_POSTWRITE 3
#define IEEE80211_BA_TO_REARM_NS (250ULL * 1000000ULL)
#define ifnet _ifnet
#define kIOPCIExpressL1PMSubstatesCapability 0xffffffe1U
#define kIOPCICapabilityIDPCIExpress 0x10U

typedef uint8_t UInt8;
typedef uint16_t UInt16;
typedef uint32_t UInt32;
typedef size_t IOByteCount;
static int g_io_service_plane_dummy = 0;
#define gIOServicePlane (&g_io_service_plane_dummy)
static bool g_boot_arg_allow_aspm = false;
static bool PE_parse_boot_argn(const char *arg, void *val, int sz) {
    (void)sz;
    if (strcmp(arg, "-mtkallowaspm") == 0 && g_boot_arg_allow_aspm) {
        *static_cast<int*>(val) = 1;
        return true;
    }
    return false;
}

struct IORegistryEntry {
    IORegistryEntry *parent = nullptr;
    bool is_pci = false;
    IORegistryEntry *getParentEntry(void *) { return parent; }
    virtual ~IORegistryEntry() = default;
};
struct IOPCIDevice : public IORegistryEntry {
    const char *name = "ep";
    IOByteCount l1ss_off = 0x1e0;
    uint32_t l1ss_ctl1 = 0;
    UInt8 pcie_off = 0x80;
    uint16_t lnkctl = 0;
    std::vector<std::string> *write_log = nullptr;
    UInt32 extendedFindPCICapability(UInt32 id, IOByteCount *off) {
        if (id == kIOPCIExpressL1PMSubstatesCapability && l1ss_off) {
            *off = l1ss_off;
            return 0x1e01001eU;
        }
        return 0;
    }
    UInt32 findPCICapability(UInt32 id, UInt8 *off) {
        if (id == kIOPCICapabilityIDPCIExpress && pcie_off) {
            *off = pcie_off;
            return 0x0010U;
        }
        return 0;
    }
    UInt32 extendedConfigRead32(IOByteCount off) {
        assert(off == l1ss_off + 0x08);
        return l1ss_ctl1;
    }
    void extendedConfigWrite32(IOByteCount off, UInt32 val) {
        assert(off == l1ss_off + 0x08);
        l1ss_ctl1 = val;
        if (write_log) write_log->push_back(std::string(name) + ":l1ss");
    }
    UInt16 configRead16(UInt8 off) {
        assert(off == pcie_off + 0x10);
        return lnkctl;
    }
    void configWrite16(UInt8 off, UInt16 val) {
        assert(off == pcie_off + 0x10);
        lnkctl = val;
        if (write_log) write_log->push_back(std::string(name) + ":lnkctl");
    }
};
#define OSDynamicCast(cls, ptr) ((ptr) && (ptr)->is_pci ? static_cast<cls*>(ptr) : nullptr)

struct CTimeout { int unused; };
struct mbuf { uint32_t len = 0; uint32_t pktlen = 0; mbuf *next = nullptr; int seq = 0; uint8_t data[128] = {}; };
struct mbuf_list { std::vector<mbuf*> items; };
#define mtod(m, t) (reinterpret_cast<t>((m)->data))
static inline mbuf *mbuf_next(mbuf *m) { return m->next; }
static inline void mbuf_setnext(mbuf *m, mbuf *n) { m->next = n; }
static inline void mbuf_setlen(mbuf *m, int l) { m->len = l; }
static inline uint32_t mbuf_len(mbuf *m) { return m->len; }
static inline void mbuf_pkthdr_setlen(mbuf *m, int l) { m->pktlen = l; }
static inline uint32_t mbuf_pkthdr_len(mbuf *m) { return m->pktlen; }
static inline void *mbuf_pkthdr_rcvif(mbuf *) { return nullptr; }
static inline mbuf *m_pullup(mbuf *m, int) { return m; }
static inline bool ml_empty(const mbuf_list *ml) { return ml->items.empty(); }
static inline void ml_enqueue(mbuf_list *ml, mbuf *m) { ml->items.push_back(m); }
static inline void m_freem(mbuf *m) {
    while (m) { mbuf *n = m->next; delete m; m = n; }
}
#define MBUF_LIST_INITIALIZER() {}

struct mt76_txwi { uint32_t w[8]; };
struct mwx_txwi { mt76_txwi *mt_desc = nullptr; uint32_t mt_addr = 0; };
struct dmamap_t { size_t dm_mapsize = 0; };
struct mwx_queue_data { mbuf *md_mbuf = nullptr; mwx_txwi *md_txwi = nullptr; dmamap_t *md_map = nullptr; };
struct mwx_desc { uint32_t buf0 = 0, ctrl = 0, buf1 = 0, info = 0; };
struct mwx_queue {
    int mq_cons = 0;
    int mq_prod = 0;
    int mq_count = 0;
    uint32_t mq_regbase = 0;
    mwx_queue_data *mq_data = nullptr;
    mwx_desc *mq_desc = nullptr;
    dmamap_t *mq_map = nullptr;
};
struct ether_header { uint8_t d[6], s[6]; uint16_t t; };
struct ieee80211_frame { uint8_t i_fc[2]; uint8_t i_dur[2]; uint8_t i_addr1[6]; uint8_t i_addr2[6]; uint8_t i_addr3[6]; uint8_t i_seq[2]; };
struct ieee80211_node {};
struct ieee80211_rxinfo { uint32_t rxi_flags = 0; uint16_t rxi_chan = 0; int8_t rxi_rssi = 0; };
struct ifqueue {
    std::deque<mbuf*> q;
    bool oactive = false;
};
static inline bool ifq_is_oactive(const ifqueue *q) { return q->oactive; }
static inline void ifq_set_oactive(ifqueue *q) { q->oactive = true; }
static inline mbuf *ifq_dequeue(ifqueue *q) {
    if (q->q.empty()) return nullptr;
    mbuf *m = q->q.front(); q->q.pop_front(); return m;
}
struct mgtqueue {
    std::deque<mbuf*> q;
};
static inline mbuf *mq_dequeue(mgtqueue *q) {
    if (q->q.empty()) return nullptr;
    mbuf *m = q->q.front(); q->q.pop_front(); return m;
}
struct netstat_t { uint64_t inputPackets = 0, outputPackets = 0, outputErrors = 0; };
struct _ifnet {
    void *if_softc = nullptr;
    netstat_t *netStat = nullptr;
    uint32_t if_flags = 0;
    uint32_t if_oerrors = 0;
    uint32_t if_ierrors = 0;
    uint32_t if_timer = 0;
    ifqueue if_snd;
};
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
    mgtqueue ic_mgtq;
    int ic_state = 0;
    uint32_t ic_flags = 0;
    uint32_t ic_xflags = 0;
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
    mwx_queue sc_txq, sc_txmcuq, sc_txfwdlq;
    uint64_t sc_last_bgscan_ns = 0;
    uint64_t sc_last_active_traffic_ns = 0;
    uint64_t sc_last_traffic_pkts = 0;
    uint64_t sc_last_traffic_check_ns = 0;
    uint32_t sc_tx_full_cnt = 0;
    uint32_t sc_rx_fill_fail = 0;
    uint32_t sc_rx_delivered = 0;
    int sc_amsdu_n = 0;
    uint8_t sc_amsdu_ta[6] = {};
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
static std::vector<uint32_t> g_txq_doorbells;
static bool g_tx_has_room_val = true;
static int g_tx_kick_calls = 0;
static uint32_t g_next_rx_flags = 0;
static int g_amsdu_add_calls = 0;
static int g_amsdu_flush_calls = 0;
static int g_rx_deliver_calls = 0;
static uint32_t mwx_rx_ctl_cnt = 0, mwx_rx_bar_cnt = 0, mwx_rx_hwdec_cnt = 0, mwx_rx_swdec_cnt = 0;

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
        return;
    }
    if (sc->sc_txq.mq_regbase && reg == sc->sc_txq.mq_regbase + MT_DMA_CPU_IDX)
        g_txq_doorbells.push_back(val);
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
static int mwx_dma_free_slots(mwx_queue *q) {
    int used = (q->mq_prod - q->mq_cons + q->mq_count) % q->mq_count;
    return q->mq_count - 1 - used;
}
static void mwx_dma_tx_cleanup(mwx_softc*, mwx_queue*) {}
static bool mwx_tx_has_room(mwx_softc*, int) { return g_tx_has_room_val; }
static void mwx_tx_kick(mwx_softc *sc) { sc->sc_ic.ic_if.if_snd.oactive = false; g_tx_kick_calls++; }
static mbuf *ieee80211_encap(_ifnet*, mbuf *m, ieee80211_node **nip) { static ieee80211_node n; *nip = &n; return m; }
static void ieee80211_release_node(ieee80211com*, ieee80211_node*) {}
int mwx_dma_txwi_enqueue(mwx_softc *sc, mwx_queue *q, mwx_txwi *mt, bool doorbell);
static int mwx_tx(mwx_softc *sc, mbuf *m, ieee80211_node*, bool doorbell = true) {
    static mt76_txwi dummy_desc{};
    static mwx_txwi dummy_txwi{&dummy_desc, 0x1000};
    int rv = mwx_dma_txwi_enqueue(sc, &sc->sc_txq, &dummy_txwi, doorbell);
    m_freem(m);
    return rv;
}
static int mt7921_mac_fill_rx(mwx_softc*, mbuf*, ieee80211_rxinfo *rxi) { rxi->rxi_flags = g_next_rx_flags; return 0; }
static void mwx_amsdu_add(mwx_softc *sc, mbuf *m, ieee80211_rxinfo*, mbuf_list*) {
    g_amsdu_add_calls++;
    auto *wh = mtod(m, ieee80211_frame*);
    if (sc->sc_amsdu_n == 0) memcpy(sc->sc_amsdu_ta, wh->i_addr2, 6);
    sc->sc_amsdu_n++;
    m_freem(m);
}
static void mwx_amsdu_flush(mwx_softc *sc, mbuf_list*) { g_amsdu_flush_calls++; sc->sc_amsdu_n = 0; }
static void mwx_rx_deliver(mwx_softc*, mbuf *m, ieee80211_rxinfo*, mbuf_list*) { g_rx_deliver_calls++; m_freem(m); }
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
void mwx_dma_tx_done(mwx_softc *sc);
void mwx_start(struct ifnet *ifp);
void mwx_rx(mwx_softc *sc, mbuf *m, mbuf_list *ml);
void mwx_pci_disable_aspm(mwx_softc *sc, IOPCIDevice *dev);
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
    // One mwx_dma_rx_done call processes 2 chunks * 64 = 128 packets, refills 2 times,
    // never breaks a multi-desc chain, only reads DMA_IDX once per chunk, and sets more=true.
    setup_rx_ring(sc.sc_rxq, 1024, 600);
    g_rxq_dma_idx = 600;
    g_rxq_dma_reads = g_fill_calls = g_process_calls = g_processed_pkts = 0;
    bool more = mwx_dma_rx_done(&sc, &sc.sc_rxq);
    assert(more == true);
    assert(g_processed_pkts == 128);
    assert(g_fill_calls == 2 && g_process_calls == 2);
    assert(g_rxq_dma_reads == 2);
    assert(sc.sc_rxq.mq_cons == 256);
    // Drain the next 128 -> still 44 left (more == true), then last 44 -> more == false.
    more = mwx_dma_rx_done(&sc, &sc.sc_rxq);
    assert(more == true);
    assert(g_processed_pkts == 256);
    assert(sc.sc_rxq.mq_cons == 512);
    more = mwx_dma_rx_done(&sc, &sc.sc_rxq);
    assert(more == false);
    assert(g_processed_pkts == 300);
    assert(sc.sc_rxq.mq_cons == 600);
    free_rx_ring(sc.sc_rxq);

    // Budget exhaustion under sustained interrupts schedules 1ms timer yield without losing STA bits.
    g_reg_sta = MT_INT_RX_DONE_DATA;
    setup_rx_ring(sc.sc_rxq, 1024, 800); // 400 packets: 2 passes * 128 = 256 -> remaining -> yield!
    g_rxq_dma_idx = 800;
    g_intr_to_calls.clear();
    g_race_on_ena_restore.clear();
    assert(mwx_intr(&sc) == 1);
    assert(sc.sc_rxq.mq_cons == 512);
    assert(g_intr_to_calls.size() == 1 && g_intr_to_calls[0] == 1);
    assert(sc.sc_intr_pending == MT_INT_RX_DONE_DATA);
    assert(g_reg_ena == sc.sc_intr_mask);
    // Next call (from timeout) drains the rest:
    assert(mwx_intr(&sc) == 1);
    assert(sc.sc_rxq.mq_cons == 800);
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

static void test_aspm_disable() {
    mwx_softc sc{};
    std::vector<std::string> writes;

    IOPCIDevice parent;
    parent.name = "parent";
    parent.is_pci = true;
    parent.l1ss_ctl1 = 0x0000000fU;
    parent.lnkctl = 0x0043U;
    parent.write_log = &writes;

    IORegistryEntry bridge;
    bridge.is_pci = false;
    bridge.parent = &parent;

    IOPCIDevice ep;
    ep.name = "ep";
    ep.is_pci = true;
    ep.parent = &bridge;
    ep.l1ss_ctl1 = 0x0000000fU;
    ep.lnkctl = 0x0043U;
    ep.write_log = &writes;

    g_boot_arg_allow_aspm = false;
    mwx_pci_disable_aspm(&sc, &ep);
    assert(ep.l1ss_ctl1 == 0);
    assert(ep.lnkctl == 0x0040U);
    assert(parent.l1ss_ctl1 == 0);
    assert(parent.lnkctl == 0x0040U);
    assert(writes.size() == 4);
    assert(writes[0] == "ep:l1ss" && writes[1] == "ep:lnkctl");
    assert(writes[2] == "parent:l1ss" && writes[3] == "parent:lnkctl");

    // -mtkallowaspm leaves ASPM and L1SS bits untouched.
    ep.l1ss_ctl1 = 0x0fU;
    ep.lnkctl = 0x0043U;
    parent.l1ss_ctl1 = 0x0fU;
    parent.lnkctl = 0x0043U;
    writes.clear();
    g_boot_arg_allow_aspm = true;
    mwx_pci_disable_aspm(&sc, &ep);
    assert(writes.empty());
    assert(ep.l1ss_ctl1 == 0x0fU && ep.lnkctl == 0x0043U);
    assert(parent.l1ss_ctl1 == 0x0fU && parent.lnkctl == 0x0043U);
    g_boot_arg_allow_aspm = false;
}

static void test_tx_doorbell_and_oactive_kick() {
    mwx_softc sc{};
    static dmamap_t qmap{64};
    sc.sc_txq.mq_count = 64;
    sc.sc_txq.mq_regbase = 0x300;
    sc.sc_txq.mq_map = &qmap;
    sc.sc_txq.mq_data = new mwx_queue_data[64]();
    sc.sc_txq.mq_desc = new mwx_desc[64]();

    netstat_t ns{};
    sc.sc_ic.ic_softc = &sc;
    sc.sc_ic.ic_if.if_softc = &sc;
    sc.sc_ic.ic_state = IEEE80211_S_RUN;
    sc.sc_ic.ic_if.netStat = &ns;
    sc.sc_ic.ic_if.if_flags = IFF_UP | IFF_RUNNING;

    for (int i = 0; i < 20; i++) {
        mbuf *m = new mbuf();
        m->len = 64;
        sc.sc_ic.ic_if.if_snd.q.push_back(m);
    }

    g_txq_doorbells.clear();
    g_tx_has_room_val = true;
    mwx_start(&sc.sc_ic.ic_if);
    assert(ns.outputPackets == 20);
    // 20 frames -> 1 doorbell at frame 16, 1 flush doorbell after frame 20 (vs 20 MMIO writes).
    assert(g_txq_doorbells.size() == 2);
    assert(g_txq_doorbells[0] == 16 && g_txq_doorbells[1] == 20);

    // When oactive is set and TX room returns, mwx_dma_tx_done restarts output.
    sc.sc_ic.ic_if.if_snd.oactive = true;
    g_tx_has_room_val = true;
    g_tx_kick_calls = 0;
    mwx_dma_tx_done(&sc);
    assert(g_tx_kick_calls == 1);
    assert(!sc.sc_ic.ic_if.if_snd.oactive);

    delete[] sc.sc_txq.mq_data;
    delete[] sc.sc_txq.mq_desc;
}

static void test_rx_amsdu_non_data_preserve() {
    mwx_softc sc{};
    mbuf_list ml{};
    const uint8_t ap[6] = {0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0x01};
    const uint8_t other[6] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66};
    g_amsdu_add_calls = g_amsdu_flush_calls = g_rx_deliver_calls = 0;

    // 1. First A-MSDU subframe arrives.
    mbuf *sub1 = new mbuf();
    sub1->len = 64;
    auto *w1 = mtod(sub1, ieee80211_frame*);
    w1->i_fc[0] = IEEE80211_FC0_TYPE_DATA;
    memcpy(w1->i_addr2, ap, 6);
    g_next_rx_flags = MWX_RXI_AMSDU_MASK;
    mwx_rx(&sc, sub1, &ml);
    assert(sc.sc_amsdu_n == 1 && g_amsdu_flush_calls == 0);

    // 2. Neighbor Beacon (mgmt) & Ctrl frame must NOT prematurely flush pending A-MSDU.
    mbuf *bcn = new mbuf();
    bcn->len = 64;
    auto *wb = mtod(bcn, ieee80211_frame*);
    wb->i_fc[0] = IEEE80211_FC0_TYPE_MGT;
    memcpy(wb->i_addr2, other, 6);
    g_next_rx_flags = 0;
    mwx_rx(&sc, bcn, &ml);
    assert(sc.sc_amsdu_n == 1 && g_amsdu_flush_calls == 0 && g_rx_deliver_calls == 1);

    // 3. Normal non-AMSDU Data frame from another TA must not flush; same-TA Data DOES flush.
    mbuf *d_other = new mbuf();
    d_other->len = 64;
    auto *wdo = mtod(d_other, ieee80211_frame*);
    wdo->i_fc[0] = IEEE80211_FC0_TYPE_DATA;
    memcpy(wdo->i_addr2, other, 6);
    mwx_rx(&sc, d_other, &ml);
    assert(sc.sc_amsdu_n == 1 && g_amsdu_flush_calls == 0);

    mbuf *d_ap = new mbuf();
    d_ap->len = 64;
    auto *wda = mtod(d_ap, ieee80211_frame*);
    wda->i_fc[0] = IEEE80211_FC0_TYPE_DATA;
    memcpy(wda->i_addr2, ap, 6);
    mwx_rx(&sc, d_ap, &ml);
    assert(sc.sc_amsdu_n == 0 && g_amsdu_flush_calls == 1 && g_rx_deliver_calls == 3);
}

int main() {
    test_stream_caps();
    test_intr_and_rx_budget();
    test_ba_rearm_throttle();
    test_edca_and_bgscan();
    test_aspm_disable();
    test_tx_doorbell_and_oactive_kick();
    test_rx_amsdu_non_data_preserve();
    puts("PASS throughput/latency fixes: 2SS MCS maps, lost-MSI race recheck, bounded RX batching, BA timeout throttling, EDCA QOS, bgscan deferral, ASPM/L1SS disable, batched TX doorbells & A-MSDU flush");
    return 0;
}
'''

out = Path(__file__).resolve().parent
cpp = out / "test-perf-fixes.cpp"
exe = out / "test-perf-fixes"
cpp.write_text("\n".join([
    harness, fn_stream, fn_rx_deq, fn_rx_done, fn_txwi_enq, fn_tx_done,
    fn_intr, fn_start, fn_rx, fn_aspm_dev, fn_aspm, fn_traffic, fn_bgscan,
    fn_set_tx, fn_rearm, tests,
]))
subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", str(cpp), "-o", str(exe)], check=True)
subprocess.run([str(exe)], check=True)
