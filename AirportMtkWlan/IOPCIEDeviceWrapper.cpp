//
//  IOPCIEDeviceWrapper.cpp
//  AirportItlwm-Sonoma
//
//  Created by qcwap on 2023/6/27.
//  Copyright © 2023 钟先耀. All rights reserved.
//

#include "IOPCIEDeviceWrapper.hpp"
#include "MtkLog.hpp"
#include "Apple80211.h"

#include "MtkMwx.hpp"

#define super IOService
OSDefineMetaClassAndStructors(IOPCIEDeviceWrapper, IOService);

#define  PCI_MSI_FLAGS        2    /* Message Control */
#define  PCI_CAP_ID_MSI        0x05    /* Message Signalled Interrupts */
#define  PCI_MSIX_FLAGS        2    /* Message Control */
#define  PCI_CAP_ID_MSIX    0x11    /* MSI-X */
#define  PCI_MSIX_FLAGS_ENABLE    0x8000    /* MSI-X enable */
#define  PCI_MSI_FLAGS_ENABLE    0x0001    /* MSI feature enabled */

static IOPMPowerState powerStateArray[2] =
{
    {1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
    {1, kIOPMDeviceUsable, kIOPMPowerOn, kIOPMPowerOn, 0, 0, 0, 0, 0, 0, 0, 0}
};

static void pciMsiXClearAndSet(IOPCIDevice *device, UInt8 msixCap, UInt16 clear, UInt16 set)
{
    UInt16 ctrl;
    
    ctrl = device->configRead16(msixCap + PCI_MSIX_FLAGS);
    ctrl &= ~clear;
    ctrl |= set;
    device->configWrite16(msixCap + PCI_MSIX_FLAGS, ctrl);
}

extern IOWorkLoop *_fWorkloop;

IOWorkLoop *IOPCIEDeviceWrapper::getWorkLoop() const
{
    return _fWorkloop;
}

IOService* IOPCIEDeviceWrapper::
probe(IOService *provider, SInt32 *score)
{
    mtk_dbg_set_nub(provider);
    XYLog("%s\n", __PRETTY_FUNCTION__);
    bool isMatch = false;
    super::probe(provider, score);
    UInt8 msiCap;
    UInt8 msixCap;
    IOPCIDevice* device = OSDynamicCast(IOPCIDevice, provider);
    if (!device)
        return NULL;
    if (MtkMwx::mwx_match(device)) {
        isMatch = true;
        fHalService = new MtkMwx;
    }
    if (isMatch) {
        XYLog("%s Found\n", __FUNCTION__);
        device->findPCICapability(PCI_CAP_ID_MSIX, &msixCap);
        if (msixCap)
            pciMsiXClearAndSet(device, msixCap, PCI_MSIX_FLAGS_ENABLE, 0);
        device->findPCICapability(PCI_CAP_ID_MSI, &msiCap);
        /*
         * Do not set the MSI enable bit by hand: nothing has programmed the
         * MSI address/data yet, and with MSI enabled the device stops raising
         * INTx. IOPCIFamily enables MSI when the PCIMessaged vector is
         * registered (see pci_intr_establish).
         */
        if (!msiCap && !msixCap) {
            XYLog("%s No MSI cap\n", __FUNCTION__);
            fHalService->release();
            fHalService = NULL;
            return NULL;
        }
        this->pciNub = device;
        return this;
    }
    return NULL;
}

bool IOPCIEDeviceWrapper::
start(IOService *provider)
{
    XYLog("%s\n", __PRETTY_FUNCTION__);
    _fWorkloop = IO80211WorkQueue::workQueue();
    if (!super::start(provider)) {
        return false;
    }
    IOLog("%s::super start succeed\n", getName());
    UInt8 builtIn = 0;
    setProperty("built-in", OSData::withBytes(&builtIn, sizeof(builtIn)));
    PMinit();
    registerPowerDriver(this, powerStateArray, 2);
    provider->joinPMtree(this);
    logTimer = IOTimerEventSource::timerEventSource(this, &IOPCIEDeviceWrapper::logTimerFired);
    if (logTimer && _fWorkloop->addEventSource(logTimer) == kIOReturnSuccess)
        logTimer->setTimeoutMS(500);
    else
        OSSafeReleaseNULL(logTimer);
    registerService();
    return true;
}

void IOPCIEDeviceWrapper::
publishLog()
{
    mtk_dbg_publish();
}

void IOPCIEDeviceWrapper::
logTimerFired(OSObject *owner, IOTimerEventSource *sender)
{
    IOPCIEDeviceWrapper *self = OSDynamicCast(IOPCIEDeviceWrapper, owner);
    if (!self)
        return;
    self->publishLog();
    sender->setTimeoutMS(2000);
}

void IOPCIEDeviceWrapper::
stop(IOService *provider)
{
    XYLog("%s\n", __PRETTY_FUNCTION__);
    if (logTimer) {
        logTimer->cancelTimeout();
        _fWorkloop->removeEventSource(logTimer);
        OSSafeReleaseNULL(logTimer);
    }
    PMstop();
    super::stop(provider);
}

IOReturn IOPCIEDeviceWrapper::
setPowerState(unsigned long powerStateOrdinal, IOService *whatDevice)
{
    return IOPMAckImplied;
}
