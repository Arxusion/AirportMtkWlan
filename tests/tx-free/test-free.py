from pathlib import Path
import subprocess,sys,tempfile
b=Path(__file__).resolve().parent
src=Path(sys.argv[1]) if len(sys.argv)>1 else b.parents[1]/'SimpleMtkWlan/hal_mwx/MtkMwx.cpp'
s=src.read_text();f=s[s.index('void\nmwx_mac_tx_free('):s.index('\nint\nmt7921_set_channel(')]
pre=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>
struct mbuf {unsigned char* raw;size_t len,off;};
#define AIRPORT_WCL 1
#define __IO80211_TARGET 260000
#define __MAC_26_0 260000
#include <HAL/MtkAwdlAnnouncement.hpp>
enum class MwxAwdlTx : uint8_t { None, Sync, Service, VerifiedService, Data, GroupData };
struct mwx_txwi {int mt_busy; MwxAwdlTx mt_awdl; uint32_t mt_awdl_epoch; uint64_t mt_awdl_queue_time;};
struct mwx_softc {
 int sc_txq;
 struct {int mt_count;mwx_txwi mt_data[16];} sc_txwi;
 MtkAwdl::AnnouncementCompletions sc_awdl_completions;
 uint32_t sc_awdl_channel_epoch;
};
void mwx_dma_tx_cleanup(mwx_softc*,int*){}
mbuf* m_pullup(mbuf*m,size_t){return m;}
size_t mbuf_len(mbuf*m){return m->len-m->off;}
size_t mbuf_pkthdr_len(mbuf*m){return m->len;}
void m_adj(mbuf*m,size_t n){assert(n<=mbuf_len(m));m->off+=n;}
void m_freem(mbuf*m){free(m->raw);delete m;}
#define mtod(m,t) ((t)((m)->raw+(m)->off))
#define le32toh(x) (x)
#define MT_TX_FREE_PAIR (1u<<31)
#define MT_TX_FREE_STATUS_MASK (3u<<13)
#define MT_TX_FREE0_MSDU_CNT_GET(x) (((x)>>16)&0x3ff)
#define MT_TX_FREE_MSDU_ID_GET(x) (((x)>>16)&0x7fff)
void mwx_tx_kick(mwx_softc*){}
unsigned releases;
uint64_t mach_absolute_time() { return 2000000; }
void absolutetime_to_nanoseconds(uint64_t ticks, uint64_t *ns) { *ns = ticks; }
void mwx_txwi_put(mwx_softc*,mwx_txwi*mt){assert(mt->mt_busy);mt->mt_busy=0;releases++;}
mbuf* packet(size_t len){auto m=new mbuf{(unsigned char*)calloc(1,len),len,0};return m;}
'''
main=r'''
int main(int argc,char**argv){
 mwx_softc sc={};sc.sc_txwi.mt_count=16;
 if(argc>1){ // baseline reproducer: count excludes PAIR, so loop grows past the payload
  auto m=packet(12);auto p=mtod(m,uint32_t*);p[0]=1u<<16;p[2]=MT_TX_FREE_PAIR;mwx_mac_tx_free(&sc,m);return 0;
 }
 for(size_t len=0;len<8;len++)mwx_mac_tx_free(&sc,packet(len));
 for(unsigned pairs=0;pairs<64;pairs++){
  auto m=packet(8+4*(pairs+2));auto p=mtod(m,uint32_t*);p[0]=2u<<16;
  for(unsigned i=0;i<pairs;i++)p[2+i]=MT_TX_FREE_PAIR;
  p[2+pairs]=3u<<16;p[3+pairs]=4u<<16;
  sc.sc_txwi.mt_data[3].mt_busy=sc.sc_txwi.mt_data[4].mt_busy=1;unsigned prev=releases;
  mwx_mac_tx_free(&sc,m);assert(releases==prev+2);
 }
 for(unsigned n=1;n<64;n++){
  auto m=packet(8+4*n);auto p=mtod(m,uint32_t*);p[0]=1u<<16;
  for(unsigned i=0;i<n;i++)p[i+2]=MT_TX_FREE_PAIR;
  mwx_mac_tx_free(&sc,m);
 }
 auto m=packet(8+5*4);
 auto words=mtod(m,uint32_t*);
 words[0]=5u<<16;
 words[2]=(3u<<16);             // Service succeeded.
 words[3]=(4u<<16) | (2u<<13);  // Service failed.
 words[4]=(5u<<16);             // Sync succeeded.
 words[5]=(6u<<16) | (1u<<13);  // Ordinary traffic is excluded.
 words[6]=(3u<<16);             // Duplicate release is ignored.
 sc.sc_txwi.mt_data[3]={1,MwxAwdlTx::Service};
 sc.sc_txwi.mt_data[4]={1,MwxAwdlTx::Service};
 sc.sc_txwi.mt_data[5]={1,MwxAwdlTx::Sync};
 sc.sc_txwi.mt_data[6]={1,MwxAwdlTx::None};
 mwx_mac_tx_free(&sc,m);
 const auto &counts=sc.sc_awdl_completions;
 assert(counts.sent==2 && counts.failed==1);
 assert(counts.serviceSent==1 && counts.serviceFailed==1 && counts.lastStatus==0);
 auto switched=packet(8+2*4);
 auto events=mtod(switched,uint32_t*);
 events[0]=2u<<16;
 events[2]=3u<<16;
 events[3]=4u<<16;
 sc.sc_awdl_channel_epoch=10;
 sc.sc_txwi.mt_data[3]={1,MwxAwdlTx::VerifiedService,9};
 sc.sc_txwi.mt_data[4]={1,MwxAwdlTx::VerifiedService,10,1500000};
 mwx_mac_tx_free(&sc,switched);
 assert(counts.sent==4 && counts.serviceSent==3 && counts.verifiedServiceSent==1);
 assert(counts.verifiedCompletionLastUS==500 && counts.verifiedCompletionMaxUS==500);
 puts("PASS: AWDL completion attribution, short headers,64 valid mixed PAIR/MSDU events,63 truncated PAIR lists; extracted firmware TX-free parser ASan/UBSan.");
}
'''
tmp=tempfile.TemporaryDirectory(prefix='mtk-tx-test-');art=Path(tmp.name)
cpp=art/'free-test.cpp';exe=art/'free-test';cpp.write_text(pre+f+main)
subprocess.run(['clang++','-std=c++14','-fsanitize=address,undefined','-g','-I',str(b.parents[1]/'include'),str(cpp),'-o',str(exe)],check=True)
raise SystemExit(subprocess.run([str(exe)]+(['baseline'] if len(sys.argv)>2 else [])).returncode)
