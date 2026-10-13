from pathlib import Path
import re,subprocess
base=Path(__file__).resolve().parents[2]
source=(base/'SimpleMtkWlan/hal_mwx/MtkMwx.cpp').read_text()
wire=(base/'SimpleMtkWlan/hal_mwx/if_mwxreg.h').read_text()
a=source.index('int\nmt7921_mcu_set_associated_bss(');fn=source[a:source.index('\n}\n',a)+3]
struct=re.search(r'struct mt76_connac_bss_basic_tlv \{.*?\} __packed;',wire,re.S).group()
code=r'''
#include <cstdint>
#include <cstring>
#include <cassert>
#include <cerrno>
#include <vector>
#include <cstdio>
#define __packed __attribute__((packed))
#define IEEE80211_ADDR_LEN 6
#define ETHER_ADDR_LEN 6
#define IEEE80211_M_STA 1
#define IEEE80211_CHAN_ANYC ((ieee80211_channel*)-1)
#define IEEE80211_IS_CHAN_2GHZ(c) ((c)->ic_freq<3000)
#define UNI_BSS_INFO_BASIC 0
#define UNI_BSS_INFO_RLM 2
#define EXT_BSSID_START 16
#define HW_BSSID_0 0
#define STA_TYPE_STA 1
#define NETWORK_INFRA 65536
#define PHY_TYPE_BIT_HR_DSSS 1
#define PHY_TYPE_BIT_ERP 2
#define PHY_TYPE_BIT_OFDM 8
#define MCU_UNI_CMD_BSS_INFO_UPDATE 0x20002
#define CMD_CBW_20MHZ 0
#define MWX_DEV_LOG(...) ((void)0)
#define htole16(x) (x)
#define htole32(x) (x)
struct ieee80211_channel { int ic_freq; int width; };
struct ieee80211_node { ieee80211_channel *ni_chan; uint8_t ni_bssid[6]; uint16_t ni_intval; uint8_t ni_dtimperiod; uint32_t ni_flags = 0; };
#define IEEE80211_NODE_HT 0x0400
struct ieee80211com { int ic_opmode; ieee80211_node *ic_bss; };
struct mwx_vif { uint8_t idx,omac_idx,band_idx,wmm_idx; struct {uint16_t wcid;} vif_mn; };
struct mwx_softc { ieee80211com sc_ic; mwx_vif sc_vif; struct {uint8_t num_streams,antenna_mask;} sc_capa; };
int ieee80211_mhz2ieee(int f,int) {return f==2484?14:f<3000?(f-2407)/5:(f-5000)/5;}
int mt7921_mcu_chan_bw(ieee80211_channel *c){return c->width;}
std::vector<std::vector<uint8_t>> sent;
int fail_at=0;
int mwx_send_assoc_status(mwx_softc*,int cmd,void *p,int n){assert(cmd==0x20002);auto b=(uint8_t*)p;sent.emplace_back(b,b+n);return int(sent.size())==fail_at?EIO:0;}
'''+struct+'\n'+fn+r'''
int main(){
 ieee80211_channel c{5745,0};ieee80211_node n{&c,{0xe8,0x45,0x8b,0x39,0xe0,0xa7},100,3};
 mwx_softc sc{{1,&n},{3,2,0,1,{19}},{2,3}};
 for(int freq:{2412,2437,2462,2484,5180,5745,5825}){
  c.ic_freq=freq;sent.clear();fail_at=0;assert(mt7921_mcu_set_associated_bss(&sc,1)==0);assert(sent.size()==2);
  std::vector<uint8_t> basic={3,0,0,0,0,0,32,0,1,2,2,0,1,0,1,0,0,1,0xe8,0x45,0x8b,0x39,0xe0,0xa7,19,0,100,0,3,1,19,0,8,0,0,0};
  bool two=freq<3000;if(two){basic[29]=6;basic[32]=3;}
  assert(sent[0]==basic);
  int ch=ieee80211_mhz2ieee(freq,0);
  std::vector<uint8_t> rlm={3,0,0,0,2,0,16,0,(uint8_t)ch,(uint8_t)ch,0,0,2,3,1,0,0,(uint8_t)(two?0:1),0,0};
  assert(sent[1]==rlm);
  sent.clear();assert(mt7921_mcu_set_associated_bss(&sc,0)==0);basic[16]=1;assert(sent.size()==1&&sent[0]==basic);
 }
 for(int fail:{1,2}){sent.clear();fail_at=fail;assert(mt7921_mcu_set_associated_bss(&sc,1)==EIO);assert(sent.size()==static_cast<size_t>(fail));}
 fail_at=0;sent.clear();sc.sc_ic.ic_bss=nullptr;assert(mt7921_mcu_set_associated_bss(&sc,1)==EINVAL);assert(sent.empty());
 sc.sc_ic.ic_bss=&n;n.ni_chan=nullptr;assert(mt7921_mcu_set_associated_bss(&sc,1)==EINVAL);assert(sent.empty());
 n.ni_chan=IEEE80211_CHAN_ANYC;assert(mt7921_mcu_set_associated_bss(&sc,1)==EINVAL);assert(sent.empty());
 n.ni_chan=&c;c.width=1;assert(mt7921_mcu_set_associated_bss(&sc,1)==EOPNOTSUPP);assert(sent.empty());
 c.width=0;sc.sc_ic.ic_opmode=2;assert(mt7921_mcu_set_associated_bss(&sc,1)==0);assert(sent.empty());
 puts("PASS: real BSS constructor, golden wire packets on 7 channels, disassociation, firmware failures, null/unsupported guards");
}
'''
p=base/'tests/association/bss-context-test.cpp';p.write_text(code)
subprocess.run(['clang++','-std=c++14','-Wall','-Wextra','-fsanitize=address,undefined',str(p),'-o',str(base/'tests/association/bss-context-test')],check=True)
subprocess.run([str(base/'tests/association/bss-context-test')],check=True)
