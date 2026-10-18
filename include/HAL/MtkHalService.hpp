//
//  MtkHalService.hpp
//  SimpleMtkWlan
//
//  Created by laobamac (王孝慈) on 2026/3/30.
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

#ifndef MtkHalService_hpp
#define MtkHalService_hpp

#include <libkern/c++/OSObject.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOService.h>
#include <IOKit/IOCommandGate.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/pci/IOPCIDevice.h>
#include <IOKit/network/IOEthernetController.h>
#include <IOKit/network/IOEthernetInterface.h>

#include "MtkDriverInfo.hpp"
#include "MtkDriverController.hpp"

#include <net80211/ieee80211_var.h>

class MtkHalService : public OSObject {
    OSDeclareAbstractStructors(MtkHalService)
    
public:
    
    virtual bool attach(IOPCIDevice *device) = 0;
    
    virtual void detach(IOPCIDevice *device) = 0;
    
    virtual IOReturn enable(IONetworkInterface *interface) = 0;
    
    virtual IOReturn disable(IONetworkInterface *interface) = 0;
    
    virtual struct ieee80211com *get80211Controller() = 0;
#ifdef AIRPORT_WCL
    /* Native Wi-Fi (AirportMtkWlan): off-channel time per channel macOS asks scans to use. */
    virtual IOReturn setScanHomeAwayTime(uint32_t) { return kIOReturnUnsupported; }
#endif
    
    virtual MtkDriverInfo *getDriverInfo() = 0;
    
    virtual MtkDriverController *getDriverController() = 0;
    
    /* Periodic hardware state dump / interrupt poll, called on the main work loop. */
    virtual void debugPoll() {}

    /*
     * System sleep / wake, called on the main work loop by the front end's
     * power state change. The card loses power in S3: suspend() quiets it,
     * resume() takes it back and reloads the firmware.
     */
    virtual void suspend() {}
    virtual void resume() {}
    
    virtual void free() override;

public:
    virtual bool initWithController(IOEthernetController *controller, IOWorkLoop *workloop, IOCommandGate *commandGate);
    
protected:
    
    int tsleep_nsec(void *ident, int priority, const char *wmesg, uint64_t timo);
    
    void wakeupOn(void* ident);
    
    IOEthernetController *getController();
    
    IOCommandGate *getMainCommandGate();
    
    IOWorkLoop *getMainWorkLoop();
    
private:
    IOEthernetController *controller;
    IOCommandGate *mainCommandGate;
    IOWorkLoop *mainWorkLoop;

    lck_grp_t *inner_gp;
    lck_grp_attr_t *inner_gp_attr;
    lck_attr_t *inner_attr;
    lck_mtx_t *inner_lock;
};

#endif /* MtkHalService_hpp */
