#!/usr/bin/env python3
"""Exercise the production WMT status and HCI handoff functions with USB replies."""
from pathlib import Path
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build/tests/bluetooth"
OUT.mkdir(parents=True, exist_ok=True)


def function(text, signature):
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


source = (ROOT / "bluetooth/AirportMtkBtFw/BtMtk.cpp").read_text()
header = (ROOT / "bluetooth/AirportMtkBtFw/BtMtk.h").read_text()
hci = (ROOT / "bluetooth/AirportMtkBtFw/Hci.h").read_text()
prelude = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <vector>
using u8=uint8_t; using u16=uint16_t; using u32=uint32_t;
using __le16=u16; using __be16=u16; using __le32=u32;
using IOReturn=int;
constexpr int kIOReturnSuccess=0, kIOReturnTimeout=-1, kMillisecondScale=1;
#define XYLog(...) ((void)0)
#define OSSwapHostToLittleInt16(x) (x)
#define OSSwapLittleToHostInt16(x) (x)
#define OSSwapBigToHostInt16(x) __builtin_bswap16(x)
uint64_t now;
void clock_interval_to_deadline(unsigned ms,int,uint64_t *out) { *out=now+ms*1000000ULL; }
void clock_get_uptime(uint64_t *out) { *out=now; }
void absolutetime_to_nanoseconds(uint64_t value,uint64_t *out) { *out=value; }
'''
prelude += hci[hci.index("typedef struct"):hci.index("/* ---- HCI Events")]
for name in ["HCI_COMMAND_HDR_SIZE", "HCI_INIT_TIMEOUT", "HCI_CMD_TIMEOUT",
             "HCI_OP_RESET", "HCI_OP_READ_LOCAL_VERSION", "HCI_OP_READ_BD_ADDR", "HCI_EV_CMD_COMPLETE"]:
    prelude += re.search(r"^#define\s+" + name + r"\s+.*$", hci, re.M)[0] + "\n"
for name in ["BTMTK_CMD_BUF_SIZE", "BTMTK_WMT_EVENT_SIZE", "BTMTK_HCI_WMT_OPCODE", "HCI_EV_WMT"]:
    prelude += re.search(r"^#define\s+" + name + r"\s+.*$", header, re.M)[0] + "\n"
prelude += header[header.index("enum {"):header.index("class BtMtk")]
prelude += r'''
struct USBDeviceController {
    int sendResult=0, readResult=0;
    uint64_t readTime=1000000;
    std::vector<uint16_t> sent;
    std::vector<uint8_t> command, wmt;
    std::deque<std::vector<uint8_t>> events;
    int sendHCIRequest(HciCommandHdr *cmd,unsigned) {
        sent.push_back(cmd->opcode);
        command.assign((u8 *)cmd,(u8 *)cmd+3+cmd->len);
        return sendResult;
    }
    int readWMTEvent(void *out,unsigned cap,u32 *len,unsigned) {
        assert(wmt.size()<=cap); *len=wmt.size(); memcpy(out,wmt.data(),*len); return readResult;
    }
    int interruptPipeRead(void *out,unsigned cap,u32 *len,unsigned timeout) {
        assert(timeout>0 && timeout<=HCI_CMD_TIMEOUT+1);
        now+=readTime;
        if (readResult) return readResult;
        if (events.empty()) return kIOReturnTimeout;
        auto event=events.front(); events.pop_front();
        assert(event.size()<=cap); *len=event.size(); memcpy(out,event.data(),*len); return 0;
    }
    const char *stringFromReturn(int) { return "mock USB result"; }
};
struct BtMtk {
    USBDeviceController *m_pUSBDeviceController;
    bool hciWmtSync(btmtk_hci_wmt_params *);
    bool enableBluetoothProtocol(bool);
    bool verifyHciController();
};
'''
main = r'''
std::vector<u8> complete(u16 opcode,unsigned count) {
    std::vector<u8> e(5+count,0);
    e[0]=0x0e;e[1]=e.size()-2;e[2]=1;e[3]=opcode;e[4]=opcode>>8;
    if(opcode==0x1009) e[6]=0x12;
    return e;
}
USBDeviceController ready() {
    now=0;USBDeviceController usb;
    usb.events={complete(0x0c03,1),complete(0x1001,9),complete(0x1009,7)};
    return usb;
}
int main() {
    unsigned cases=0;
    {auto usb=ready();BtMtk bt{&usb};assert(bt.verifyHciController());
     assert((usb.sent==std::vector<u16>{0x0c03,0x1001,0x1009}));assert(usb.events.empty());++cases;}
    {auto usb=ready();usb.events.push_front({0xff,1,0});BtMtk bt{&usb};assert(bt.verifyHciController());++cases;}
    for(int fault=0;fault<9;++fault) {
        auto usb=ready();
        switch(fault) {
          case 0:usb.sendResult=-4;break;
          case 1:usb.readResult=-5;break;
          case 2:usb.events[0][5]=0x0c;break;
          case 3:usb.events[0][3]=0x01;break;
          case 4:usb.events[0].pop_back();break;
          case 5:usb.events[2][6]=0;break;
          case 6:for(unsigned i=6;i<12;++i) usb.events[2][i]=0xff;break;
          case 7:usb.events.clear();break;
          case 8:usb.events.push_front({0xff,1,0});usb.readTime=3000000000ULL;break;
        }
        BtMtk bt{&usb};assert(!bt.verifyHciController());++cases;
    }
    // MT7922's short FUNC_CTRL acknowledgement: zero flag succeeds; a
    // negative acknowledgement must not become FirmwareLoaded=true.
    for(unsigned flag=0;flag<3;++flag) {
        USBDeviceController usb;usb.wmt={0xe4,5,2,6,1,0,u8(flag)};
        BtMtk bt{&usb};assert(bt.enableBluetoothProtocol(true)==(flag==0));
        assert((usb.command==std::vector<u8>{0x6f,0xfc,6,1,6,2,0,0,1}));++cases;
    }
    for(auto status : {0x0404,0x0420,0x0000}) {
        USBDeviceController usb;usb.wmt={0xe4,7,2,6,3,0,0,u8(status>>8),u8(status)};
        BtMtk bt{&usb};assert(bt.enableBluetoothProtocol(true)==(status==0x0404));++cases;
    }
    for(int fault=0;fault<6;++fault) {
        USBDeviceController usb;usb.wmt={0xe4,5,2,6,1,0,0};
        switch(fault) {
          case 0:usb.wmt[0]=0xff;break;
          case 1:usb.wmt[1]=7;break;
          case 2:usb.wmt[2]=1;break;
          case 3:usb.wmt[3]=1;break;
          case 4:usb.wmt[4]=3;break;
          case 5:usb.readResult=-2;break;
        }
        BtMtk bt{&usb};assert(!bt.enableBluetoothProtocol(true));++cases;
    }
    printf("PASS: %u production WMT/HCI handoff cases\n",cases);
}
'''
code = prelude + "\n".join(function(source, "bool BtMtk::" + name)
                           for name in ["hciWmtSync", "enableBluetoothProtocol", "verifyHciController"]) + main
cpp = OUT / "handoff.cpp"
cpp.write_text(code)
binary = OUT / "handoff"
subprocess.run([os.environ.get("CXX", "clang++"), "-std=c++14", "-g",
                "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                str(cpp), "-o", str(binary)], check=True)
subprocess.run([str(binary)], check=True)
