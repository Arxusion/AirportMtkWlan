from pathlib import Path
import re,subprocess
b=Path(__file__).resolve().parents[2]
out=Path(__file__).resolve().parent
s=(b/'mtk80211/openbsd/sys/_task.cpp').read_text()
s=re.sub(r'^#include[^\n]*\n','',s,flags=re.M)
stubs=r'''
#include <sys/queue.h>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <cassert>
#include <mutex>
#include <thread>
#include <condition_variable>
#include <atomic>
#include <chrono>
using IORecursiveLock=std::recursive_mutex;
IORecursiveLock* IORecursiveLockAlloc(){return new IORecursiveLock;}
void IORecursiveLockFree(IORecursiveLock*p){delete p;}
void IORecursiveLockLock(IORecursiveLock*p){p->lock();}
void IORecursiveLockUnlock(IORecursiveLock*p){p->unlock();}
void* IOMalloc(size_t n){return malloc(n);}void IOFree(void*p,size_t){free(p);}
using thread_call_param_t=void*;
struct Call{void(*fn)(void*,void*);void*arg;std::mutex m;std::condition_variable cv;bool pending=false,running=false,resched=false,stop=false;std::thread worker;};
using thread_call_t=Call*;
#define THREAD_CALL_PRIORITY_KERNEL 1
#define THREAD_CALL_OPTIONS_ONCE 1
Call*thread_call_allocate_with_options(void(*fn)(void*,void*),void*arg,int,int){
 auto*c=new Call;c->fn=fn;c->arg=arg;
 c->worker=std::thread([c]{std::unique_lock<std::mutex> l(c->m);for(;;){c->cv.wait(l,[c]{return c->pending||c->stop;});if(c->stop)return;c->pending=false;c->running=true;l.unlock();c->fn(c->arg,nullptr);l.lock();c->running=false;if(c->resched){c->resched=false;c->pending=true;}c->cv.notify_all();}});return c;
}
// xnu THREAD_CALL_ONCE: entering a running call reschedules it once; enter returns TRUE if nothing new was scheduled
bool thread_call_enter(Call*c){std::lock_guard<std::mutex> l(c->m);bool r;if(c->running){r=c->resched;c->resched=true;}else{r=c->pending;c->pending=true;}c->cv.notify_all();return r;}
bool thread_call_cancel(Call*c){std::lock_guard<std::mutex> l(c->m);if(c->pending){c->pending=false;return true;}if(c->resched){c->resched=false;return true;}return false;}
void IOSleep(unsigned ms){std::this_thread::sleep_for(std::chrono::milliseconds(ms));}
int IOLog(const char*,...){return 0;}
bool thread_call_free(Call*c){{std::lock_guard<std::mutex> l(c->m);c->stop=true;c->cv.notify_all();}c->worker.join();delete c;return true;}
struct task{TAILQ_ENTRY(task)t_entry;void(*t_func)(void*);void*t_arg;unsigned t_flags;char name[256];};
TAILQ_HEAD(task_list,task);
#define TASK_ONQUEUE 1
'''
tests=r'''
struct Block{std::atomic<bool> entered{false},release{false};};
void block(void*p){auto*b=(Block*)p;b->entered=true;while(!b->release)std::this_thread::yield();}
void count(void*p){++*(std::atomic<int>*)p;}
void wait(std::atomic<bool>&b){auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);while(!b){assert(std::chrono::steady_clock::now()<end);std::this_thread::yield();}}
int main(){
 for(int iteration=0;iteration<30;iteration++){
  assert(taskq_init());assert(!taskq_init());
  auto*q=taskq_create("test",1,0,0);assert(q);Block b;task busy{},pending{};std::atomic<int> calls{0};
  task_set(&busy,block,&b,"b");task_set(&pending,count,&calls,"p");
  assert(task_add(q,&busy));wait(b.entered);
  assert(task_add(q,&pending));assert(!task_add(q,&pending));
  assert(!task_del(systq,&pending));assert(pending.t_flags&TASK_ONQUEUE);
  std::atomic<bool> done{false};std::thread closer([&]{taskq_quiesce(q);done=true;});
  bool stopping=false;while(!stopping){IORecursiveLockLock(q->lock);stopping=q->stopping;IORecursiveLockUnlock(q->lock);}
  assert(!done);assert(!task_add(q,&pending));assert(!(pending.t_flags&TASK_ONQUEUE));
  b.release=true;closer.join();assert(done);assert(calls==0);taskq_destroy(q);
  task many[100]{};for(auto&t:many){task_set(&t,count,&calls,"run");assert(task_add(systq,&t));}
  auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(calls<100){assert(std::chrono::steady_clock::now()<end);std::this_thread::yield();}
  taskq_destroy(systq);assert(systq->lock==nullptr);
 }
 puts("PASS 30 lifecycles: active callback drain, pending cancellation, reject late submissions, deduplication, wrong-queue protection, 3000 callbacks and global reinitialization.");
}
'''
p=out/'test-queue.cpp';p.write_text(stubs+s+tests);exe=p.with_suffix('')
subprocess.run(['clang++','-std=c++14','-pthread','-fsanitize=address,undefined',str(p),'-o',str(exe)],check=True)
r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30);(out/'test-queue-result.txt').write_text(r.stdout+r.stderr);print(r.stdout,r.stderr);assert r.returncode==0
