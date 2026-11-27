#!/usr/bin/env python3
"""Exercise production interrupt completion ordering and timeout ownership."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build/tests/bluetooth"
OUT.mkdir(parents=True, exist_ok=True)
source = (ROOT / "bluetooth/AirportMtkBtFw/USBDeviceController.cpp").read_text()
header = (ROOT / "bluetooth/AirportMtkBtFw/USBDeviceController.hpp").read_text()


def function(signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


code = r'''
#include <cassert>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <thread>
using IOReturn=int;using AbsoluteTime=uint64_t;
constexpr int kIOReturnSuccess=0,kIOReturnTimeout=-1,kIOReturnOverrun=-2;
constexpr int kIOReturnError=-3,kIOReturnAborted=-4,kIOUSBPipeStalled=-5;
constexpr int kMillisecondScale=1,THREAD_UNINT=0,THREAD_TIMED_OUT=1,THREAD_AWAKENED=0;
#define XYLog(...) ((void)0)
#define OSDynamicCast(type,value) static_cast<type *>(value)
struct OSObject {};
struct IOLock { std::mutex mutex; std::condition_variable condition; };
void IOLockLock(IOLock *lock){lock->mutex.lock();}
void IOLockUnlock(IOLock *lock){lock->mutex.unlock();}
void IOLockWakeup(IOLock *lock,void *,bool){lock->condition.notify_one();}
void clock_interval_to_deadline(unsigned ms,int,uint64_t *deadline) {
    *deadline=std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count()+ms*1000000ULL;
}
int IOLockSleepDeadline(IOLock *lock,void *,AbsoluteTime deadline,int) {
    std::unique_lock<std::mutex> held(lock->mutex,std::adopt_lock);
    auto until=std::chrono::steady_clock::time_point(std::chrono::nanoseconds(deadline));
    auto result=lock->condition.wait_until(held,until);
    held.release();
    return result==std::cv_status::timeout ? THREAD_TIMED_OUT : THREAD_AWAKENED;
}
struct Buffer {
    uint8_t data[4096]={1,2,3,4};
    size_t getLength(){return sizeof(data);}
    void *getBytesNoCopy(){return data;}
};
struct IOUSBHostCompletion {
    void *owner,*parameter;
    void (*action)(void *,void *,IOReturn,uint32_t);
};
struct IOUSBHostIOSource { enum {kAbortSynchronous=1}; };
struct Pipe {
    enum Mode {Immediate,Delayed,Timeout,TransferError,EnqueueError,Empty,Oversize};
    Mode mode=Immediate;
    IOUSBHostCompletion completion{};
    std::thread worker;
    std::atomic<bool> pending{false};
    bool synchronousAbort=false;
    ~Pipe(){if(worker.joinable())worker.join();assert(!pending);}
    void finish(int result,unsigned length) {
        pending=false;
        completion.action(completion.owner,completion.parameter,result,length);
    }
    int io(Buffer *,uint32_t,IOUSBHostCompletion *done,uint32_t timeout) {
        assert(timeout==0); // USB interrupt transfers require a separate deadline.
        if(mode==EnqueueError)return kIOReturnError;
        completion=*done;pending=true;
        if(mode==Timeout)return 0;
        if(mode==Delayed) {
            worker=std::thread([this] {std::this_thread::sleep_for(std::chrono::milliseconds(2));finish(0,4);});
        } else {
            finish(mode==TransferError?kIOReturnError:0,mode==Empty?0:mode==Oversize?100:4);
        }
        return 0;
    }
    void clearStall(bool){assert(false);}
    void abort(unsigned flags) {
        assert(flags==IOUSBHostIOSource::kAbortSynchronous);
        synchronousAbort=true;
        if(pending)finish(kIOReturnAborted,0);
    }
};
'''
code += header[header.index("typedef struct {"):header.index("class USBDeviceController")]
code += r'''
struct USBDeviceController : OSObject {
    IOLock *_hciLock;Pipe *m_pInterruptReadPipe;Buffer *mReadBuffer;
    static void interruptHandler(void *,void *,IOReturn,uint32_t);
    IOReturn interruptPipeRead(void *,uint32_t,uint32_t *,uint32_t);
    const char *stringFromReturn(int){return "mock USB result";}
};
'''
code += function("void USBDeviceController::\ninterruptHandler")
code += function("IOReturn USBDeviceController::\ninterruptPipeRead")
code += r'''
int main() {
    unsigned cases=0;
    for(auto mode : {Pipe::Immediate,Pipe::Delayed,Pipe::Timeout,Pipe::TransferError,
                    Pipe::EnqueueError,Pipe::Empty,Pipe::Oversize}) {
        IOLock lock;Pipe pipe;pipe.mode=mode;Buffer buffer;
        USBDeviceController usb;usb._hciLock=&lock;usb.m_pInterruptReadPipe=&pipe;usb.mReadBuffer=&buffer;
        uint8_t out[8]={};uint32_t size=0;
        int result=usb.interruptPipeRead(out,sizeof(out),&size,mode==Pipe::Timeout?5:100);
        if(mode==Pipe::Immediate||mode==Pipe::Delayed) {
            assert(result==0 && size==4 && !memcmp(out,buffer.data,4));
        } else if(mode==Pipe::Timeout) {
            assert(result==kIOReturnTimeout && pipe.synchronousAbort && !pipe.pending);
        } else if(mode==Pipe::Empty||mode==Pipe::Oversize) {
            assert(result==kIOReturnOverrun && size==0);
        } else {
            assert(result==kIOReturnError && size==0);
        }
        ++cases;
    }
    printf("PASS: %u production interrupt completion/ownership cases\n",cases);
}
'''
cpp = OUT / "interrupt.cpp"
cpp.write_text(code)
binary = OUT / "interrupt"
subprocess.run([os.environ.get("CXX", "clang++"), "-std=c++14", "-pthread", "-g",
                "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                str(cpp), "-o", str(binary)], check=True)
subprocess.run([str(binary)], check=True)
