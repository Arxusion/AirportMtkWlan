from pathlib import Path
import subprocess,re
b=Path(__file__).resolve().parents[2]
s=(b/'SimpleMtkWlan/hal_mwx/MtkMwx.cpp').read_text();a=s.index('int mt7921_mcu_set_associated_peer(struct mwx_softc *sc)\n{');fn=s[a:s.index('\n}\n',a)+3]
w=(b/'SimpleMtkWlan/hal_mwx/if_mwxreg.h').read_text();state=re.search(r'struct sta_rec_state \{.*?\} __packed;',w,re.S).group()
assert re.search(r'#define\s+STA_REC_STATE\s+0x07\b',w), 'Wire tag changed; inspect protocol'
pre=r'''
#include <cstdint>
#include <cstring>
#include <cassert>
#include <cerrno>
#include <cstdio>
#define __packed __attribute__((packed))
#define MWX_DEV_LOG(...) ((void)0)
#define IEEE80211_AID(x) ((x)&0x3fff)
#define MCU_UNI_CMD_STA_REC_UPDATE 0x20003
#define STA_REC_STATE 0x07
struct ieee80211_node{uint16_t ni_associd;uint32_t ni_flags=0;uint16_t ni_htcaps=0;uint8_t ni_ampdu_param=0;uint8_t ni_rxmcs[10]={};uint32_t ni_vhtcaps=0;struct{uint16_t rx_mcs_map,rx_highest,tx_mcs_map,tx_highest;} ni_vht_mcsinfo={};int ni_chw=0;};
#define IEEE80211_NODE_HT 0x0400
#define IEEE80211_NODE_VHT 0x2000
#define IEEE80211_VHTCAP_SUPP_CHAN_WIDTH_MASK 0x0000000C
#define STA_REC_VHT 0x0a
#define CMD_CBW_80MHZ 2
struct ieee80211_vht_mcs_info{uint16_t rx_mcs_map,rx_highest,tx_mcs_map,tx_highest;};
struct sta_rec_vht_v1{uint16_t tag,len;uint32_t vht_cap;uint16_t vht_rx_mcs_map,vht_tx_mcs_map;uint8_t rts_bw_sig,rsv[3];};
#ifndef htole16
#define htole16(x) (x)
#endif
#ifndef htole32
#define htole32(x) (x)
#endif
#define IEEE80211_HTCAP_CBW20_40 0x0002
#define IEEE80211_HTCAP_SGI40 0x0040
#define STA_REC_HT 0x09
#define STA_REC_PHY 0x15
#define STA_REC_RA 0x01
#define HT_MCS_MASK_NUM 10
#define RA_LEGACY_OFDM 0x3fc0
struct sta_rec_ht_v1{uint16_t tag,len,ht_cap,rsv;};
struct sta_rec_phy{uint16_t tag,len,basic_rate;uint8_t phy_type,ampdu,rts_policy,rcpi,rsv[2];};
struct sta_rec_ra_info{uint16_t tag,len,legacy;uint8_t rx_mcs_bitmask[HT_MCS_MASK_NUM];};
struct mwx_node{ieee80211_node ni;uint16_t wcid;};
struct mwx_vif{uint8_t omac_idx;};
struct mwx_softc{struct {ieee80211_node*ic_bss;uint8_t ic_sup_mcs[10];}sc_ic;mwx_vif sc_vif;struct{uint8_t num_streams;}sc_capa;};
void mwx_node_chan_width(ieee80211_node*,uint8_t*bw,uint8_t*center){*bw=0;*center=0;}
uint8_t mt7921_get_phy_mode_v2(mwx_softc*,ieee80211_node*){return 0;}
struct sta_req_hdr{uint8_t unused[8];};
struct mbuf{unsigned char bytes[256];size_t len;};
mbuf storage;bool alloc_fail=false,header_fail=false;int send_rc=0,wait_rc=0,sends=0,waits=0;uint32_t fw=0;
mbuf*mwx_alloc_sta_req_tlv(size_t){memset(&storage,0xbd,sizeof(storage));storage.len=0;return alloc_fail?nullptr:&storage;}
void mt7921_mcu_add_basic_tlv(mbuf*m,uint16_t*n,mwx_softc*,ieee80211_node*ni,int add,int isnew){assert(add==1&&isnew==0);assert(IEEE80211_AID(ni->ni_associd)==37);m->len=32;(*n)++;}
void*mwx_append_tlv(mbuf*m,uint16_t*n,int tag,int len){auto*p=m->bytes+m->len;memset(p,0,len);((uint16_t*)p)[0]=tag;((uint16_t*)p)[1]=len;m->len+=len;(*n)++;return p;}
mbuf*mwx_fill_sta_req_hdr(mbuf*m,mwx_vif*,uint8_t omac,uint16_t wcid,uint16_t n){assert(omac==3&&wcid==287&&n==2);return header_fail?nullptr:m;}
int mwx_mcu_send_mbuf(mwx_softc*,int cmd,mbuf*m,int*seq){assert(cmd==MCU_UNI_CMD_STA_REC_UPDATE);assert(m->len==44);unsigned char golden[]={0x07,0,12,0,0,0,0,0,2,0,0,0};assert(!memcmp(m->bytes+32,golden,12));*seq=9;sends++;return send_rc;}
int mwx_mcu_wait_resp_int(mwx_softc*,int cmd,int seq,uint32_t*status){assert(cmd==MCU_UNI_CMD_STA_REC_UPDATE&&seq==9);*status=fw;waits++;return wait_rc;}
'''
post=r'''
int main(){mwx_node n{{uint16_t(0xc000|37)},287};mwx_softc sc{{&n.ni},{3}};
 assert(mt7921_mcu_set_associated_peer(&sc)==0);assert(sends==1&&waits==1);
 fw=7;assert(mt7921_mcu_set_associated_peer(&sc)==EIO);fw=0;
 wait_rc=ETIMEDOUT;assert(mt7921_mcu_set_associated_peer(&sc)==ETIMEDOUT);wait_rc=0;
 int before=waits;send_rc=ENOBUFS;assert(mt7921_mcu_set_associated_peer(&sc)==ENOBUFS&&waits==before);send_rc=0;
 before=sends;alloc_fail=true;assert(mt7921_mcu_set_associated_peer(&sc)==ENOBUFS&&sends==before);alloc_fail=false;
 header_fail=true;assert(mt7921_mcu_set_associated_peer(&sc)==ENOBUFS&&sends==before);header_fail=false;
 n.ni.ni_associd=0;assert(mt7921_mcu_set_associated_peer(&sc)==EINVAL&&sends==before);
 sc.sc_ic.ic_bss=nullptr;assert(mt7921_mcu_set_associated_peer(&sc)==EINVAL&&sends==before);
 puts("PASS actual associated-peer builder: golden STATE TLV, AID/WCID, no WTBL reset, transport/firmware failures and absent association guards.");}
'''
p=b/'tests/association/peer-test.cpp';p.write_text(pre+state+'\n'+fn+'\n'+post)
subprocess.run(['clang++','-std=c++14','-fsanitize=address,undefined',str(p),'-o',str(p.with_suffix(''))],check=True)
r=subprocess.run([str(p.with_suffix(''))],capture_output=True,text=True);(b/'tests/association/peer-result.txt').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr);r.check_returncode()
