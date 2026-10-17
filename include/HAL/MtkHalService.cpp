//
//  MtkHalService.cpp
//  SimpleMtkWlan
//
//  Created by laobamac (王孝慈) on 2026/3/18.
//  Copyright © 2026 laobamac (王孝慈). All rights reserved.
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

#include "MtkHalService.hpp"

#define super OSObject
OSDefineMetaClassAndAbstractStructors(MtkHalService, OSObject)

bool MtkHalService::
initWithController(IOEthernetController *controller, IOWorkLoop *workloop, IOCommandGate *commandGate)
{
    this->controller = controller;
    this->controller->retain();
    this->mainWorkLoop = workloop;
    this->mainWorkLoop->retain();
    this->mainCommandGate = commandGate;
    this->mainCommandGate->retain();
    this->inner_attr = lck_attr_alloc_init();
    this->inner_gp_attr = lck_grp_attr_alloc_init();
    this->inner_gp = lck_grp_alloc_init("simplemtkwlan_tsleep", this->inner_gp_attr);
    this->inner_lock = lck_mtx_alloc_init(this->inner_gp, this->inner_attr);
    return true;
}

IOEthernetController *MtkHalService::
getController()
{
    return this->controller;
}

IOCommandGate *MtkHalService::
getMainCommandGate()
{
    return this->mainCommandGate;
}

IOWorkLoop *MtkHalService::
getMainWorkLoop()
{
    return this->mainWorkLoop;
}

void MtkHalService::
wakeupOn(void *ident)
{
//    XYLog("%s\n", __FUNCTION__);
    wakeup(ident);
}

#ifdef AIRPORT
/*
 * Runs with the command gate closed. commandSleep() opens the gate while the
 * thread sleeps, so the work loop keeps delivering interrupts. Kernel
 * wakeup(ident) and commandWakeup(ident) both wake this sleep (same event).
 */
static IOReturn
gateSleepAction(OSObject *owner, void *ident, void *timo, void *gate, void *)
{
    IOCommandGate *commandGate = (IOCommandGate *)gate;
    uint64_t ns = *(uint64_t *)timo;
    uint64_t deadline;
    IOReturn ret;

    if (ns == 0) {
        ret = commandGate->commandSleep(ident, THREAD_INTERRUPTIBLE);
    } else {
        if (ns <= UINT32_MAX)
            clock_interval_to_deadline((uint32_t)ns, kNanosecondScale, &deadline);
        else
            clock_interval_to_deadline((uint32_t)(ns / 1000000), kMillisecondScale, &deadline);
        ret = commandGate->commandSleep(ident, deadline, THREAD_INTERRUPTIBLE);
    }
    return ret == THREAD_AWAKENED ? kIOReturnSuccess : kIOReturnTimeout;
}
#endif

int MtkHalService::
tsleep_nsec(void *ident, int priority, const char *wmesg, uint64_t timo)
{
//    XYLog("%s %s\n", __FUNCTION__, wmesg);
#ifdef AIRPORT
    /*
     * AirportMtkWlan (from pengubow): the IO80211 controller's work loop is
     * also the interrupt work loop and enable() runs with its gate closed, so
     * msleep() on a private lock kept the gate closed and MCU replies were
     * only handled after the wait timed out. Sleep through the gate instead,
     * like itlwm.
     */
    if (this->mainCommandGate != NULL) {
        IOReturn ret = this->mainCommandGate->runAction(gateSleepAction, ident,
            &timo, this->mainCommandGate);
        return ret == kIOReturnSuccess ? 0 : EWOULDBLOCK;
    }
#endif
    struct timespec ts;
    int err;
    memset(&ts, 0, sizeof(struct timespec));
    ts.tv_sec = timo / 1000000000ULL;
    ts.tv_nsec = timo % 1000000000ULL;
    lck_mtx_lock(this->inner_lock);
    err = msleep(ident, this->inner_lock, priority, wmesg, &ts);
    lck_mtx_unlock(this->inner_lock);
    return err;
}

void MtkHalService::
free()
{
    XYLog("%s\n", __PRETTY_FUNCTION__);
    if (this->mainWorkLoop) {
        this->mainWorkLoop->release();
    }
    this->mainWorkLoop = NULL;
    if (this->mainCommandGate) {
        this->mainCommandGate->release();
    }
    this->mainCommandGate = NULL;
    if (this->controller) {
        this->controller->release();
    }
    if (this->inner_lock) {
        lck_attr_free(this->inner_attr);
        lck_mtx_free(this->inner_lock, this->inner_gp);
        lck_grp_free(this->inner_gp);
        lck_grp_attr_free(this->inner_gp_attr);
        this->inner_lock = NULL;
    }
    this->controller = NULL;
    super::free();
}
