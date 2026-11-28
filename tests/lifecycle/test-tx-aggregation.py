#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host tests for TX A-MPDU aggregation establishment.

Covers the two halves that together let a TX Block Ack session reach
IEEE80211_BA_AGREED:

1. ieee80211_can_use_ampdu: A-MPDU is allowed on open networks (no
   RSN/WEP). The injection guard previously made the clause always false
   there, so the ADDBA handshake never triggered and every frame went
   out as an individual PPDU (~10x throughput loss on MT7922). RSN and
   WEP behavior is unchanged, and the guard still refuses nodes that
   are not the associated AP.
2. The deferred BA handshake: mwx_ampdu_tx_start returns EBUSY and
   queues mwx_ba_task; the task programs the WTBL record and resolves
   the session with ieee80211_addba_resp_accept/refuse. (Only compiled
   when the source actually contains the deferred handshake; on an
   unpatched tree the part-1 assertions fail, which is the point.)
"""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
out_src = (root / "SimpleMtkWlan/hal_mwx/MtkMwx.cpp").read_text()
output_c = (root / "mtk80211/openbsd/net80211/ieee80211_output.c").read_text()


def extract(text: str, sig: str) -> str:
    start = text.index(sig)
    start = text.rfind("\n", 0, start - 1) + 1
    end = text.index("\n}\n", start) + 3
    return text[start:end]


fn_can = extract(output_c, "ieee80211_can_use_ampdu(struct ieee80211com *ic")
try:
    fn_start = extract(out_src, "mwx_ampdu_tx_start(struct ieee80211com *ic")
    fn_stop = extract(out_src, "mwx_ampdu_tx_stop(struct ieee80211com *ic")
    fn_task = extract(out_src, "mwx_ba_task(void *arg)")
    has_handshake = True
except ValueError:
    # Unpatched source: only the can_use_ampdu half is testable.
    fn_start = fn_stop = fn_task = ""
    has_handshake = False

harness = r'''
#define TEST_HARNESS 1
#include <cassert>
#include <cstdint>
#include <cstdio>

#define MWX_DEV_LOG(...) ((void)0)
#define DEVNAME(sc) "mwx0"

/* Values from mtk80211/openbsd/net80211 (verified against the headers). */
#define IEEE80211_NODE_HT           0x0400
#define IEEE80211_NODE_QOS          0x0002
#define IEEE80211_F_WEPON           0x00000100
#define IEEE80211_F_QOS             0x00080000
#define IEEE80211_F_RSNON           0x00200000
#define IEEE80211_C_TX_AMPDU        0x00010000
#define IEEE80211_PROTO_RSN         (1 << 0)
#define IEEE80211_M_STA             1
#define IEEE80211_BA_INIT           0
#define IEEE80211_BA_REQUESTED      1
#define IEEE80211_BA_AGREED         2
#define IEEE80211_ADDBA_AMSDU       0x0001
#define IEEE80211_STATUS_UNSPECIFIED 1
#define EOPNOTSUPP                  45
#define EBUSY                       16
#define IEEE80211_S_RUN             4
#define IEEE80211_S_INIT            0

struct ieee80211_tx_ba {
    int ba_state = IEEE80211_BA_INIT;
    uint16_t ba_params = 0;
    uint16_t ba_winsize = 0;
    uint16_t ba_winstart = 0;
};
struct ieee80211_node {
    uint32_t ni_flags = 0;
    int ni_rsnprotos = 0;
    ieee80211_tx_ba ni_tx_ba[8];
};
struct ieee80211com {
    void *ic_softc = nullptr;
    ieee80211_node *ic_bss = nullptr;
    int ic_opmode = IEEE80211_M_STA;
    unsigned ic_flags = 0;
    unsigned ic_caps = IEEE80211_C_TX_AMPDU;
    int ic_state = IEEE80211_S_RUN;
};

#ifdef HAS_HANDSHAKE
struct task { int queued = 0; };
static int task_add(void *, void *t) { ((task *)t)->queued++; return 1; }
static void task_del(void *, void *) {}
static int splnet() { return 0; }
static void splx(int) {}

static int g_mcu_rv = 0;
static int g_mcu_calls = 0;
static int g_mcu_tid = -1;
static int g_mcu_enable = -1;
static int g_accepts = 0;
static int g_refuses = 0;

struct mwx_softc;
int mwx_mcu_sta_ba(struct mwx_softc *, struct ieee80211_node *, uint8_t tid,
    uint16_t, uint16_t, int enable, int tx, int);
void ieee80211_addba_resp_accept(struct ieee80211com *, struct ieee80211_node *, uint8_t);
void ieee80211_addba_resp_refuse(struct ieee80211com *, struct ieee80211_node *, uint8_t, int);

struct mwx_softc {
    void *sc_nswq = nullptr;
    task sc_ba_task;
    uint8_t sc_txba_start = 0;
    uint8_t sc_txba_stop = 0;
    ieee80211com sc_ic;
    int sc_tx_amsdu = 1;
};

int mwx_mcu_sta_ba(struct mwx_softc *, struct ieee80211_node *, uint8_t tid,
    uint16_t, uint16_t, int enable, int tx, int)
{
    ++g_mcu_calls;
    g_mcu_tid = tid;
    g_mcu_enable = enable;
    return g_mcu_rv;
}
void ieee80211_addba_resp_accept(struct ieee80211com *, struct ieee80211_node *ni, uint8_t tid) {
    ++g_accepts;
    ni->ni_tx_ba[tid].ba_state = IEEE80211_BA_AGREED;
}
void ieee80211_addba_resp_refuse(struct ieee80211com *, struct ieee80211_node *, uint8_t, int) { ++g_refuses; }
#endif /* HAS_HANDSHAKE */
'''

part2 = r'''
#ifdef HAS_HANDSHAKE
static void test_deferred_handshake() {
    ieee80211_node bss{};
    mwx_softc sc{};
    sc.sc_nswq = &sc;
    sc.sc_ic.ic_softc = &sc;
    sc.sc_ic.ic_bss = &bss;
    sc.sc_ic.ic_state = IEEE80211_S_RUN;
    bss.ni_flags = IEEE80211_NODE_HT | IEEE80211_NODE_QOS;

    // tx_start defers: EBUSY, bit set, task queued, no MCU traffic yet.
    assert(mwx_ampdu_tx_start(&sc.sc_ic, &bss, 0) == EBUSY);
    assert(sc.sc_txba_start == 0x01);
    assert(sc.sc_ba_task.queued == 1);
    assert(g_mcu_calls == 0);

    // The task programs the WTBL record and resolves the session.
    g_mcu_rv = 0;
    mwx_ba_task(&sc);
    assert(g_mcu_calls == 1 && g_mcu_tid == 0 && g_mcu_enable == 1);
    assert(g_accepts == 1 && g_refuses == 0);
    assert(bss.ni_tx_ba[0].ba_state == IEEE80211_BA_AGREED);
    assert(sc.sc_txba_start == 0);

    // MCU failure path refuses instead.
    assert(mwx_ampdu_tx_start(&sc.sc_ic, &bss, 1) == EBUSY);
    g_mcu_rv = 5;
    mwx_ba_task(&sc);
    assert(g_refuses == 1 && g_accepts == 1);

    // tx_stop defers a teardown that reaches the firmware when running.
    assert(sc.sc_txba_start == 0);
    mwx_ampdu_tx_stop(&sc.sc_ic, &bss, 0);
    assert(sc.sc_txba_stop == 0x01);
    g_mcu_rv = 0;
    g_mcu_enable = -1;
    mwx_ba_task(&sc);
    assert(g_mcu_enable == 0); // disable record programmed
    assert(sc.sc_txba_stop == 0);

    // A foreign node is refused outright (no deferral, no bits).
    ieee80211_node other{};
    assert(mwx_ampdu_tx_start(&sc.sc_ic, &other, 0) == EOPNOTSUPP);
    assert(sc.sc_txba_start == 0);
    mwx_ampdu_tx_stop(&sc.sc_ic, &other, 0);
    assert(sc.sc_txba_stop == 0);

    // tid >= 8 is refused too.
    assert(mwx_ampdu_tx_start(&sc.sc_ic, &bss, 8) == EOPNOTSUPP);

    // Leaving S_RUN before the task runs: bits cleared, no accept/refuse.
    assert(mwx_ampdu_tx_start(&sc.sc_ic, &bss, 2) == EBUSY);
    sc.sc_ic.ic_state = IEEE80211_S_INIT;
    mwx_ba_task(&sc);
    assert(g_accepts == 1 && g_refuses == 1); // unchanged
    assert(sc.sc_txba_start == 0);
}
#endif /* HAS_HANDSHAKE */
'''

tests = r'''
static void test_can_use_ampdu() {
    ieee80211com ic{};
    ieee80211_node bss{}, other{};
    ic.ic_bss = &bss;

    // RSN network: the original guard passes.
    ic.ic_flags = IEEE80211_F_QOS | IEEE80211_F_RSNON;
    bss.ni_flags = IEEE80211_NODE_HT | IEEE80211_NODE_QOS;
    bss.ni_rsnprotos = IEEE80211_PROTO_RSN;
    assert(ieee80211_can_use_ampdu(&ic, &bss) != 0);

    // Open network (neither RSN nor WEP): must be allowed now.
    // This is the case that previously made every frame an individual PPDU.
    ic.ic_flags = IEEE80211_F_QOS;
    assert(ieee80211_can_use_ampdu(&ic, &bss) != 0);

    // WEP network stays excluded.
    ic.ic_flags = IEEE80211_F_QOS | IEEE80211_F_WEPON;
    assert(ieee80211_can_use_ampdu(&ic, &bss) == 0);

    // RSN announced but the peer has no RSN proto: still excluded.
    ic.ic_flags = IEEE80211_F_QOS | IEEE80211_F_RSNON;
    bss.ni_rsnprotos = 0;
    assert(ieee80211_can_use_ampdu(&ic, &bss) == 0);
    bss.ni_rsnprotos = IEEE80211_PROTO_RSN;

    // A node that is not the associated AP never gets A-MPDU.
    ic.ic_flags = IEEE80211_F_QOS;
    assert(ieee80211_can_use_ampdu(&ic, &other) == 0);

    // No HT: excluded regardless.
    bss.ni_flags &= ~IEEE80211_NODE_HT;
    assert(ieee80211_can_use_ampdu(&ic, &bss) == 0);
    bss.ni_flags |= IEEE80211_NODE_HT;

    // No TX_AMPDU capability: excluded.
    ic.ic_caps &= ~IEEE80211_C_TX_AMPDU;
    assert(ieee80211_can_use_ampdu(&ic, &bss) == 0);
    ic.ic_caps |= IEEE80211_C_TX_AMPDU;
}

int main() {
    test_can_use_ampdu();
#ifdef HAS_HANDSHAKE
    test_deferred_handshake();
#endif
    puts("PASS TX A-MPDU aggregation: open-network A-MPDU allowed (RSN/WEP guard kept)"
#ifdef HAS_HANDSHAKE
         ", deferred EBUSY handshake accepts/refuses via task"
#endif
    );
    return 0;
}
'''

out = Path(__file__).resolve().parent
cpp = out / "test-tx-aggregation.cpp"
exe = out / "test-tx-aggregation"
parts = [harness, fn_can]
if has_handshake:
    # Driver definitions first, then the test that calls them.
    parts += [fn_start, fn_stop, fn_task, part2]
parts += [tests]
cpp.write_text("\n".join(parts))
subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g",
                *(["-DHAS_HANDSHAKE"] if has_handshake else []),
                str(cpp), "-o", str(exe)], check=True)
subprocess.run([str(exe)], check=True)
