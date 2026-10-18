root=ARGV.fetch(0)
src=File.read(File.join(root,'SimpleMtkWlan/hal_mwx/MtkMwx.cpp'))
hdr=File.read(File.join(root,'SimpleMtkWlan/hal_mwx/if_mwxreg.h'))
structs=%w[mt76_connac_mcu_scan_ssid mt76_connac_mcu_scan_channel mt76_connac_hw_scan_req].map do |name|
 hdr.match(/^struct #{name} \{.*?^\} __packed;/m).to_s.tap{|v|abort 'Missing struct' if v.empty?}
end.join("\n")
fn=src.match(/^int\nmt7921_mcu_hw_scan\(.*?^\}\n/m).to_s
abort 'Missing function' if fn.empty?
print <<'CPP'
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <cerrno>
#include <algorithm>
#define __packed __attribute__((packed))
#define IEEE80211_NWID_LEN 32
#define IEEE80211_ADDR_LEN 6
#define ETHER_ADDR_LEN 6
#define IEEE80211_CHAN_MAX 255
#define MT76_HW_SCAN_IE_LEN 600
#define SCAN_FUNC_SPLIT_SCAN 0x20
#define SCAN_FUNC_RANDOM_MAC 0x1
#define MWX_FLAG_SCANNING 1
#define MWX_FLAG_BGSCAN 2
#define MCU_CE_CMD_START_HW_SCAN 1
#define htole16(x) (x)
#define htole32(x) (x)
#define le16toh(x) (x)
#define le32toh(x) (x)
#define MWX_DEV_LOG(...) ((void)0)
CPP
puts structs
print <<'CPP'
struct ieee80211_channel {unsigned ic_flags,ic_freq;};
struct ieee80211com {ieee80211_channel ic_channels[256];};
struct mwx_softc {ieee80211com sc_ic;unsigned sc_flags;uint8_t sc_scan_seq_num;};
struct mbuf {unsigned char bytes[sizeof(mt76_connac_hw_scan_req)];};
#define mtod(m,T) reinterpret_cast<T>((m)->bytes)
#define IEEE80211_IS_CHAN_2GHZ(c) ((c)->ic_freq<100)
static unsigned ieee80211_mhz2ieee(unsigned freq,int){return freq;}
static unsigned char poison;
static char nmx_wifi_band;
static bool alloc_fail;
static int send_error;
static mt76_connac_hw_scan_req captured;
static mbuf storage;
static mbuf *mwx_mcu_alloc_msg(size_t n){if(alloc_fail)return nullptr;if(n!=sizeof(storage.bytes))std::abort();memset(storage.bytes,poison,n);return &storage;}
static int mwx_mcu_send_mbuf(mwx_softc*,unsigned,mbuf*m,int*){memcpy(&captured,m->bytes,sizeof(captured));return send_error;}
CPP
puts fn
print <<'CPP'
static void check(bool ok,const char*reason){if(!ok){fprintf(stderr,"FAIL: %s\n",reason);exit(1);}}
static void zeros(const void*p,size_t n,const char*reason){auto b=static_cast<const unsigned char*>(p);for(size_t i=0;i<n;i++)check(b[i]==0,reason);}
int main(){
 unsigned cases=0;
 for(char band: {'2','\0'}) for(unsigned seed: {0x00,0xbd,0xfb,0xff}) for(unsigned n: {0,1,14,32,33,41,64,65}) for(int bg: {0,1}) {
  nmx_wifi_band=band; poison=seed; mwx_softc sc={}; sc.sc_scan_seq_num=127;
  for(unsigned i=1;i<=n;i++){sc.sc_ic.ic_channels[i].ic_flags=1;sc.sc_ic.ic_channels[i].ic_freq=i<=14?i:100+i;}
  check(mt7921_mcu_hw_scan(&sc,bg)==0,"scan return");
  check(captured.scan_func==SCAN_FUNC_SPLIT_SCAN,"scan_func contains stale allocation bits");
  check(captured.ies_len==0,"uninitialised IE length");
  check(captured.ext_ssids_num==0,"uninitialised extra SSID count");
  check(captured.probe_delay_time==0,"uninitialised probe delay");
  check(captured.seq_num==0,"sequence wrap");
  check(captured.channels_num==std::min(n,32u),"primary channel count");
  check(captured.ext_channels_num==(n>32?std::min(n,64u)-32:0),"extra channel count");
  check(captured.timeout_value==std::min(n,64u)*120,"timeout");
  check(captured.channel_dwell_time==120 && captured.channel_min_dwell_time==120,"dwell");
  check(captured.channel_type==(n?4:0),"channel type");
  check(captured.ssid_type==1 && captured.ssid_type_ext==0 && captured.ssids_num==0,"SSID mode");
  check(captured.version==1 && captured.scan_type==0 && captured.probe_req_num==0,"scan mode");
  zeros(captured.pad,sizeof(captured.pad),"reserved padding");
  zeros(captured.ies,sizeof(captured.ies),"unused IE bytes");
  zeros(captured.ssids,sizeof(captured.ssids),"unused SSIDs");
  zeros(captured.ext_ssids,sizeof(captured.ext_ssids),"unused extra SSIDs");
  zeros(captured.random_mac,sizeof(captured.random_mac),"disabled random MAC");
  for(auto v:captured.bssid)check(v==0xff,"wildcard BSSID");
  // nullmoth-wifi-band=2: channel table order; unset (prefer 5 GHz): the 5 GHz channels first, then 2.4 GHz
  unsigned exp_band[128],exp_num[128],e=0;
  if(band=='2') for(unsigned i=1;i<=n;i++){exp_band[e]=i<=14?1:2;exp_num[e++]=i<=14?i:100+i;}
  else {for(unsigned i=15;i<=n;i++){exp_band[e]=2;exp_num[e++]=100+i;} for(unsigned i=1;i<=n&&i<=14;i++){exp_band[e]=1;exp_num[e++]=i;}}
  for(unsigned i=0;i<std::min(n,64u);i++) {auto c=i<32?captured.channels[i]:captured.ext_channels[i-32];check(c.band==exp_band[i],"band");check(c.channel_num==exp_num[i],"channel");}
  cases++;
 }
 mwx_softc sc={};sc.sc_scan_seq_num=42;alloc_fail=true;
 check(mt7921_mcu_hw_scan(&sc,1)==ENOMEM,"allocation failure");check(sc.sc_flags==0 && sc.sc_scan_seq_num==42,"allocation failure state");
 alloc_fail=false;send_error=EIO;sc.sc_flags=MWX_FLAG_BGSCAN;
 check(mt7921_mcu_hw_scan(&sc,1)==EIO,"send failure");check(sc.sc_flags==0,"send failure flags");
 printf("PASS: %u poisoned-buffer/channel/background combinations + allocation/send failure paths\n",cases);
}
CPP
