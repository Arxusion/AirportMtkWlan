//
//  AirportMtkBtPatcher.cpp
//  AirportMtkBtFw
//
//  Created by laobamac on 2026/5/30.
//  Copyright © 2026 Aswini Soni (@Arxusion). All rights reserved.
//

//
//  AirportMtkBtPatcher.cpp
//  AirportMtkBtPatcher
//
//  Created by zxystd <zxystd@foxmail.com> on 2021/2/8.
//

#include <Headers/kern_api.hpp>
#include <Headers/kern_util.hpp>
#include <Headers/plugin_start.hpp>

#include "AirportMtkBtPatcher.hpp"
#include "BlueToolCompat.hpp"

static CAirportMtkBtPatcher mtkBtPatcher;
static CAirportMtkBtPatcher *callbackMtkBtPatcher = nullptr;

static const char *bootargOff[] {
    "-smbtcompatoff"
};

static const char *bootargDebug[] {
    "-smbtcompatdbg"
};

static const char *bootargBeta[] {
    "-smbtcompatbeta"
};

PluginConfiguration ADDPR(config) {
    xStringify(PRODUCT_NAME),
    parseModuleVersion(xStringify(MODULE_VERSION)),
    LiluAPI::AllowNormal | LiluAPI::AllowInstallerRecovery | LiluAPI::AllowSafeMode,
    bootargOff,
    arrsize(bootargOff),
    bootargDebug,
    arrsize(bootargDebug),
    bootargBeta,
    arrsize(bootargBeta),
    KernelVersion::MountainLion,
    KernelVersion::Tahoe,
    []() {
        mtkBtPatcher.init();
    }
};

static const char *AirportMtkBtPatcher_IOBluetoothFamily[] { "/System/Library/Extensions/IOBluetoothFamily.kext/Contents/MacOS/IOBluetoothFamily" };

static KernelPatcher::KextInfo AirportMtkBtPatcher_IOBluetoothInfo {
    "com.apple.iokit.IOBluetoothFamily",
    AirportMtkBtPatcher_IOBluetoothFamily,
    1,
    {true, true},
    {},
    KernelPatcher::KextInfo::Unloaded
};

bool CAirportMtkBtPatcher::init()
{
    DBGLOG(DRV_NAME, "%s", __PRETTY_FUNCTION__);
    callbackMtkBtPatcher = this;
    if (getKernelVersion() < KernelVersion::Monterey) {
        lilu.onKextLoadForce(&AirportMtkBtPatcher_IOBluetoothInfo, 1,
        [](void *user, KernelPatcher &patcher, size_t index, mach_vm_address_t address, size_t size) {
            callbackMtkBtPatcher->processKext(patcher, index, address, size);
        }, this);
    } else {
        lilu.onPatcherLoadForce([](void *, KernelPatcher &patcher) {
            AirportMtkBlueTool::route(patcher);
        }, this);
    }
    return true;
}

void CAirportMtkBtPatcher::free()
{
    DBGLOG(DRV_NAME, "%s", __PRETTY_FUNCTION__);
}

void CAirportMtkBtPatcher::processKext(KernelPatcher &patcher, size_t index, mach_vm_address_t address, size_t size)
{
    DBGLOG(DRV_NAME, "%s", __PRETTY_FUNCTION__);
    if (getKernelVersion() < KernelVersion::Monterey) {
        if (AirportMtkBtPatcher_IOBluetoothInfo.loadIndex == index) {
            DBGLOG(DRV_NAME, "%s", AirportMtkBtPatcher_IOBluetoothInfo.id);
            
            KernelPatcher::RouteRequest findQueueRequestRequest {
                "__ZN25IOBluetoothHostController17FindQueuedRequestEtP22BluetoothDeviceAddresstbPP21IOBluetoothHCIRequest",
                newFindQueueRequest,
                oldFindQueueRequest
            };
            patcher.routeMultiple(index, &findQueueRequestRequest, 1, address, size);
            if (patcher.getError() == KernelPatcher::Error::NoError) {
                DBGLOG(DRV_NAME, "routed %s", findQueueRequestRequest.symbol);
            } else {
                SYSLOG(DRV_NAME, "failed to resolve %s, error = %d", findQueueRequestRequest.symbol, patcher.getError());
                patcher.clearError();
            }
            
        }
    }
}

#pragma mark - For Bigsur-, patch unhandled 0x2019 opcode

#define HCI_OP_LE_START_ENCRYPTION 0x2019

IOReturn CAirportMtkBtPatcher::newFindQueueRequest(void *that, unsigned short arg1, void *addr, unsigned short arg2, bool arg3, void **hciRequestPtr)
{
    IOReturn ret = FunctionCast(newFindQueueRequest, callbackMtkBtPatcher->oldFindQueueRequest)(that, arg1, addr, arg2, arg3, hciRequestPtr);
    if (ret != 0 && arg1 == HCI_OP_LE_START_ENCRYPTION) {
        ret = FunctionCast(newFindQueueRequest, callbackMtkBtPatcher->oldFindQueueRequest)(that, arg1, addr, 0xffff, arg3, hciRequestPtr);
        DBGLOG(DRV_NAME, "%s ret: %d arg1: 0x%04x arg2: 0x%04x arg3: %d ptr: %p", __FUNCTION__, ret, arg1, arg2, arg3, *hciRequestPtr);
    }
    return ret;
}
