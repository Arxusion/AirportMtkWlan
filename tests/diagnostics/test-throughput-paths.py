#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run real HAL functions with diagnostics enabled, checking counters and existing ownership contracts."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/throughput"))
import test_amsdu_chain as chain
import test_amsdu_timeout as timeout
import test_tx_wtbl_ba as ba

PERF = r'''
#include <cstdint>
#define MTK_PERF 1
#define MTK_PERF_HOST 1
uint64_t mach_absolute_time();
#include <HAL/MtkPerf.hpp>
uint64_t mp_values[mp_count]={};
'''

TX_SUPPORT = r'''
#include <cassert>
#include <cstdio>
uint64_t now_ticks=1;
uint64_t mach_absolute_time() { return now_ticks; }
using u_int=unsigned;
struct ifqueue { bool active=false; };
struct ifnet { ifqueue if_snd; };
struct mwx_queue { int free=0; };
struct mwx_softc {
    struct { ifnet ic_if; } sc_ic;
    struct { unsigned mt_nfree=0; } sc_txwi;
    mwx_queue sc_txq;
    uint64_t sc_tx_pause_started=0;
};
int starts=0;
int mwx_dma_free_slots(mwx_queue *q) { return q->free; }
bool ifq_is_oactive(ifqueue *q) { return q->active; }
void ifq_clr_oactive(ifqueue *q) { q->active=false; }
void mwx_start(ifnet *) { ++starts; }
'''

TX_MAIN = r'''
int main() {
    mwx_softc sc;
    mwx_tx_kick(&sc);
    assert(starts==0 && mp_values[mp_tx_pause_samples]==0);
    sc.sc_ic.ic_if.if_snd.active=true;
    sc.sc_txwi.mt_nfree=100;
    mwx_tx_pause_begin(&sc);
    assert(mp_values[mp_tx_full_ring]==1 && mp_values[mp_tx_full_token]==0);
    now_ticks=1001; mwx_tx_kick(&sc);
    assert(mp_values[mp_tx_wake_below_threshold]==0 && starts==0);
    sc.sc_txq.free=31; mwx_tx_kick(&sc);
    assert(mp_values[mp_tx_wake_below_threshold]==1 && starts==0);
    sc.sc_txq.free=32; now_ticks=2001; mwx_tx_kick(&sc);
    assert(starts==1 && !sc.sc_ic.ic_if.if_snd.active && sc.sc_tx_pause_started==0);
    assert(mp_values[mp_tx_pause_samples]==1 && mp_values[mp_tx_pause_ticks]==2000);
    sc.sc_txwi.mt_nfree=0; mwx_tx_pause_begin(&sc);
    assert(mp_values[mp_tx_full_token]==1 && mp_values[mp_tx_full_ring]==1);
    now_ticks=2101; mwx_tx_pause_end(&sc,false); mwx_tx_pause_end(&sc,false);
    assert(mp_values[mp_tx_pause_abort]==1 && mp_values[mp_tx_pause_samples]==2);
    assert(mp_values[mp_tx_pause_ticks]==2100 && mp_values[mp_tx_pause_max_ticks]==2000);
    sc.sc_txq.free=0; mwx_tx_pause_begin(&sc);
    assert(mp_values[mp_tx_full_token]==2 && mp_values[mp_tx_full_ring]==2);
    mwx_tx_pause_end(&sc,false);
    puts("PASS: TX resource causes, wake threshold, pause timing, and stop cleanup");
}
'''


def add_after(text, marker, check):
    if marker not in text:
        raise ValueError("Missing fixture checkpoint: " + marker)
    return text.replace(marker, marker + "\n" + check, 1)


def main():
    output = Path(os.environ.get("MTK_TEST_BUILD_DIR", ROOT / "build/tests")) / "throughput-paths"
    output.mkdir(parents=True, exist_ok=True)
    os.environ["MTK_TEST_BUILD_DIR"] = str(output)
    # Reuse the existing real-function harnesses, adding counter assertions only.
    # CPATH supplies the production header to their compiler invocations.
    os.environ["CPATH"] = str(ROOT / "include") + (
        os.pathsep + os.environ["CPATH"] if os.environ.get("CPATH") else "")
    sys.argv = [sys.argv[0], "--source", str(ROOT)]
    chain.PRELUDE = PERF + "uint64_t mach_absolute_time() { return 1; }\n" + chain.PRELUDE
    marker = '    puts("PASS: single/chained'
    assert marker in chain.MAIN
    chain.MAIN = chain.MAIN.replace(marker, '''    assert(mp_values[mp_rx_amsdu_chain]>0);
    assert(mp_values[mp_rx_amsdu_alloc_fail]>0 && mp_values[mp_rx_amsdu_copy_fail]>0);
''' + marker)
    chain.main()

    timeout.PRELUDE = PERF + timeout.PRELUDE
    timeout.FIELDS += "\n    bool sc_amsdu_cross_batch=false;\n"
    timeout.MAIN = add_after(timeout.MAIN, "timer_fail=false;arms=inputs=0;now_ticks=1;",
                            "    memset(mp_values,0,sizeof(mp_values));")
    for marker, check in (
        ("assert(sc.sc_amsdu_n==0 && live==0 && delivered.size()==1);",
         "assert(mp_values[mp_rx_amsdu_sub]==2 && mp_values[mp_rx_amsdu_cross_batch_complete]==1);"),
        ("assert(arms==0 && delivered.size()==1 && live==0);",
         "assert(mp_values[mp_rx_amsdu_cross_batch_complete]==0 && mp_values[mp_rx_amsdu_timer_flush]==0);"),
        ("assert(delivered.size()==1 && live==0);",
         "assert(mp_values[mp_rx_amsdu_timer_flush]==1);"),
        ("assert(live==0 && delivered.empty() && !ended.timer.pending);",
         "assert(mp_values[mp_rx_amsdu_purge_sub]==1 && !ended.sc_amsdu_cross_batch);"),
        ("assert(delivered.size()==1 && live==0 && failed.sc_amsdu_n==0);",
         "assert(mp_values[mp_rx_amsdu_timer_fail]==1 && mp_values[mp_rx_amsdu_timer_flush]==0);"),
    ):
        timeout.MAIN = add_after(timeout.MAIN, marker, "    " + check)
    timeout.main()

    ba.PRELUDE = PERF + "uint64_t mach_absolute_time() { return 1; }\n" + ba.PRELUDE
    ba.MAIN = add_after(ba.MAIN, "messages.clear();", "    memset(mp_values,0,sizeof(mp_values));")
    for marker, check in (
        ("assert(messages[0]==wt && messages[1]==sta);",
         "assert(mp_values[mp_tx_wtbl_ba_enable_submit]==unsigned(enable));\n"
         "assert(mp_values[mp_tx_wtbl_ba_disable_submit]==unsigned(!enable));"),
        ("assert(live==0 && messages.size()==1);",
         "assert(mp_values[mp_tx_wtbl_ba_submit_fail]==1 && mp_values[mp_tx_sta_ba_submit_fail]==0);"),
        ("// TX counters checked by diagnostics: one WTBL submit failure, one STA submit failure.",
         "assert(mp_values[mp_tx_wtbl_ba_submit_fail]==0 && "
         "mp_values[mp_tx_sta_ba_submit_fail]==1);"),
        ("assert(messages[0]==rwt && messages[1]==rsta);",
         "assert(mp_values[mp_tx_wtbl_ba_enable_submit]==0 &&\n"
         "    mp_values[mp_tx_wtbl_ba_disable_submit]==0 &&\n"
         "    mp_values[mp_tx_wtbl_ba_submit_fail]==0 && mp_values[mp_tx_sta_ba_submit_fail]==0);\n"
         "    reset();assert(mwx_mcu_sta_ba(&sc,&node.ni,3,0x123,64,0,0,0)==0);\n"
         "    assert(mp_values[mp_tx_wtbl_ba_enable_submit]==0 &&\n"
         "    mp_values[mp_tx_wtbl_ba_disable_submit]==0 && messages.size()==2);"),
    ):
        ba.MAIN = add_after(ba.MAIN, marker, "    " + check)
    ba.main()

    source = (ROOT / "SimpleMtkWlan/hal_mwx/MtkMwx.cpp").read_text()
    functions = ("mwx_tx_has_room", "mwx_tx_pause_begin", "mwx_tx_pause_end", "mwx_tx_kick")
    cpp, binary = output / "tx.cpp", output / "tx"
    cpp.write_text(PERF + TX_SUPPORT + "\n".join(timeout.function(source, f) for f in functions) + TX_MAIN)
    subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g",
                    str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
