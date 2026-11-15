#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise actual A-MSDU reassembly with empty segments, complete payloads, padding, and failure ownership."""
import argparse
import os
from pathlib import Path
import subprocess

PRELUDE = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#define MBUF_DONTWAIT 0
#define mtod(m, t) reinterpret_cast<t>((m)->data.data())
int live, copy_calls, read_calls, fail_copy, fail_read;
bool fail_alloc;
std::vector<size_t> layout;
struct mbuf {
    std::vector<uint8_t> data;
    size_t len=0, total=0;
    mbuf *next=nullptr;
    explicit mbuf(size_t capacity): data(capacity, 0xa5) { ++live; }
    ~mbuf() { --live; }
};
struct ieee80211_rxinfo { unsigned flags=0x1234; };
struct mbuf_list {};
struct mwx_softc {
    int sc_amsdu_n=0;
    unsigned sc_amsdu_hdrlen=26;
    mbuf *sc_amsdu_sub[32]={};
    uint16_t sc_amsdu_len[32]={};
    ieee80211_rxinfo sc_amsdu_rxi;
};
size_t mbuf_len(mbuf *m) { return m->len; }
mbuf *mbuf_next(mbuf *m) { return m->next; }
size_t mbuf_trailingspace(mbuf *m) { return m->data.size()-m->len; }
void mbuf_setlen(mbuf *m, size_t n) { assert(n<=m->data.size()); m->len=n; }
void mbuf_pkthdr_setlen(mbuf *m, size_t n) { m->total=n; }
void m_freem(mbuf *m) { while(m) { auto next=m->next; delete m; m=next; } }
int mbuf_allocpacket(int, size_t total, unsigned *chunks, mbuf **out) {
    if(fail_alloc) return 12;
    auto caps=layout.empty() ? std::vector<size_t>{total} : layout;
    mbuf **tail=out;
    for(auto cap:caps) { *tail=new mbuf(cap); tail=&(*tail)->next; }
    *chunks=caps.size();
    // Match XNU: allocating capacity does not initialize segment m_len values.
    return 0;
}
int mbuf_copydata(mbuf *m, size_t off, size_t len, void *out) {
    if(++read_calls==fail_read) return 22;
    auto dst=static_cast<uint8_t *>(out);
    while(m && off>=m->len) { off-=m->len; m=m->next; }
    while(len && m) {
        size_t n=std::min(len,m->len-off);
        memcpy(dst,m->data.data()+off,n);
        dst+=n;len-=n;off=0;m=m->next;
    }
    return len ? 22 : 0;
}
int mbuf_copyback(mbuf *m, size_t off, size_t len, const void *in, int) {
    if(++copy_calls==fail_copy) return 12;
    auto src=static_cast<const uint8_t *>(in);
    mbuf *head=m;
    size_t written=0;
    while(off>m->len) {
        off-=m->len;written+=m->len;
        assert(m->next);m=m->next;
    }
    while(len) {
        size_t n=std::min(m->len-off,len);
        // Match the KPI boundary: only the last segment can grow into its trailing space.
        if(n<len && !m->next) {
            size_t grow=std::min(mbuf_trailingspace(m),len-n);
            n+=grow;m->len+=grow;
        }
        memcpy(m->data.data()+off,src,n);
        src+=n;len-=n;written+=n+off;off=0;
        if(!len) break;
        if(!m->next) { m->next=new mbuf(std::max(size_t(256),len)); m->next->len=len; }
        m=m->next;
    }
    head->total=std::max(head->total,written);
    return 0;
}
std::vector<std::vector<uint8_t>> delivered;
size_t delivered_head, delivered_total;
void mwx_rx_deliver(mwx_softc *, mbuf *m, ieee80211_rxinfo *rxi, mbuf_list *) {
    assert(rxi->flags==0x1234);
    delivered_head=m->len;delivered_total=m->total;
    std::vector<uint8_t> bytes;
    for(auto seg=m;seg;seg=seg->next)
        bytes.insert(bytes.end(),seg->data.begin(),seg->data.begin()+seg->len);
    delivered.push_back(bytes);
    m_freem(m);
}
'''

MAIN = r'''
std::vector<uint8_t> prepare(mwx_softc &sc, std::vector<unsigned> lengths, bool split=false) {
    sc.sc_amsdu_n=lengths.size();
    std::vector<uint8_t> expected(sc.sc_amsdu_hdrlen);
    for(unsigned h=0;h<sc.sc_amsdu_hdrlen;++h) expected[h]=uint8_t(0x80+h);
    for(unsigned i=0;i<lengths.size();++i) {
        std::vector<uint8_t> bytes(expected.begin(),expected.begin()+sc.sc_amsdu_hdrlen);
        for(unsigned j=0;j<lengths[i];++j) bytes.push_back(uint8_t(7+i*31+j));
        auto m=new mbuf(bytes.size());
        m->data=bytes;m->len=m->total=bytes.size();
        if(split) {
            size_t first=sc.sc_amsdu_hdrlen+7;
            m->next=new mbuf(bytes.size()-first);
            m->next->data.assign(bytes.begin()+first,bytes.end());
            m->next->len=bytes.size()-first;m->len=first;
        }
        sc.sc_amsdu_sub[i]=m;sc.sc_amsdu_len[i]=lengths[i];
        expected.insert(expected.end(),bytes.begin()+sc.sc_amsdu_hdrlen,bytes.end());
        if(i+1<lengths.size()) expected.insert(expected.end(),(4-lengths[i]%4)%4,0);
    }
    return expected;
}
void reset() {
    assert(live==0);
    delivered.clear();layout.clear();
    fail_alloc=false;fail_copy=fail_read=copy_calls=read_calls=0;
}
void check_cleared(mwx_softc &sc) {
    assert(sc.sc_amsdu_n==0 && live==0);
    for(auto m:sc.sc_amsdu_sub) assert(!m);
}
void good(std::vector<unsigned> sizes, std::vector<size_t> caps, unsigned hl=26, bool split=false) {
    reset();layout=caps;
    mwx_softc sc;sc.sc_amsdu_hdrlen=hl;mbuf_list ml;
    auto expected=prepare(sc,sizes,split);
    mwx_amsdu_flush(&sc,&ml);
    check_cleared(sc);
    assert(delivered.size()==1 && delivered[0]==expected);
    assert(delivered_head>=hl && delivered_total==expected.size());
}
int main(int argc, char **) {
    if(argc>1) {
        reset();layout={128,256};mwx_softc sc;mbuf_list ml;
        auto expected=prepare(sc,{80,80});
        mwx_amsdu_flush(&sc,&ml);
        check_cleared(sc);
        assert(delivered.size()==1 && delivered_head==0 && delivered[0]==expected);
        puts("Reproduced original defect: complete payload delivered with a zero-length head");
        return 0;
    }
    for(unsigned hl:{26U,30U,36U})
        for(unsigned len=60;len<76;++len) {
            good({len,len+1,len+2},{128,256},hl);
            good({len,len+1,len+2},{},hl);
        }
    good({2049,3075},{2048,2048,2048},26,true);
    good({1531,1531,1531,1531,1531,1531,1531,1531},{4096,4096,4096,4096});
    good({63,65},{31,65,128});
    good({80},{},26);
    reset();mwx_softc empty;mbuf_list ml;
    mwx_amsdu_flush(&empty,&ml);check_cleared(empty);assert(delivered.empty());
    reset();fail_alloc=true;mwx_softc failed;
    auto expected=prepare(failed,{63,65});
    expected.resize(26+63);
    mwx_amsdu_flush(&failed,&ml);check_cleared(failed);
    assert(delivered.size()==1 && delivered[0]==expected);
    for(int call=1;call<=4;++call) {
        reset();layout={128,256};fail_copy=call;mwx_softc sc;
        prepare(sc,{63,65});mwx_amsdu_flush(&sc,&ml);check_cleared(sc);
        assert(delivered.empty());
    }
    for(bool chain:{false,true}) {
        reset();if(chain) layout={128,256};fail_read=2;mwx_softc sc;
        prepare(sc,{63,65});mwx_amsdu_flush(&sc,&ml);check_cleared(sc);
        assert(delivered.empty());
    }
    for(auto caps:{std::vector<size_t>{32,32},std::vector<size_t>{8,256}}) {
        reset();layout=caps;mwx_softc sc;
        prepare(sc,{63,65});mwx_amsdu_flush(&sc,&ml);check_cleared(sc);
        assert(delivered.empty());
    }
    puts("PASS: single/chained A-MSDU payloads, four-byte padding, head length, and failure ownership");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--expect-bug", action="store_true", help="reproduce the zero-length head defect using unpatched source")
    args = parser.parse_args()
    text = (args.source / "SimpleMtkWlan/hal_mwx/MtkMwx.cpp").read_text()
    start = text.index("static void\nmwx_amsdu_flush(")
    end = text.index("\n}\n", start) + 3
    output = Path(os.environ.get("MTK_TEST_BUILD_DIR", Path(__file__).resolve().parents[2] / "build/tests")) / "amsdu-chain"
    output.mkdir(parents=True, exist_ok=True)
    cpp = output / "test.cpp"
    cpp.write_text(PRELUDE + text[start:end] + MAIN)
    binary = output / "test"
    subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g",
                    str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)] + (["--expect-bug"] if args.expect_bug else []), check=True)


if __name__ == "__main__":
    main()
