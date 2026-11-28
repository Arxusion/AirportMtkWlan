#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The A-MSDU aggregate identity must include the TID.

The hardware splitter delivers subframes of all TIDs into the same ring.
The identity used to be seq + hdrlen + addr2, so two TIDs whose first
subframes carry the same sequence number were reassembled into one
aggregate. Subframes of a different TID must flush the pending aggregate
and start a new one instead of being appended to it.
"""
import argparse
import os
import re
from pathlib import Path
import subprocess

from test_amsdu_chain import PRELUDE

SUPPORT = r'''
#define IEEE80211_SEQ_SEQ_SHIFT 4
#define IEEE80211_FC0_TYPE_MASK 0x0c
#define IEEE80211_FC0_TYPE_DATA 0x08
#define IEEE80211_FC0_SUBTYPE_QOS 0x80
#define IEEE80211_QOS_TID 0x000f
#define IEEE80211_ADDR_EQ(a,b) (memcmp(a,b,6)==0)
#define IEEE80211_ADDR_COPY(a,b) memcpy(a,b,6)
#define letoh16(x) (x)
uint64_t mach_absolute_time() { return 1; }
struct CTimeout { bool pending=false; };
int timeout_del(CTimeout **t) { return 1; }
struct ieee80211_frame {
    uint8_t i_fc[2], i_dur[2], i_addr1[6], i_addr2[6], i_addr3[6], i_seq[2], i_qos[2];
};
unsigned ieee80211_get_hdrlen(ieee80211_frame *wh) {
    return ((wh->i_fc[0] & IEEE80211_FC0_TYPE_MASK) == IEEE80211_FC0_TYPE_DATA &&
            (wh->i_fc[0] & IEEE80211_FC0_SUBTYPE_QOS)) ? 26 : 24;
}
int ieee80211_has_qos(ieee80211_frame *wh) {
    return (wh->i_fc[0] & (IEEE80211_FC0_TYPE_MASK | IEEE80211_FC0_SUBTYPE_QOS)) ==
        (IEEE80211_FC0_TYPE_DATA | IEEE80211_FC0_SUBTYPE_QOS);
}
unsigned ieee80211_get_qos(ieee80211_frame *wh) {
    return letoh16(*(const uint16_t *)wh->i_qos) & IEEE80211_QOS_TID;
}
'''

FIELDS = r'''
    CTimeout timer;
    CTimeout *sc_amsdu_to=&timer;
    uint64_t sc_amsdu_last_ticks=0;
    uint16_t sc_amsdu_seq=0;
    uint16_t sc_amsdu_tid=0;
    uint8_t sc_amsdu_ta[6]={};
'''

MAIN = r'''
static mbuf_list ml;
static int delivered_expected = 0;

/* One hardware-split A-MSDU subframe with a 40-byte payload. */
static void sub(mwx_softc &sc, int fmt, unsigned seq, int tid, bool qos=true) {
    u_int hl = qos ? 26 : 24;
    auto m = new mbuf(hl + 40);
    m->len = m->total = m->data.size();
    memset(m->data.data(), 0, hl);
    memset(m->data.data() + hl, 0x55, 40);
    auto wh = mtod(m, ieee80211_frame *);
    wh->i_fc[0] = qos ? (IEEE80211_FC0_TYPE_DATA | IEEE80211_FC0_SUBTYPE_QOS)
                      : IEEE80211_FC0_TYPE_DATA;
    wh->i_seq[0] = (seq << 4) & 255; wh->i_seq[1] = seq >> 4;
    if (qos) { wh->i_qos[0] = (uint8_t)tid; wh->i_qos[1] = 0; }
    wh->i_addr2[0] = 0xa0; wh->i_addr2[1] = 0x01;
    ieee80211_rxinfo rxi;
    rxi.rxi_flags |= uint32_t(fmt) << MWX_RXI_AMSDU_SHIFT;
    mwx_amsdu_add(&sc, m, &rxi, &ml);
}

static void reset() {
    assert(live == 0);
    delivered.clear();
    ml.count = 0;
}

static void check_cleared(mwx_softc &sc) {
    assert(sc.sc_amsdu_n == 0 && live == 0);
    for (auto m : sc.sc_amsdu_sub) assert(!m);
}

/* delivered[] grows by one per flush; sizes are header + payloads (+ 4-byte
 * padding between subframes). */
static void expect_delivered(size_t n, std::vector<size_t> sizes, u_int hl = 26) {
    assert(delivered.size() == n);
    for (size_t i = 0; i < n; i++)
        assert(delivered[i].size() == sizes[i]);
    /* header is rebuilt by flush with the real fc/seq/qos; beyond it only
     * original payload 0x55 and zero padding are allowed. */
    for (auto &d : delivered)
        for (size_t j = hl; j < d.size(); ++j)
            assert(d[j] == 0x55 || d[j] == 0);
}

int main() {
    // 1. Same TID continues the aggregate: FIRST+MID+LAST of tid 3, seq 1.
    reset();mwx_softc sc;
    sub(sc, MT_RXD4_FIRST_AMSDU_FRAME, 1, 3);
    sub(sc, MT_RXD4_MID_AMSDU_FRAME, 1, 3);
    assert(sc.sc_amsdu_n == 2 && delivered.empty() && sc.sc_amsdu_tid == 3);
    sub(sc, MT_RXD4_LAST_AMSDU_FRAME, 1, 3);
    check_cleared(sc);
    expect_delivered(1, {26 + 40 + 40 + 40});

    // 2. THE BUG: another TID with the same seq must NOT join the aggregate.
    //    tid 3 FIRST(seq 5), then tid 0 MID(seq 5): the pending aggregate is
    //    flushed and the foreign subframe starts its own aggregate.
    reset();mwx_softc mix;
    sub(mix, MT_RXD4_FIRST_AMSDU_FRAME, 5, 3);
    assert(mix.sc_amsdu_n == 1 && mix.sc_amsdu_tid == 3);
    sub(mix, MT_RXD4_MID_AMSDU_FRAME, 5, 0);
    assert(mix.sc_amsdu_n == 1 && mix.sc_amsdu_tid == 0 && delivered.size() == 1);
    expect_delivered(1, {26 + 40});
    sub(mix, MT_RXD4_LAST_AMSDU_FRAME, 5, 0);
    check_cleared(mix);
    expect_delivered(2, {26 + 40, 26 + 40 + 40});

    // 3. Different TID with FIRST still flushes (pre-existing rule) and the
    //    new aggregate carries the new TID: same seq again.
    reset();mwx_softc firsts;
    sub(firsts, MT_RXD4_FIRST_AMSDU_FRAME, 7, 3);
    sub(firsts, MT_RXD4_FIRST_AMSDU_FRAME, 7, 1);
    assert(firsts.sc_amsdu_n == 1 && firsts.sc_amsdu_tid == 1 && delivered.size() == 1);
    sub(firsts, MT_RXD4_MID_AMSDU_FRAME, 7, 1);
    assert(firsts.sc_amsdu_n == 2);
    sub(firsts, MT_RXD4_LAST_AMSDU_FRAME, 7, 1);
    check_cleared(firsts);
    expect_delivered(2, {26 + 40, 26 + 40 + 40 + 40});

    // 4. TIDs 0 and non-QoS both map to 0: same-seq non-QoS after QoS tid 0
    //    still flushes on hdrlen (26 vs 24, pre-existing rule), but two
    //    non-QoS subframes with the same seq continue to aggregate.
    reset();mwx_softc nonqos;
    sub(nonqos, MT_RXD4_FIRST_AMSDU_FRAME, 9, 0, false);
    sub(nonqos, MT_RXD4_MID_AMSDU_FRAME, 9, 0, false);
    assert(nonqos.sc_amsdu_n == 2 && nonqos.sc_amsdu_tid == 0 && delivered.empty());
    sub(nonqos, MT_RXD4_LAST_AMSDU_FRAME, 9, 0, false);
    check_cleared(nonqos);
    expect_delivered(1, {24 + 40 + 40 + 40}, 24);

    // 5. purge between aggregates leaves a clean slate.
    reset();mwx_softc pg;
    sub(pg, MT_RXD4_FIRST_AMSDU_FRAME, 11, 2);
    mwx_amsdu_purge(&pg);
    check_cleared(pg);
    sub(pg, MT_RXD4_FIRST_AMSDU_FRAME, 11, 4);
    assert(pg.sc_amsdu_n == 1 && pg.sc_amsdu_tid == 4 && delivered.empty());
    mwx_amsdu_purge(&pg);
    check_cleared(pg);

    puts("PASS: A-MSDU aggregate identity includes TID (same-seq foreign TID flushes, same TID continues)");
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    source = args.source.resolve()
    text = (source / "SimpleMtkWlan/hal_mwx/MtkMwx.cpp").read_text()
    reg = (source / "SimpleMtkWlan/hal_mwx/if_mwxreg.h").read_text()
    defines = "\n".join(line for line in (text + reg).splitlines()
                        if re.match(r"#define\s+(MWX_AMSDU_MAX_SUB|MWX_RXI_AMSDU_(MASK|SHIFT)|MT_RXD4_(FIRST|MID|LAST)_AMSDU_FRAME)\b", line))
    prelude = PRELUDE
    prelude = prelude.replace("int live,", defines + "\n" + SUPPORT + "\nint live,")
    prelude = prelude.replace("struct ieee80211_rxinfo { unsigned flags=0x1234; };",
                              "struct ieee80211_rxinfo { union { unsigned flags=0x1234; unsigned rxi_flags; }; };")
    prelude = prelude.replace("struct mbuf_list {};", "struct mbuf_list { int count=0; };")
    prelude = prelude.replace("struct mwx_softc {", "struct mwx_softc {" + FIELDS)
    prelude = prelude.replace("mbuf_list *) {", "mbuf_list *ml) {\n    ++ml->count;")
    prelude = prelude.replace("size_t mbuf_len(mbuf *m)", "size_t mbuf_pkthdr_len(mbuf *m) { return m->total; }\nsize_t mbuf_len(mbuf *m)")
    functions = ["mwx_amsdu_flush", "mwx_amsdu_purge", "mwx_amsdu_add"]

    def function(t, name):
        start = t.index("\n" + name + "(")
        body = t.index("{", start)
        end = t.index("\n}\n", body) + 3
        return t[t.rfind("\n", 0, start - 1) + 1:end]

    out = Path(os.environ.get("MTK_TEST_BUILD_DIR", Path(__file__).resolve().parents[2] / "build/tests")) / "amsdu-tid"
    out.mkdir(parents=True, exist_ok=True)
    cpp = out / "test.cpp"
    cpp.write_text(prelude + "\n".join(function(text, name) for name in functions) + MAIN)
    binary = out / "test"
    subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g",
                    str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)

if __name__ == "__main__":
    main()
