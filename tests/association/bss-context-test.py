from pathlib import Path
import re,subprocess
base=Path(__file__).resolve().parents[2]
source=(base/'SimpleMtkWlan/hal_mwx/MtkMwx.cpp').read_text()
wire=(base/'SimpleMtkWlan/hal_mwx/if_mwxreg.h').read_text()
a=source.index('int\nmt7921_mcu_set_associated_bss(');fn=source[a:source.index('\n}\n',a)+3]
struct='\n'.join([
    re.search(r'struct mt76_connac_bss_basic_tlv \{.*?\} __packed;',wire,re.S).group(),
    re.search(r'struct bss_info_uni_bss_color \{.*?\} __packed;',wire,re.S).group(),
    re.search(r'struct bss_info_uni_he \{.*?\} __packed;',wire,re.S).group(),
])
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
#define UNI_BSS_INFO_BSS_COLOR 4
#define UNI_BSS_INFO_HE_BASIC 5
#define CMD_HE_MCS_BW80 0
#define CMD_HE_MCS_BW160 1
#define CMD_HE_MCS_BW8080 2
#define CMD_HE_MCS_BW_NUM 3
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
#define le16toh(x) (x)
struct ieee80211_channel { int ic_freq; int width; };
struct ieee80211_node { ieee80211_channel *ni_chan; uint8_t ni_bssid[6]; uint16_t ni_intval; uint8_t ni_dtimperiod; uint32_t ni_flags = 0; uint32_t ni_he_oper_params = 0; };
#define IEEE80211_NODE_HT 0x0400
#define IEEE80211_NODE_VHT 0x2000
#define IEEE80211_NODE_HE 0x200000
#define IEEE80211_HE_OPERATION_DFLT_PE_DURATION_MASK 0x00000007
#define IEEE80211_HE_OPERATION_RTS_THRESHOLD_MASK 0x00003ff0
#define IEEE80211_HE_OPERATION_RTS_THRESHOLD_OFFSET 4
#define IEEE80211_HE_OPERATION_BSS_COLOR_MASK 0x3f000000
#define IEEE80211_HE_OPERATION_BSS_COLOR_OFFSET 24
#define IEEE80211_HE_OPERATION_BSS_COLOR_DISABLED 0x80000000
#define CMD_CBW_80MHZ 2
struct ieee80211_he_mcs_nss_supp { uint16_t rx_mcs_80, tx_mcs_80, rx_mcs_160, tx_mcs_160, rx_mcs_80p80, tx_mcs_80p80; };
struct ieee80211com { int ic_opmode; ieee80211_node *ic_bss; ieee80211_he_mcs_nss_supp ic_he_mcs_nss_supp{}; };
struct mwx_vif { uint8_t idx,omac_idx,band_idx,wmm_idx; struct {uint16_t wcid;} vif_mn; };
struct mwx_softc { ieee80211com sc_ic; mwx_vif sc_vif; struct {uint8_t num_streams,antenna_mask;} sc_capa; };
int ieee80211_mhz2ieee(int f,int) {return f==2484?14:f<3000?(f-2407)/5:(f-5000)/5;}
int mt7921_mcu_chan_bw(ieee80211_channel *c){return c->width;}
/* Mirrors the driver: 80 MHz only once VHT80 is negotiated (stub: width==2 -> center 42). */
void mwx_node_chan_width(ieee80211_node *ni,uint8_t *bw,uint8_t *center){
 *bw=CMD_CBW_20MHZ;*center=ieee80211_mhz2ieee(ni->ni_chan->ic_freq,0);
 if((ni->ni_flags&IEEE80211_NODE_VHT)&&ni->ni_chan->width==2){*bw=CMD_CBW_80MHZ;*center=42;}}
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
 /* Channel width flags are capabilities only: a non-VHT peer is always 20 MHz. */
 n.ni_chan=&c;c.ic_freq=5180;c.width=2;sent.clear();assert(mt7921_mcu_set_associated_bss(&sc,1)==0);assert(sent.size()==2);
 assert(sent[1][9]==36&&sent[1][11]==CMD_CBW_20MHZ&&sent[1][15]==0&&sent[1][16]==0);
 /* VHT80 golden RLM: control 36, center 42, bw 80, 40MHz+ allowed, SCA; phymode A|AC. */
 n.ni_flags=IEEE80211_NODE_VHT;sent.clear();assert(mt7921_mcu_set_associated_bss(&sc,1)==0);assert(sent.size()==2);
 assert(sent[0][29]==(1|(1<<5)));
 std::vector<uint8_t> rlm80={3,0,0,0,2,0,16,0,36,42,0,CMD_CBW_80MHZ,2,3,1,4,1,1,0,0};
 assert(sent[1]==rlm80);
 /* HE basic + BSS color on 5 GHz (default PE=4, RTS=1023) and custom op fields on 2.4 GHz. */
 sc.sc_ic.ic_he_mcs_nss_supp={0xfffa,0xfffa,0xffff,0xffff,0xffff,0xffff};
 n.ni_flags=IEEE80211_NODE_HE;n.ni_he_oper_params=0;sent.clear();assert(mt7921_mcu_set_associated_bss(&sc,1)==0);assert(sent.size()==3);
 assert(sent[0][29]==((1U<<0)|(1U<<7)));
 std::vector<uint8_t> he_def={3,0,0,0, 5,0,16,0, 0xff,0x03, 4, 0, 0xfa,0xff, 0xff,0xff, 0xff,0xff, 0,0, 4,0,8,0, 1,0, 0,0};
 assert(sent[2]==he_def);
 c.ic_freq=2412;c.width=0;n.ni_he_oper_params=3|(120<<4)|(42<<24)|IEEE80211_HE_OPERATION_BSS_COLOR_DISABLED;
 sent.clear();assert(mt7921_mcu_set_associated_bss(&sc,1)==0);assert(sent.size()==3);
 assert(sent[0][29]==((1U<<1)|(1U<<2)|(1U<<6)));
 std::vector<uint8_t> he_2g={3,0,0,0, 5,0,16,0, 120,0, 3, 0, 0xfa,0xff, 0xff,0xff, 0xff,0xff, 0,0, 4,0,8,0, 0,42, 0,0};
 assert(sent[2]==he_2g);
 n.ni_flags=0;n.ni_he_oper_params=0;sent.clear();
 c.width=0;sc.sc_ic.ic_opmode=2;assert(mt7921_mcu_set_associated_bss(&sc,1)==0);assert(sent.empty());
 puts("PASS: real BSS constructor, golden wire packets on 7 channels, VHT80 RLM, HE+BSS color, 20 MHz for non-VHT peers, disassociation, firmware failures, null guards");
}
'''
p=base/'tests/association/bss-context-test.cpp';p.write_text(code)
subprocess.run(['clang++','-std=c++14','-Wall','-Wextra','-fsanitize=address,undefined',str(p),'-o',str(base/'tests/association/bss-context-test')],check=True)
subprocess.run([str(base/'tests/association/bss-context-test')],check=True)
