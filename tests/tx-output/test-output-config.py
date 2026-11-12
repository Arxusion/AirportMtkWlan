#!/usr/bin/python3
"""Compile actual configureInterface against a contract-recording interface stub."""
from pathlib import Path
import subprocess,re,tempfile
b=Path(__file__).resolve().parent
source=(b.parents[1]/'SimpleMtkWlan/SimpleMtkWlan.cpp').read_text()
fn=source[source.index('bool SimpleMtkWlan::configureInterface('):source.index('struct _ifnet *SimpleMtkWlan::getIfp()')]
stub=r'''
#include <cassert>
#include <cstdio>
#define __PRIVATE_SPI__
#define XYLog(...) ((void)0)
#define OSDynamicCast(t,p) (p)
const int kIONetworkWorkLoopSynchronous=1,kIOReturnSuccess=0,kIONetworkStatsKey=0;
struct IONetworkStats { unsigned collisions; } stats;
struct IONetworkData { void* getBuffer(){return &stats;} } data;
struct IONetworkInterface {
 bool missing=false;int result=0,calls=0,options=-1;
 enum { kOutputPacketSchedulingModelNormal=0 };
 IONetworkData* getParameter(int){return missing?nullptr:&data;}
 int configureOutputPullModel(int,int opt,int,int,int){calls++;options=opt;return result;}
};
using IOEthernetInterface=IONetworkInterface;
struct _ifnet { IONetworkStats* netStat; };
struct Ctrl { struct { _ifnet ac_if; } ic_ac; } ctrl;
void ether_ifattach(_ifnet*,IONetworkInterface*){}
struct Info {int getTxQueueSize(){return 256;}} info;
struct Hal {Ctrl* get80211Controller(){return &ctrl;}Info* getDriverInfo(){return &info;}} hal;
struct Super { bool ok=true;bool configureInterface(IONetworkInterface*){return ok;} };
#define super Super
struct SimpleMtkWlan: Super {Hal* fHalService=&hal;IONetworkStats* fpNetStats;bool configureInterface(IONetworkInterface*);};
'''
main=r'''
int main(){
 SimpleMtkWlan d;IONetworkInterface iface;
 assert(d.configureInterface(&iface));assert(iface.calls==1);assert(iface.options==0);
 iface.result=-1;assert(!d.configureInterface(&iface));
 iface.calls=0;iface.missing=true;assert(!d.configureInterface(&iface));assert(iface.calls==0);
 iface.missing=false;d.ok=false;assert(!d.configureInterface(&iface));assert(iface.calls==0);
 puts("PASS: extracted configureInterface uses async output pull thread (0, with gated batching in outputStart), propagates pull-configuration failure, preserves early failures. Host contract test only, not Darwin scheduler/hardware validation.");
}
'''
tmp=tempfile.TemporaryDirectory(prefix='mtk-tx-test-');art=Path(tmp.name)
f=art/'test-output-config.cpp';f.write_text(stub+fn+main)
subprocess.run(['clang++','-std=c++14','-fsanitize=address,undefined','-g',str(f),'-o',str(art/'test-output-config')],check=True)
subprocess.run([str(art/'test-output-config')],check=True)
