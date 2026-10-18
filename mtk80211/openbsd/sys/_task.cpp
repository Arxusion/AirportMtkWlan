//
//  _task.cpp
//  SimpleMtkWlan
//
//  Created by laobamac (王孝慈) on 2026/4/15.
//  Copyright © 2026 laobamac (王孝慈). All rights reserved.
//

//
//  _task.cpp
//  SimpleMtkWlan
//
//  Created by qcwap on 2020/3/1.
//  Copyright © 2020 钟先耀. All rights reserved.
//

/*
* Copyright (C) 2020  钟先耀
*
* This program is free software; you can redistribute it and/or modify
* it under the terms of the GNU General Public License as published by
* the Free Software Foundation; either version 2 of the License, or
* (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU General Public License for more details.
*/

#include <sys/_task.h>
#include <IOKit/IOLib.h>
#include <kern/thread_call.h>

/* The HAL owns each queue. Quiesce before destroying callback arguments.
 * No producer may use a queue after taskq_destroy().
 */
struct taskq {
    IORecursiveLock *lock;
    thread_call_t call;
    struct task_list work;
    bool stopping;
    int inflight;   /* invocations scheduled and not yet returned, under lock (replaces thread_call_cancel_wait) */
};
static struct taskq system_queue;
struct taskq *const systq = &system_queue;

static void taskq_run(thread_call_param_t arg, thread_call_param_t)
{
    struct taskq *q = (struct taskq *)arg;
    for (;;) {
        IORecursiveLockLock(q->lock);
        struct task *item = TAILQ_FIRST(&q->work);
        if (q->stopping || item == NULL) {
            q->inflight--;
            IORecursiveLockUnlock(q->lock);
            return;
        }
        TAILQ_REMOVE(&q->work, item, t_entry);
        item->t_flags &= ~TASK_ONQUEUE;
        struct task work = *item;
        IORecursiveLockUnlock(q->lock);
        work.t_func(work.t_arg);
    }
}

static bool taskq_setup(struct taskq *q)
{
    q->lock = IORecursiveLockAlloc();
    if (!q->lock) return false;
    TAILQ_INIT(&q->work);
    q->stopping = false;
    q->inflight = 0;
    q->call = thread_call_allocate_with_options(taskq_run, q,
        THREAD_CALL_PRIORITY_KERNEL, THREAD_CALL_OPTIONS_ONCE);
    if (!q->call) {
        IORecursiveLockFree(q->lock);
        q->lock = NULL;
        return false;
    }
    return true;
}

bool taskq_init(void)
{
    /* A second live HAL must not reinitialize the global queue. */
    if (systq->lock != NULL) return false;
    return taskq_setup(systq);
}

struct taskq *taskq_create(const char *, unsigned int nthreads, int, unsigned int)
{
    if (nthreads != 1) return NULL;
    struct taskq *q = (struct taskq *)IOMalloc(sizeof(*q));
    if (!q) return NULL;
    bzero(q, sizeof(*q));
    if (!taskq_setup(q)) { IOFree(q, sizeof(*q)); return NULL; }
    return q;
}

void taskq_quiesce(struct taskq *q)
{
    if (!q || !q->lock) return;
    IORecursiveLockLock(q->lock);
    q->stopping = true;
    struct task *item;
    while ((item = TAILQ_FIRST(&q->work)) != NULL) {
        TAILQ_REMOVE(&q->work, item, t_entry);
        item->t_flags &= ~TASK_ONQUEUE;
    }
    IORecursiveLockUnlock(q->lock);
    /* task_add and resubmission are now rejected under the same lock. */
    /* thread_call_cancel_wait is private KPI (kmutil refuses to link it). thread_call_cancel returns TRUE when it
       removed a scheduled invocation (also a running ONCE call's reschedule); then wait until every invocation that
       did start has returned (each one sees `stopping` and takes no work). Bounded like the ring log's stop. */
    if (thread_call_cancel(q->call)) {
        IORecursiveLockLock(q->lock);
        q->inflight--;
        IORecursiveLockUnlock(q->lock);
    }
    for (int i = 0; i < 5000; i++) {
        IORecursiveLockLock(q->lock);
        int n = q->inflight;
        IORecursiveLockUnlock(q->lock);
        if (n <= 0) return;
        IOSleep(1);
    }
    IOLog("SimpleMtkWlan: taskq_quiesce: callback still running after 5 s\n");
}

void taskq_destroy(struct taskq *q)
{
    if (!q || !q->lock) return;
    taskq_quiesce(q);
    thread_call_free(q->call);
    q->call = NULL;
    IORecursiveLockFree(q->lock);
    q->lock = NULL;
    if (q != systq) IOFree(q, sizeof(*q));
}

void task_set(struct task *t, void (*fn)(void *), void *arg, const char *name)
{
    t->t_func = fn;
    t->t_arg = arg;
    t->t_flags = 0;
    strlcpy(t->name, name, sizeof(t->name));
}

int task_add(struct taskq *q, struct task *t)
{
    if (!q || !q->lock) return 0;
    IORecursiveLockLock(q->lock);
    if (q->stopping || (t->t_flags & TASK_ONQUEUE)) {
        IORecursiveLockUnlock(q->lock);
        return 0;
    }
    t->t_flags |= TASK_ONQUEUE;
    TAILQ_INSERT_TAIL(&q->work, t, t_entry);
    /* Submit while locked, so shutdown cannot miss a late submission. FALSE = a new invocation was scheduled
       (TRUE: one is already pending and will see this task). */
    if (!thread_call_enter(q->call))
        q->inflight++;
    IORecursiveLockUnlock(q->lock);
    return 1;
}

int task_del(struct taskq *q, struct task *t)
{
    if (!q || !q->lock) return 0;
    IORecursiveLockLock(q->lock);
    /* Validate membership rather than trusting a flag from another queue. */
    struct task *item;
    TAILQ_FOREACH(item, &q->work, t_entry) {
        if (item == t) {
            TAILQ_REMOVE(&q->work, t, t_entry);
            t->t_flags &= ~TASK_ONQUEUE;
            IORecursiveLockUnlock(q->lock);
            return 1;
        }
    }
    IORecursiveLockUnlock(q->lock);
    return 0;
}
