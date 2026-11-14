#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise actual BA message builders for wire format, submission order, and failure ownership."""
import argparse
import os
from pathlib import Path
import re
import subprocess

PRELUDE = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <vector>
#define __packed __attribute__((packed))
#define KASSERT(x) assert(x)
#define M_DONTWAIT 0
#define IEEE80211_ADDR_LEN 6
#define htole16(x) static_cast<uint16_t>(x)
#define le16toh(x) static_cast<uint16_t>(x)
#define mtod(m,t) reinterpret_cast<t>((m)->bytes+(m)->head)
#define STA_REC_BA 0x06
#define STA_REC_WTBL 0x0d
#define WTBL_BA 0x08
#define WTBL_SET 2
#define MT_BA_TYPE_ORIGINATOR 1
#define MT_BA_TYPE_RECIPIENT 2
#define MCU_UNI_CMD_STA_REC_UPDATE 0x10003
int live, allocs, prepends, sends, fail_alloc, fail_prepend, fail_send;
struct mbuf { uint8_t bytes[2048]={}; size_t head=64,len=0,total=0; };
struct ieee80211_node { unsigned unused; };
struct mwx_node { ieee80211_node ni; uint16_t wcid=0x234; };
struct mwx_vif { uint8_t idx=3,omac_idx=5; };
struct mwx_softc { mwx_vif sc_vif; };
std::vector<std::vector<uint8_t>> messages;
mbuf *mwx_alloc_sta_req_tlv(int) {
    if(++allocs==fail_alloc) return nullptr;
    ++live;return new mbuf;
}
void m_freem(mbuf *m) { assert(m && live>0);--live;delete m; }
size_t mbuf_len(mbuf *m) { return m->len; }
void mbuf_setlen(mbuf *m, size_t n) { assert(n<=sizeof(m->bytes)-m->head);m->len=n; }
void mbuf_pkthdr_setlen(mbuf *m, size_t n) { m->total=n; }
size_t m_leadingspace(mbuf *m) { return m->head; }
size_t m_trailingspace(mbuf *m) { return sizeof(m->bytes)-m->head-m->len; }
mbuf *m_prepend(mbuf *m, size_t n, int) {
    if(++prepends==fail_prepend) { m_freem(m);return nullptr; }
    assert(m->head>=n);m->head-=n;m->len+=n;m->total+=n;return m;
}
int mwx_mcu_send_mbuf(mwx_softc *, uint32_t cmd, mbuf *m, int *seq) {
    assert(cmd==MCU_UNI_CMD_STA_REC_UPDATE && seq==nullptr && m->len==m->total);
    messages.emplace_back(m->bytes+m->head,m->bytes+m->head+m->len);
    m_freem(m);
    return ++sends==fail_send ? EIO : 0;
}
'''

MAIN = r'''
void reset() {
    assert(live==0);allocs=prepends=sends=fail_alloc=fail_prepend=fail_send=0;
    messages.clear();
}
std::vector<uint8_t> header(size_t size) {
    std::vector<uint8_t> v(size,0);
    v[0]=3;v[1]=0x34;v[2]=1;v[4]=1;v[5]=5;v[6]=2;
    return v;
}
void put16(std::vector<uint8_t> &v, size_t offset, unsigned value) {
    v[offset]=value&255;v[offset+1]=(value>>8)&255;
}
int main() {
    static_assert(sizeof(sta_req_hdr)==8 && sizeof(sta_rec_wtbl)==12 &&
                  sizeof(wtbl_ba)==28 && sizeof(sta_rec_ba)==12,"wire size");
    mwx_softc sc;mwx_node node;
    for(unsigned tid=0;tid<8;++tid)
        for(unsigned ssn:{0U,0x123U,4095U})
            for(unsigned win:{1U,32U,64U})
                for(int enable:{0,1}) {
                    reset();
                    assert(mwx_mcu_sta_ba(&sc,&node.ni,tid,ssn,win,enable,1,1)==0);
                    assert(live==0 && messages.size()==2);
                    auto wt=header(48);
                    put16(wt,8,13);put16(wt,10,40);
                    wt[12]=0x34;wt[13]=2;wt[14]=1;wt[16]=2;
                    put16(wt,20,8);put16(wt,22,28);wt[24]=tid;wt[25]=1;
                    put16(wt,28,enable?ssn:0);wt[30]=enable;
                    put16(wt,32,enable?win:0);
                    auto sta=header(20);
                    put16(sta,8,6);put16(sta,10,12);sta[12]=tid;sta[13]=1;
                    sta[14]=1;sta[15]=enable?(1U<<tid):0;
                    put16(sta,16,ssn);put16(sta,18,win);
                    assert(messages[0]==wt && messages[1]==sta);
                }
    // RX calls continue to submit a single STA_REC_BA message.
    reset();assert(mwx_mcu_sta_ba(&sc,&node.ni,3,0x123,64,1,0,0)==0);
    auto rx=header(20);put16(rx,8,6);put16(rx,10,12);
    rx[12]=3;rx[13]=2;rx[15]=8;put16(rx,16,0x123);put16(rx,18,64);
    assert(live==0 && messages.size()==1 && messages[0]==rx);
    // If either message cannot be built, submit neither and free any allocated message.
    for(int which:{1,2}) {
        reset();fail_alloc=which;
        assert(mwx_mcu_sta_ba(&sc,&node.ni,0,0,64,1,1,0)==ENOBUFS);
        assert(live==0 && messages.empty());
        reset();fail_prepend=which;
        assert(mwx_mcu_sta_ba(&sc,&node.ni,0,0,64,1,1,0)==ENOBUFS);
        assert(live==0 && messages.empty());
    }
    reset();fail_send=1;
    assert(mwx_mcu_sta_ba(&sc,&node.ni,0,0,64,1,1,0)==EIO);
    assert(live==0 && messages.size()==1);
    reset();fail_send=2;
    assert(mwx_mcu_sta_ba(&sc,&node.ni,0,0,64,1,1,0)==EIO);
    assert(live==0 && messages.size()==2);
    puts("PASS: TX WTBL/STA BA wire format, enable/disable order, RX behavior, and build/submission failures");
}
'''


def extract(text, signature, prefix):
    pattern = r"\s+".join(re.escape(part) for part in signature.split()) + r"\s*\{"
    match = re.search(pattern, text)
    if match is None:
        raise ValueError("Function not found: " + signature)
    start = match.start()
    return prefix + text[start:text.index("\n}\n", start) + 3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    hal = args.source / "SimpleMtkWlan/hal_mwx"
    text = (hal / "MtkMwx.cpp").read_text()
    header = (hal / "if_mwxreg.h").read_text()
    blocks = [PRELUDE]
    for name in ("sta_req_hdr", "sta_rec_wtbl", "wtbl_ba", "sta_rec_ba"):
        start = header.index("struct " + name + " {")
        blocks.append(header[start:header.index("} __packed;", start) + len("} __packed;")])
    for signature, prefix in (
        ("mwx_append_len(struct mbuf *m, int len)", "void *\n"),
        ("mwx_append_tlv(struct mbuf *m, uint16_t *tlvnum, int tag, int len)", "void *\n"),
        ("mwx_fill_sta_req_hdr(struct mbuf *m, struct mwx_vif *mvif,\n    uint8_t muar_idx, uint16_t wcid, uint16_t tlvnum)", "struct mbuf *\n"),
        ("mwx_alloc_wtbl_tx_ba(struct mwx_softc *sc, struct ieee80211_node *ni,\n    uint8_t tid, uint16_t ssn, uint16_t winsize, int enable)", "static struct mbuf *\n"),
        ("mwx_mcu_sta_ba(struct mwx_softc *sc, struct ieee80211_node *ni, uint8_t tid,\n    uint16_t ssn, uint16_t winsize, int enable, int tx, int amsdu)", "static int\n"),
    ):
        blocks.append(extract(text, signature, prefix))
    blocks.append(MAIN)
    output = Path(os.environ.get("MTK_TEST_BUILD_DIR", Path(__file__).resolve().parents[2] / "build/tests")) / "tx-wtbl-ba"
    output.mkdir(parents=True, exist_ok=True)
    cpp = output / "test.cpp"
    cpp.write_text("\n".join(blocks))
    binary = output / "test"
    subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g",
                    str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
