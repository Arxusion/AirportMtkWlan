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
struct mwx_txwi {int mt_busy;};
struct mwx_softc {int sc_txq;struct {int mt_count;mwx_txwi mt_data[16];}sc_txwi;};
void mwx_dma_tx_cleanup(mwx_softc*,int*){}
mbuf* m_pullup(mbuf*m,size_t){return m;}
size_t mbuf_len(mbuf*m){return m->len-m->off;}
size_t mbuf_pkthdr_len(mbuf*m){return m->len;}
void m_adj(mbuf*m,size_t n){assert(n<=mbuf_len(m));m->off+=n;}
void m_freem(mbuf*m){free(m->raw);delete m;}
#define mtod(m,t) ((t)((m)->raw+(m)->off))
#define le32toh(x) (x)
#define MT_TX_FREE_PAIR (1u<<31)
#define MT_TX_FREE0_MSDU_CNT_GET(x) (((x)>>16)&0x3ff)
#define MT_TX_FREE_MSDU_ID_GET(x) (((x)>>16)&0x7fff)
void mwx_tx_kick(mwx_softc*){}
unsigned releases;
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
 puts("PASS: short headers,64 valid mixed PAIR/MSDU events,63 truncated PAIR lists; extracted firmware TX-free parser ASan/UBSan.");
}
'''
tmp=tempfile.TemporaryDirectory(prefix='mtk-tx-test-');art=Path(tmp.name)
cpp=art/'free-test.cpp';exe=art/'free-test';cpp.write_text(pre+f+main)
subprocess.run(['clang++','-std=c++14','-fsanitize=address,undefined','-g',str(cpp),'-o',str(exe)],check=True)
raise SystemExit(subprocess.run([str(exe)]+(['baseline'] if len(sys.argv)>2 else [])).returncode)
