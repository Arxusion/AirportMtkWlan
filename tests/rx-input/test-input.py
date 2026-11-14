#!/usr/bin/env python3
"""Exercise actual receive handoff with an ownership-consuming IOKit stub."""
from pathlib import Path
import subprocess,tempfile,sys
root=Path(__file__).resolve().parents[2]
s=(root/'mtk80211/openbsd/sys/_mbuf.cpp').read_text()
f=s[s.index('static IOReturn _if_input('):s.index('\nint if_input(')]
h=(root/'mtk80211/openbsd/sys/_mbuf.h').read_text()
dequeue=h[h.index('static inline mbuf_t\nml_dequeue('):h.index('static inline mbuf_t\nml_dechain(')]
pre=r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <net/ethernet.h>
using UInt32=unsigned; using IOReturn=int; struct OSObject{};
constexpr int kIOReturnSuccess=0;
#define XYLog(...) ((void)0)
#define panic(...) abort()
#define mtod(m, t) ((t)((m)->raw))
#define MBUF_DONTWAIT 0
struct Packet { Packet* next; unsigned id; uint8_t raw[64]; Packet(Packet* n, unsigned i) : next(n), id(i) { memset(raw, 0, sizeof(raw)); } };
using mbuf_t=Packet*;
mbuf_t mbuf_nextpkt(mbuf_t m){return m->next;}
void mbuf_setnextpkt(mbuf_t m,mbuf_t n){m->next=n;}
static inline int mbuf_dup(mbuf_t m, int, mbuf_t* out) { *out = nullptr; return 1; }
struct mbuf_list {mbuf_t ml_head=nullptr,ml_tail=nullptr;unsigned ml_len=0;};
#define MBUF_LIST_FOREACH(ml,m) for(m=(ml)->ml_head;m;m=mbuf_nextpkt(m))
struct Stats {unsigned inputPackets=0;};
struct IONetworkInterface {
 static constexpr unsigned kInputOptionQueuePacket=1;
 std::vector<unsigned> received; unsigned flushes=0;
 UInt32 inputPacket(mbuf_t m,unsigned len,unsigned opt){
  assert(len==0 && opt==kInputOptionQueuePacket);
  assert(m->next==nullptr && "IOKit requires a detached packet");
  received.push_back(m->id); delete m; return 0;
 }
 unsigned flushInputQueue(){++flushes;return received.size();}
};
struct _ifnet {
    IONetworkInterface* iface;
    Stats* netStat;
    IONetworkInterface* if_awdl_iface = nullptr;
    uint8_t if_awdl_mac[6] = {0};
    bool if_awdl_enabled = false;
};
'''
main=r'''
int main(){
 for(unsigned count: {0u,1u,2u,16u,64u,1024u}) {
  mbuf_list list; IONetworkInterface iface;Stats stats;_ifnet net{&iface,&stats};
  for(unsigned i=0;i<count;++i){auto m=new Packet{nullptr,i};if(list.ml_tail)list.ml_tail->next=m;else list.ml_head=m;list.ml_tail=m;++list.ml_len;}
  assert(_if_input(nullptr,&net,&list,nullptr,nullptr)==0);
  assert(iface.received.size()==count && stats.inputPackets==count);
  assert(iface.flushes==(count?1u:0u));
  assert(!list.ml_head && !list.ml_tail && list.ml_len==0);
  for(unsigned i=0;i<count;++i)assert(iface.received[i]==i);
 }
 puts("PASS: six batch sizes, exact-once ordered handoff, detached packets, no post-transfer access");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.cpp').write_text(pre+dequeue+f+main)
 subprocess.run(['clang++','-std=c++14','-fsanitize=address,undefined','-g',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 r=subprocess.run([str(p/'test')],capture_output=True,text=True)
 print(r.stdout+r.stderr)
 if '--expect-failure' in sys.argv:
  assert r.returncode!=0,'Original unexpectedly passed'
  print('Original rejected as expected')
 else:r.check_returncode()
