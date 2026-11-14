from pathlib import Path
import re
import subprocess

b = Path(__file__).resolve().parents[2]
out = Path(__file__).resolve().parent
src = (b / "SimpleMtkWlan/hal_mwx/MtkMwx.cpp").read_text()

def extract_fn(sig: str) -> str:
    idx = src.index(sig)
    start = src.index("{", idx)
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[idx : i + 1]
    raise RuntimeError(f"Unmatched braces for {sig}")

init_hw_fn = extract_fn("int\nmwx_init_hw(struct ifnet *ifp)")
stop_fn = extract_fn("void\nmwx_stop(struct ifnet *ifp)")
reset_task_fn = extract_fn("void\nmwx_reset_task(void *arg)")

# Strip NVRAM/WCL/EDCA-only calls not needed in this state-machine stub
pre = r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#define IFF_UP 0x1
#define IFF_RUNNING 0x40
#define MWX_FLAG_SCANNING 0x01
#define IEEE80211_F_BGSCAN 0x1
#define IEEE80211_F_ASCAN 0x2
#define IEEE80211_M_STA 1
#define IEEE80211_M_MONITOR 8
#define IEEE80211_FC0_SUBTYPE_DEAUTH 0xc0
#define IEEE80211_REASON_AUTH_LEAVE 3
#define IEEE80211_ADDR_EQ(a,b) (memcmp((a),(b),6)==0)
#define IEEE80211_ADDR_COPY(d,s) memcpy((d),(s),6)
#define ether_sprintf(a) "00:11:22:33:44:55"
#define DPRINTF(...) ((void)0)
#define MWX_DEV_LOG(...) ((void)0)
#define KASSERT(x) assert(x)
#define M_DEVBUF 0
#define MT_DMA_DCR0(x) 0
#define MT_DMA_DCR0_RXD_G5_EN 1
#define MT_WF_RFCR_DROP_OTHER_UC 1
#define MT_WF_RFCR(x) 1
#define MCU_EXT_CMD_SET_RX_PATH 1
#define IEEE80211_EVT_DRIVER_STOPPED 1
#define AIRPORT_WCL 1

enum ieee80211_state {
    IEEE80211_S_INIT = 0,
    IEEE80211_S_SCAN = 1,
    IEEE80211_S_AUTH = 2,
    IEEE80211_S_ASSOC = 3,
    IEEE80211_S_RUN = 4,
};

struct ieee80211_node { void *ni_chan; };
struct ifq_t { int d; };
struct ifnet { void *if_softc; int if_flags; int if_timer; ifq_t if_snd; };
struct arpcom { uint8_t ac_enaddr[6]; };
struct ieee80211com {
    ifnet ic_if;
    int ic_opmode;
    ieee80211_state ic_state;
    ieee80211_node *ic_bss;
    void *ic_ibss_chan;
    uint8_t ic_myaddr[6];
    uint32_t ic_flags;
    bool ic_wcl_scan_requested, ic_wcl_scan_active, ic_wcl_scan_idle;
    int ic_wcl_scan_ssid_length;
    void (*ic_event_handler)(ieee80211com *, int, void *);
};
struct mwx_node { uint16_t wcid; };
struct mwx_vif { mwx_node vif_mn; };
struct mwx_softc {
    ieee80211com sc_ic;
    mwx_vif sc_vif;
    void *sc_nswq, *sc_reset_to, *sc_intr_to;
    int sc_newstate_task, sc_bgscan_done_task, sc_setkey_task, sc_reset_task, sc_scan_task, sc_edca_task;
    int sc_intr_pending;
    void *sc_bgscan_arg;
    size_t sc_bgscan_arg_size;
    unsigned sc_flags;
    int sc_sta_added;
    int sc_fw_loaded;
    int sc_hard_reset;
    int sc_resetting;
    int sc_coredump_cnt;
    uint64_t sc_last_bgscan_ns;
    ieee80211_state sc_ns_state;
    uint32_t sc_rxfilter;
    int (*sc_newstate)(ieee80211com *, ieee80211_state, int);
};

static const uint8_t etheranyaddr[6] = {0};
static void *systq = (void*)1;
static std::vector<std::string> calls;
static int g_preinit_rv = 0;
static int g_mac_enable_fail_once = 0;
static int g_mac_enable_always_fail = 0;
static int g_bss_off_rv = 0;
static int g_uni_add_dev_rv = 0;

static inline int splnet() { return 0; }
static inline void splx(int) {}
static inline void delay(int) {}
static inline void free(void *, int, size_t) {}
static inline void task_del(void *, void *) {}
static inline void timeout_del(void *) {}
static inline void mwx_amsdu_purge(mwx_softc *sc) {
    assert(!(sc->sc_ic.ic_if.if_flags & IFF_RUNNING));
    calls.push_back("amsdu_purge");
}
static inline void ifq_clr_oactive(void *) {}
static inline void mwx_start(ifnet *) {}
static inline void mwx_set(mwx_softc *, int, int) {}
static inline void mwx_clear(mwx_softc *, int, int) {}
static inline void mwx_write(mwx_softc *, int, uint32_t) {}
static inline int IEEE80211_SEND_MGMT(ieee80211com *, ieee80211_node *, int, int) { calls.push_back("deauth"); return 0; }
static inline int ieee80211_new_state(ieee80211com *, ieee80211_state, int) { return 0; }
static inline void ieee80211_begin_scan(ifnet *) { calls.push_back("begin_scan"); }

static int mwx_init(ifnet *ifp);
static int mwx_preinit(mwx_softc *sc) {
    calls.push_back("preinit");
    if (g_preinit_rv != 0) return g_preinit_rv;
    sc->sc_hard_reset = 0;
    sc->sc_fw_loaded = 1;
    return 0;
}
static int mwx_mcu_set_deep_sleep(mwx_softc *, int en) { calls.push_back(en ? "deep_sleep_on" : "deep_sleep_off"); return 0; }
static int mt7921_mcu_set_mac_enable(mwx_softc *, int, int en) {
    calls.push_back(en ? "mac_enable_on" : "mac_enable_off");
    if (en && g_mac_enable_always_fail) return 35;
    if (en && g_mac_enable_fail_once > 0) { g_mac_enable_fail_once--; return 35; }
    return 0;
}
static int mt7921_mcu_set_channel_domain(mwx_softc *) { return 0; }
static int mt7921_mcu_set_chan_info(mwx_softc *, int) { return 0; }
static int mt7921_set_channel(mwx_softc *) { return 0; }
static int mt7921_mcu_set_rate_txpower(mwx_softc *) { return 0; }
static void mt7921_mac_reset_counters(mwx_softc *) {}
static void mwx_mac_wtbl_update(mwx_softc *, uint16_t) {}
static int mt7921_mcu_uni_add_dev(mwx_softc *, mwx_vif *, mwx_node *, int en) {
    calls.push_back(en ? "uni_add_dev_on" : "uni_add_dev_off");
    return en ? 0 : g_uni_add_dev_rv;
}
static int mt7921_mcu_set_tx(mwx_softc *, mwx_vif *) { return 0; }
static int mt7921_mcu_set_sniffer(mwx_softc *, int) { return 0; }
static int mt7921_mcu_set_beacon_filter(mwx_softc *, int) { return 0; }
static int mt7921_mcu_hw_scan_cancel(mwx_softc *) { calls.push_back("scan_cancel"); return 0; }
static int mt7921_mcu_set_associated_bss(mwx_softc *, int en) {
    calls.push_back(en ? "bss_on" : "bss_off");
    return en ? 0 : g_bss_off_rv;
}
static int mt7921_mac_sta_update(mwx_softc *, ieee80211_node *, int add, int) {
    calls.push_back(add ? "sta_add" : "sta_remove");
    return 0;
}
static int stub_newstate(ieee80211com *ic, ieee80211_state st, int) { ic->ic_state = st; calls.push_back("newstate_init"); return 0; }
"""

post = r"""
static int mwx_init(ifnet *ifp) { return mwx_init_hw(ifp); }
static int idx_of(const std::string &s) {
    for (size_t i = 0; i < calls.size(); ++i)
        if (calls[i] == s) return (int)i;
    return -1;
}

int main() {
    ieee80211_node bss{};
    auto init_sc = [&](mwx_softc &sc) {
        memset(&sc, 0, sizeof(sc));
        sc.sc_ic.ic_if.if_softc = &sc;
        sc.sc_ic.ic_opmode = IEEE80211_M_STA;
        sc.sc_ic.ic_bss = &bss;
        sc.sc_vif.vif_mn.wcid = 1;
        sc.sc_newstate = stub_newstate;
    };

    // 1. mwx_stop while RUN must remove BSS + peer STA before uni_add_dev_off, and mac_enable_off before deep_sleep_on
    {
        mwx_softc sc; init_sc(sc);
        sc.sc_fw_loaded = 1; sc.sc_sta_added = 1;
        sc.sc_ic.ic_state = IEEE80211_S_RUN;
        sc.sc_ic.ic_if.if_flags = IFF_UP | IFF_RUNNING;
        calls.clear();
        mwx_stop(&sc.sc_ic.ic_if);
        assert(sc.sc_sta_added == 0);
        assert(idx_of("amsdu_purge") >= 0 && idx_of("amsdu_purge") < idx_of("bss_off"));
        assert(idx_of("bss_off") >= 0 && idx_of("sta_remove") > idx_of("bss_off"));
        assert(idx_of("uni_add_dev_off") > idx_of("sta_remove"));
        assert(idx_of("mac_enable_off") > idx_of("uni_add_dev_off"));
        assert(idx_of("deep_sleep_on") > idx_of("mac_enable_off"));
        assert(sc.sc_fw_loaded == 1 && sc.sc_hard_reset == 0);
    }

    // 2. If firmware coredumps/fails during stop, sc_fw_loaded clears and sc_hard_reset is armed for next enable
    {
        mwx_softc sc; init_sc(sc);
        sc.sc_fw_loaded = 1; sc.sc_sta_added = 1;
        sc.sc_ic.ic_state = IEEE80211_S_RUN;
        sc.sc_ic.ic_if.if_flags = IFF_UP | IFF_RUNNING;
        g_bss_off_rv = 35;
        calls.clear();
        mwx_stop(&sc.sc_ic.ic_if);
        g_bss_off_rv = 0;
        assert(sc.sc_fw_loaded == 0 && sc.sc_hard_reset == 1);
        assert(idx_of("uni_add_dev_off") == -1);
    }

    // 3. mwx_reset_task while interface is down keeps sc_hard_reset armed and clears sc_fw_loaded
    {
        mwx_softc sc; init_sc(sc);
        sc.sc_fw_loaded = 1; sc.sc_hard_reset = 1; sc.sc_resetting = 1;
        sc.sc_ic.ic_if.if_flags = 0;
        calls.clear();
        mwx_reset_task(&sc);
        assert(sc.sc_fw_loaded == 0 && sc.sc_hard_reset == 1 && sc.sc_resetting == 0);
    }

    // 4. Warm mwx_init_hw failure (error=35) recovers via one firmware reload + retry
    {
        mwx_softc sc; init_sc(sc);
        sc.sc_fw_loaded = 1; sc.sc_hard_reset = 0;
        sc.sc_ic.ic_if.if_flags = IFF_UP;
        g_mac_enable_fail_once = 1;
        calls.clear();
        assert(mwx_init_hw(&sc.sc_ic.ic_if) == 0);
        assert(idx_of("preinit") >= 0);
        assert(sc.sc_fw_loaded == 1 && sc.sc_hard_reset == 0);
    }

    // 5. Cold mwx_init_hw persistent failure does not loop forever
    {
        mwx_softc sc; init_sc(sc);
        sc.sc_fw_loaded = 1; sc.sc_hard_reset = 0;
        sc.sc_ic.ic_if.if_flags = IFF_UP;
        g_mac_enable_always_fail = 1;
        calls.clear();
        assert(mwx_init_hw(&sc.sc_ic.ic_if) == 35);
        g_mac_enable_always_fail = 0;
    }

    puts("PASS actual mwx_stop / mwx_init_hw / mwx_reset_task power-cycle and coredump recovery invariants.");
    return 0;
}
"""

p = out / "test-power-cycle.cpp"
p.write_text(pre + "\n" + init_hw_fn + "\n" + stop_fn + "\n" + reset_task_fn + "\n" + post)
exe = p.with_suffix("")
subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", str(p), "-o", str(exe)], check=True)
r = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
(out / "test-power-cycle-result.txt").write_text(r.stdout + r.stderr)
print(r.stdout + r.stderr, end="")
