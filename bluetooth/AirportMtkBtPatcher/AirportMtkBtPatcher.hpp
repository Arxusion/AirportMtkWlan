//
//  AirportMtkBtPatcher.hpp
//  AirportMtkBtFw
//
//  Created by laobamac on 2026/5/30.
//  Copyright © 2026 Aswini Soni (@Arxusion). All rights reserved.
//

//
//  AirportMtkBtPatcher.h
//  AirportMtkBtPatcher
//
//  Created by zxystd <zxystd@foxmail.com> on 2021/2/8.
//

#ifndef AirportMtkBtPatcher_h
#define AirportMtkBtPatcher_h

#include <Headers/kern_patcher.hpp>

#include <IOKit/usb/IOUSBHostDevice.h>

#define DRV_NAME "smbtp"

class CAirportMtkBtPatcher {
public:
    bool init();
    void free();
    
    void processKext(KernelPatcher &patcher, size_t index, mach_vm_address_t address, size_t size);
    static IOReturn newFindQueueRequest(void *that, unsigned short arg1, void *addr, unsigned short arg2, bool arg3, void **hciRequestPtr);
    
    mach_vm_address_t oldFindQueueRequest {};
};

#endif /* AirportMtkBtPatcher_h */
