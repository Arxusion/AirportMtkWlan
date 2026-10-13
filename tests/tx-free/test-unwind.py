from pathlib import Path
import subprocess,sys,tempfile
b=Path(__file__).resolve().parent
src=Path(sys.argv[1]) if len(sys.argv)>1 else b.parents[1]/'SimpleMtkWlan/hal_mwx/MtkMwx.cpp';s=src.read_text();f=s[s.index('int\nmwx_tx('):s.index('\nvoid\nmwx_rx(')]
pre=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cerrno>
#define MWX_DEV_LOG(...) ((void)0)
struct mbuf {bool freed=false;};struct ieee80211_node {};struct mwx_node:ieee80211_node{unsigned wcid;};
struct mt76_txwi {char desc[64];};
struct mwx_txwi{mt76_txwi*mt_desc;mbuf*mt_mbuf;bool busy;};
struct mwx_softc{int sc_txq;};
mt76_txwi desc; mwx_txwi mt{&desc,nullptr,false};int fail_at,freed,returned,mapped;
void m_freem(mbuf*m){assert(!m->freed);m->freed=true;freed++;}
mbuf* mwx_tx_linearize(mbuf*m){return m;}
mwx_txwi* mwx_txwi_get(mwx_softc*){if(fail_at==1)return nullptr;assert(!mt.busy);mt.busy=true;return &mt;}
void mt7921_mac_write_txwi(mwx_softc*,mbuf*,ieee80211_node*,mt76_txwi*){}
int mwx_txwi_enqueue(mwx_softc*,mwx_txwi*t,mbuf*m){if(fail_at==2)return EFBIG;t->mt_mbuf=m;mapped++;return 0;}
int mwx_dma_txwi_enqueue(mwx_softc*,int*,mwx_txwi*){return fail_at==3?EBUSY:0;}
void mwx_txwi_put(mwx_softc*,mwx_txwi*t){assert(t->busy);if(t->mt_mbuf){m_freem(t->mt_mbuf);t->mt_mbuf=nullptr;mapped--;}t->busy=false;returned++;}
'''
main=r'''
int main(){mwx_softc sc{};mwx_node ni{};
 for(int trial=0;trial<100;trial++)for(fail_at=0;fail_at<=3;fail_at++){
  mbuf m;freed=returned=mapped=0;int rv=mwx_tx(&sc,&m,&ni);
  if(fail_at==0){assert(rv==0&&mt.busy&&mapped==1&&!m.freed);mwx_txwi_put(&sc,&mt);}
  else assert(rv!=0);
  assert(m.freed&&freed==1&&!mt.busy&&mapped==0);assert(returned==(fail_at==1?0:1));
 }
 puts("PASS:400 extracted mwx_tx paths; no-token,map failure,ring-full and completion return packet/token/map exactly once.");
}
'''
tmp=tempfile.TemporaryDirectory(prefix='mtk-tx-test-');art=Path(tmp.name)
cpp=art/'unwind-test.cpp';exe=art/'unwind-test';cpp.write_text(pre+f+main)
subprocess.run(['clang++','-std=c++14','-fsanitize=address,undefined','-g',str(cpp),'-o',str(exe)],check=True)
raise SystemExit(subprocess.run([str(exe)]).returncode)
