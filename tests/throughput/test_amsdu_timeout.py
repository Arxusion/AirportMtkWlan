#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise actual aggregation and timeout functions for cross-batch input, stale callbacks, and cleanup ownership."""
import argparse
import os
from pathlib import Path
import re
import subprocess

from test_amsdu_chain import PRELUDE


SUPPORT = r'''
#define MBUF_LIST_INITIALIZER() {}
#define IFF_RUNNING 1
#define IEEE80211_SEQ_SEQ_SHIFT 4
#define IEEE80211_ADDR_EQ(a,b) (memcmp(a,b,6)==0)
#define IEEE80211_ADDR_COPY(a,b) memcpy(a,b,6)
#define letoh16(x) (x)
uint64_t now_ticks=1;
uint64_t mach_absolute_time() { return now_ticks; }
void absolutetime_to_nanoseconds(uint64_t ticks, uint64_t *ns) { *ns=ticks; }
struct CTimeout { bool pending=false; uint64_t deadline=0; };
bool timer_fail=false;
int arms=0, inputs=0;
int timeout_add_msec(CTimeout **t, int ms) {
    assert(ms>0 && ms<=MWX_AMSDU_TIMEOUT_MS);
    ++arms;
    if(timer_fail || !*t) return 0;
    (*t)->pending=true;(*t)->deadline=now_ticks+ms*1000000ULL;return 1;
}
int timeout_del(CTimeout **t) { if(*t) (*t)->pending=false;return 1; }
int timeout_pending(CTimeout **t) { return *t && (*t)->pending; }
struct ifnet { unsigned if_flags=IFF_RUNNING; };
struct ieee80211_frame {
    uint8_t i_fc[2], i_dur[2], i_addr1[6], i_addr2[6], i_addr3[6], i_seq[2];
};
unsigned ieee80211_get_hdrlen(ieee80211_frame *) { return 26; }
'''

FIELDS = r'''
    CTimeout timer;
    CTimeout *sc_amsdu_to=&timer;
    uint64_t sc_amsdu_last_ticks=0;
    bool sc_detaching=false, sc_suspended=false;
    uint16_t sc_amsdu_seq=0;
    uint8_t sc_amsdu_ta[6]={};
    struct { ifnet ic_if; } sc_ic;
'''

MAIN = r'''
void append(mwx_softc &sc, int fmt, unsigned seq=1, uint8_t payload=0x55) {
    auto m=new mbuf(26+64);
    m->len=m->total=m->data.size();
    memset(m->data.data(),0,26);
    memset(m->data.data()+26,payload,64);
    auto wh=mtod(m,ieee80211_frame *);
    wh->i_seq[0]=(seq<<4)&255;wh->i_seq[1]=seq>>4;wh->i_addr2[0]=0xa;
    ieee80211_rxinfo rxi;
    rxi.rxi_flags|=uint32_t(fmt)<<MWX_RXI_AMSDU_SHIFT;
    mbuf_list ml;
    mwx_amsdu_add(&sc,m,&rxi,&ml);
}
void batch(mwx_softc &sc) { mbuf_list ml; mwx_amsdu_schedule(&sc,&ml); }
void fire(mwx_softc &sc) {
    assert(sc.timer.pending && now_ticks>=sc.timer.deadline);
    sc.timer.pending=false;mwx_amsdu_timeout(&sc);
}
void reset() {
    assert(live==0);
    delivered.clear();
    timer_fail=false;arms=inputs=0;now_ticks=1;
}
int main() {
    // Repeated MCU/TX completion batches must not split subframes sharing a sequence number.
    reset();mwx_softc sc;
    append(sc,MT_RXD4_FIRST_AMSDU_FRAME);batch(sc);
    auto deadline=sc.timer.deadline;
    for(int i=0;i<100;i++) { now_ticks+=1000;batch(sc); }
    assert(delivered.empty() && sc.sc_amsdu_n==1 && arms==1);
    assert(sc.timer.deadline==deadline);
    append(sc,MT_RXD4_LAST_AMSDU_FRAME,1,0x66);batch(sc);
    assert(sc.sc_amsdu_n==0 && live==0 && delivered.size()==1);
    assert(delivered[0].size()==26+128 && delivered[0][26]==0x55 && delivered[0][90]==0x66);
    now_ticks=deadline;fire(sc);assert(delivered.size()==1 && inputs==0);

    // Completion within a batch needs no timer and preserves single-buffer reassembly.
    reset();mwx_softc same;
    append(same,MT_RXD4_FIRST_AMSDU_FRAME);append(same,MT_RXD4_LAST_AMSDU_FRAME);batch(same);
    assert(arms==0 && delivered.size()==1 && live==0);

    // Later subframes extend the wait; stale callbacks must not deliver a new aggregate early.
    reset();mwx_softc changed;
    append(changed,MT_RXD4_FIRST_AMSDU_FRAME);batch(changed);
    now_ticks=1500001;append(changed,MT_RXD4_LAST_AMSDU_FRAME);
    append(changed,MT_RXD4_FIRST_AMSDU_FRAME,2);batch(changed);
    now_ticks=2000001;fire(changed);
    assert(delivered.size()==1 && changed.sc_amsdu_n==1);
    assert(changed.timer.pending && changed.timer.deadline==4000001);
    now_ticks=3000001;append(changed,MT_RXD4_MID_AMSDU_FRAME,2);batch(changed);
    now_ticks=4000001;fire(changed);
    assert(changed.sc_amsdu_n==2 && changed.timer.deadline==5000001);
    now_ticks=5000001;fire(changed);
    assert(changed.sc_amsdu_n==0 && !changed.timer.pending && live==0);
    assert(delivered.size()==2 && inputs==1);

    // A missing LAST permits one delivery; a new FIRST ends the previous aggregate as before.
    reset();mwx_softc missing;
    append(missing,MT_RXD4_FIRST_AMSDU_FRAME);batch(missing);
    now_ticks=missing.timer.deadline;fire(missing);
    assert(delivered.size()==1 && live==0);
    append(missing,MT_RXD4_FIRST_AMSDU_FRAME,2);batch(missing);
    append(missing,MT_RXD4_FIRST_AMSDU_FRAME,3);
    append(missing,MT_RXD4_LAST_AMSDU_FRAME,3);batch(missing);
    assert(delivered.size()==3 && live==0);
    mwx_amsdu_purge(&missing);

    // Stop/suspend/detach discard pending subframes; stale callbacks must not deliver or rearm.
    for(int reason=0;reason<3;reason++) {
        reset();mwx_softc ended;
        append(ended,MT_RXD4_FIRST_AMSDU_FRAME);batch(ended);
        if(reason==0) ended.sc_ic.ic_if.if_flags=0;
        if(reason==1) ended.sc_suspended=true;
        if(reason==2) ended.sc_detaching=true;
        now_ticks=ended.timer.deadline;fire(ended);
        assert(live==0 && delivered.empty() && !ended.timer.pending);
        mwx_amsdu_purge(&ended);assert(live==0 && !ended.timer.pending);
    }
    reset();mwx_softc stopped;
    append(stopped,MT_RXD4_FIRST_AMSDU_FRAME);batch(stopped);
    mwx_amsdu_purge(&stopped);mwx_amsdu_timeout(&stopped);
    assert(live==0 && delivered.empty() && !stopped.timer.pending);

    // Initial scheduling and callback rearming failures must release or deliver all held mbufs.
    for(bool rearm:{false,true}) {
        reset();mwx_softc failed;
        append(failed,MT_RXD4_FIRST_AMSDU_FRAME);
        if(rearm) {
            batch(failed);now_ticks=1500001;
            append(failed,MT_RXD4_MID_AMSDU_FRAME);batch(failed);
            timer_fail=true;now_ticks=2000001;fire(failed);
        } else { timer_fail=true;batch(failed); }
        assert(delivered.size()==1 && live==0 && failed.sc_amsdu_n==0);
        assert(!failed.timer.pending);
    }

    puts("PASS: complete cross-batch delivery, deadlines, stale callbacks, and cleanup/failure ownership");
}
'''


def function(text, name):
    start = text.index("\n" + name + "(")
    body = text.index("{", start)
    end = text.index("\n}\n", body) + 3
    return text[text.rfind("\n", 0, start - 1) + 1:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    source = args.source.resolve()
    text = (source / "SimpleMtkWlan/hal_mwx/MtkMwx.cpp").read_text()
    reg = (source / "SimpleMtkWlan/hal_mwx/if_mwxreg.h").read_text()
    defines = "\n".join(line for line in (text + reg).splitlines()
                         if re.match(r"#define\s+(MWX_AMSDU_(MAX_SUB|TIMEOUT_MS)|MWX_RXI_AMSDU_(MASK|SHIFT)|MT_RXD4_(FIRST|MID|LAST)_AMSDU_FRAME)\b", line))
    prelude = PRELUDE
    prelude = prelude.replace("int live,", defines + "\n" + SUPPORT + "\nint live,")
    prelude = prelude.replace("struct ieee80211_rxinfo { unsigned flags=0x1234; };",
                              "struct ieee80211_rxinfo { union { unsigned flags=0x1234; unsigned rxi_flags; }; };")
    prelude = prelude.replace("struct mbuf_list {};", "struct mbuf_list { int count=0; };\nbool ml_empty(mbuf_list *ml) { return ml->count==0; }\nvoid if_input(ifnet *, mbuf_list *ml) { ++inputs;ml->count=0; }")
    prelude = prelude.replace("struct mwx_softc {", "struct mwx_softc {" + FIELDS)
    prelude = prelude.replace("mbuf_list *) {", "mbuf_list *ml) {\n    ++ml->count;")
    prelude = prelude.replace("size_t mbuf_len(mbuf *m)", "size_t mbuf_pkthdr_len(mbuf *m) { return m->total; }\nsize_t mbuf_len(mbuf *m)")
    functions = ["mwx_amsdu_flush", "mwx_amsdu_purge", "mwx_amsdu_arm", "mwx_amsdu_schedule",
                 "mwx_amsdu_timeout", "mwx_amsdu_add"]
    out = Path(os.environ.get("MTK_TEST_BUILD_DIR", Path(__file__).resolve().parents[2] / "build/tests")) / "amsdu-timeout"
    out.mkdir(parents=True, exist_ok=True)
    cpp = out / "test.cpp"
    cpp.write_text(prelude + "\n".join(function(text, name) for name in functions) + MAIN)
    binary = out / "test"
    subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
