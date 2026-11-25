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
#include <sys/vnode.h>
#include <mach/vm_param.h>

#include "AirportMtkBtPatcher.hpp"

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

static const char *AirportMtkBtPatcher_IOUSBHostFamily[] {
    "/System/Library/Extensions/IOUSBHostFamily.kext/Contents/MacOS/IOUSBHostFamily" };

static KernelPatcher::KextInfo AirportMtkBtPatcher_IOUsbHostInfo {
    "com.apple.iokit.IOUSBHostFamily",
    AirportMtkBtPatcher_IOUSBHostFamily,
    1,
    {true, true},
    {},
    KernelPatcher::KextInfo::Unloaded
};

static IONotifier *gUsbIfNotifier = nullptr;

struct MtkUsbId {
    uint16_t vid;
    uint16_t pid;
};

// Known MT7922 USB VID:PIDs that are NOT in Apple's native BAM MT7922 table
// (0489:e0d8/e0e0/e0f1/e0f2/e0f6, 0e8d:7922, 13d3:3568).
static constexpr MtkUsbId kNonBamMt7922Ids[] = {
    { 0x13D3, 0x3584 }, { 0x13D3, 0x3585 }, { 0x13D3, 0x3605 },
    { 0x13D3, 0x3607 }, { 0x13D3, 0x3610 }, { 0x13D3, 0x3614 },
    { 0x13D3, 0x3615 }, { 0x13D3, 0x3633 },
    { 0x0489, 0xE0D9 }, { 0x0489, 0xE0E2 }, { 0x0489, 0xE0E4 },
    { 0x0489, 0xE0F5 }, { 0x0489, 0xE102 }, { 0x0489, 0xE11D },
    { 0x0489, 0xE152 }, { 0x0489, 0xE153 }, { 0x0489, 0xE170 },
    { 0x0489, 0xE174 },
    { 0x04CA, 0x3804 }, { 0x04CA, 0x3807 }, { 0x04CA, 0x38E4 },
    { 0x35F5, 0x7922 },
};

static bool isNonBamMt7922(uint32_t vid, uint32_t pid)
{
    for (size_t i = 0; i < arrsize(kNonBamMt7922Ids); ++i) {
        if (kNonBamMt7922Ids[i].vid == vid && kNonBamMt7922Ids[i].pid == pid)
            return true;
    }
    return false;
}

// Remap non-listed MT7922 USB VID:PIDs (e.g. AzureWave 0x13D3:0x3585) in IORegistry
// to Apple's native BAM-listed MT7922 ID (0x13D3:0x3568) AFTER SimpleMtkBtFw/AirportMtkBtFw
// has matched and configured the device. This lets bluetoothd classify the chip
// as native SRS_7922 (controllerID = 0xFA0 > 3) instead of THIRD_PARTY_DONGLE (0),
// keeping gUseAdvSetRandomAddr = 1 so bluetoothd natively sends HCI 0x2035 with
// real CA/NC random MAC addresses matching AirDrop TempAuthTag.
static bool onUsbInterfacePublished(void *target, void *refCon, IOService *newService, IONotifier *notifier)
{
    if (!newService)
        return true;
    IOService *dev = newService->getProvider();
    if (!dev)
        return true;

    auto *vidObj = OSDynamicCast(OSNumber, dev->getProperty("idVendor"));
    auto *pidObj = OSDynamicCast(OSNumber, dev->getProperty("idProduct"));
    if (!vidObj || !pidObj)
        return true;

    uint32_t vid = vidObj->unsigned32BitValue();
    uint32_t pid = pidObj->unsigned32BitValue();
    if (isNonBamMt7922(vid, pid)) {
        if (vid != 0x13D3)
            dev->setProperty("idVendor", static_cast<uint64_t>(0x13D3), 32);
        dev->setProperty("idProduct", static_cast<uint64_t>(0x3568), 32);
        SYSLOG(DRV_NAME, "[BAM] Remapped IORegistry 0x%04x:0x%04x -> 0x13d3:0x3568 on %s",
               vid, pid, dev->getName());
    }
    return true;
}

static void patchedCsValidatePage(vnode_t vp, memory_object_t pager, memory_object_offset_t pageOffset,
                                  const void *data, int *validatedP, int *taintedP, int *nxP)
{
    FunctionCast(patchedCsValidatePage, callbackMtkBtPatcher->oldCsValidatePage)(
        vp, pager, pageOffset, data, validatedP, taintedP, nxP);

    if (!vp || !data)
        return;

    char path[PATH_MAX];
    int pathLen = PATH_MAX;
    if (vn_getpath(vp, path, &pathLen) != 0)
        return;
    if (strncmp(path, "/usr/sbin/", 10) != 0)
        return;

    void *page = const_cast<void *>(data);
    if (strcmp(path + 10, "BlueTool") == 0) {
        // Skip Broadcom USB DFU serial flash update without needing /etc/bluetool/SkipBluetoothAutomaticFirmwareUpdate
        static constexpr char kSkipFind[51] = "/etc/bluetool/SkipBluetoothAutomaticFirmwareUpdate";
        static constexpr char kSkipRepl[51] = "/System/Library/CoreServices/boot.efi";
        if (KernelPatcher::findAndReplaceWithMask(page, PAGE_SIZE,
                kSkipFind, sizeof(kSkipFind), nullptr, 0,
                kSkipRepl, sizeof(kSkipRepl), nullptr, 0)) {
            SYSLOG(DRV_NAME, "[CS] Patched BlueTool SkipBluetoothAutomaticFirmwareUpdate");
        }
    } else if (strcmp(path + 10, "bluetoothd") == 0) {
        // 1. Disable Extended Scanning (stock MT7922 returns 0 scan reports with extended scan enabled)
        //    48 8b 08 48 89 c7 ff 91 a8 09 00 00 41 89 c6 88 05
        //    Replace callq *0x9a8(%rcx) -> xorl %eax, %eax; nop*4
        static constexpr uint8_t kExtScanFind[] = {
            0x48, 0x8b, 0x08, 0x48, 0x89, 0xc7,
            0xff, 0x91, 0xa8, 0x09, 0x00, 0x00,
            0x41, 0x89, 0xc6, 0x88, 0x05
        };
        static constexpr uint8_t kScanCallZeroRepl[] = {
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x31, 0xc0, 0x90, 0x90, 0x90, 0x90,
            0x00, 0x00, 0x00, 0x00, 0x00
        };
        static constexpr uint8_t kScanCallZeroMask[] = {
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
            0x00, 0x00, 0x00, 0x00, 0x00
        };
        if (KernelPatcher::findAndReplaceWithMask(page, PAGE_SIZE,
                kExtScanFind, sizeof(kExtScanFind), nullptr, 0,
                kScanCallZeroRepl, sizeof(kScanCallZeroRepl), kScanCallZeroMask, sizeof(kScanCallZeroMask))) {
            SYSLOG(DRV_NAME, "[CS] Patched bluetoothd DisableExtScans");
        }

        // 2. Disable Scan Enhancements VSC (stock MT7922 returns STATUS 3601 on Apple SRS Scan Enhancement VSC)
        //    48 8b 08 48 89 c7 ff 91 d8 09 00 00 41 89 c6 88 05
        //    Replace callq *0x9d8(%rcx) -> xorl %eax, %eax; nop*4
        static constexpr uint8_t kScanEnhFind[] = {
            0x48, 0x8b, 0x08, 0x48, 0x89, 0xc7,
            0xff, 0x91, 0xd8, 0x09, 0x00, 0x00,
            0x41, 0x89, 0xc6, 0x88, 0x05
        };
        if (KernelPatcher::findAndReplaceWithMask(page, PAGE_SIZE,
                kScanEnhFind, sizeof(kScanEnhFind), nullptr, 0,
                kScanCallZeroRepl, sizeof(kScanCallZeroRepl), kScanCallZeroMask, sizeof(kScanCallZeroMask))) {
            SYSLOG(DRV_NAME, "[CS] Patched bluetoothd DisableScanEnhancements");
        }

        // 3. Allow MtkLoadRomPatch to return 0 instead of 0x72 when /etc/bluetool/BT_RAM_CODE_MT7922*
        //    is not present on disk (firmware is already loaded by SimpleMtkBtFw/AirportMtkBtFw).
        //    31 c0 e8 ?? ?? ?? ?? bb 72 00 00 00 48 8b 05
        static constexpr uint8_t kMtkRomFind[] = {
            0x31, 0xc0, 0xe8, 0x00, 0x00, 0x00, 0x00,
            0xbb, 0x72, 0x00, 0x00, 0x00,
            0x48, 0x8b, 0x05
        };
        static constexpr uint8_t kMtkRomFindMask[] = {
            0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0x00,
            0xff, 0xff, 0xff, 0xff, 0xff,
            0xff, 0xff, 0xff
        };
        static constexpr uint8_t kMtkRomRepl[] = {
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x31, 0xdb, 0x90, 0x90, 0x90,
            0x00, 0x00, 0x00
        };
        static constexpr uint8_t kMtkRomReplMask[] = {
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0xff, 0xff, 0xff, 0xff, 0xff,
            0x00, 0x00, 0x00
        };
        if (KernelPatcher::findAndReplaceWithMask(page, PAGE_SIZE,
                kMtkRomFind, sizeof(kMtkRomFind), kMtkRomFindMask, sizeof(kMtkRomFindMask),
                kMtkRomRepl, sizeof(kMtkRomRepl), kMtkRomReplMask, sizeof(kMtkRomReplMask))) {
            SYSLOG(DRV_NAME, "[CS] Patched bluetoothd MtkLoadRomPatch fallback");
        }
    }
}

bool CAirportMtkBtPatcher::_randomAddressInit = false;

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
        lilu.onPatcherLoadForce([](void *user, KernelPatcher &patcher) {
            callbackMtkBtPatcher->processKernel(patcher);
        }, this);
        lilu.onKextLoadForce(&AirportMtkBtPatcher_IOUsbHostInfo, 1,
        [](void *user, KernelPatcher &patcher, size_t index, mach_vm_address_t address, size_t size) {
            callbackMtkBtPatcher->processKext(patcher, index, address, size);
        }, this);
    }
    return true;
}

void CAirportMtkBtPatcher::free()
{
    DBGLOG(DRV_NAME, "%s", __PRETTY_FUNCTION__);
}

void CAirportMtkBtPatcher::processKernel(KernelPatcher &patcher)
{
    KernelPatcher::RouteRequest request("_cs_validate_page", patchedCsValidatePage, oldCsValidatePage);
    if (!patcher.routeMultipleLong(KernelPatcher::KernelID, &request, 1)) {
        SYSLOG(DRV_NAME, "failed to route _cs_validate_page, error = %d", patcher.getError());
        patcher.clearError();
    } else {
        DBGLOG(DRV_NAME, "routed _cs_validate_page");
    }
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
    } else {
        if (AirportMtkBtPatcher_IOUsbHostInfo.loadIndex == index) {
            SYSLOG(DRV_NAME, "%s", AirportMtkBtPatcher_IOUsbHostInfo.id);
            
            KernelPatcher::RouteRequest hostDeviceRequest {
            "__ZN15IOUSBHostDevice13deviceRequestEP9IOServiceRN11StandardUSB13DeviceRequestEPvP18IOMemoryDescriptorRjP19IOUSBHostCompletionj",
                newHostDeviceRequest,
                oldHostDeviceRequest
            };
            patcher.routeMultiple(index, &hostDeviceRequest, 1, address, size);
            if (patcher.getError() == KernelPatcher::Error::NoError) {
                SYSLOG(DRV_NAME, "routed %s", hostDeviceRequest.symbol);
            } else {
                SYSLOG(DRV_NAME, "failed to resolve %s, error = %d", hostDeviceRequest.symbol, patcher.getError());
                patcher.clearError();
            }

            if (gUsbIfNotifier == nullptr) {
                OSDictionary *matching = IOService::serviceMatching("IOUSBHostInterface");
                if (matching) {
                    gUsbIfNotifier = IOService::addMatchingNotification(
                        gIOPublishNotification, matching, onUsbInterfacePublished, this, nullptr, 0);
                    matching->release();
                    SYSLOG(DRV_NAME, "[BAM] Registered IOUSBHostInterface publish notifier=%p", gUsbIfNotifier);
                }
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

#pragma mark - For Monterey+ patch for intercept HCI REQ and RESP

StandardUSB::DeviceRequest randomAddressRequest;
// Hardcoded Random Address HCI Command
const uint8_t randomAddressHci[9] = {0x05, 0x20, 0x06, 0x94, 0x50, 0x64, 0xD0, 0x78, 0x6B}; 
IOBufferMemoryDescriptor *writeHCIDescriptor = nullptr;

#define MAX_HCI_BUF_LEN                 255
#define HCI_OP_RESET                    0x0c03
#define HCI_OP_LE_SET_RANDOM_ADDR       0x2005
#define HCI_OP_LE_SET_SCAN_PARAM        0x200B
#define HCI_OP_LE_SET_SCAN_ENABLE       0x200C
#define HCI_OP_LE_SET_ADV_SET_RAND_ADDR 0x2035
#define HCI_OP_LE_SET_EXT_ADV_PARAMS    0x2036
#define HCI_OP_LE_SET_EXT_ADV_DATA      0x2037
#define HCI_OP_LE_SET_EXT_SCAN_RSP_DATA 0x2038
#define HCI_OP_LE_SET_EXT_ADV_ENABLE    0x2039
#define HCI_OP_LE_READ_MAX_ADV_DATA_LEN 0x203A
#define HCI_OP_LE_READ_NUM_ADV_SETS     0x203B
#define HCI_OP_LE_REMOVE_ADV_SET        0x203C
#define HCI_OP_LE_CLEAR_ADV_SETS        0x203D
#define HCI_OP_LE_SET_EXT_SCAN_PARAMS   0x2041
#define HCI_OP_LE_SET_EXT_SCAN_ENABLE   0x2042

struct MtkAdvHandleState {
    uint8_t ownAddrType;
    bool paramsSet;
    bool addrSent;
    bool hasLastAddr;
    uint8_t lastAddr[6];
};

static MtkAdvHandleState gAdvHandles[8] = {};
static uint32_t gExtAdvLogCount = 0;

static bool isTrackedExtAdvOpcode(uint16_t opcode)
{
    return opcode == HCI_OP_RESET ||
           opcode == HCI_OP_LE_SET_RANDOM_ADDR ||
           opcode == HCI_OP_LE_SET_SCAN_PARAM ||
           (opcode >= HCI_OP_LE_SET_ADV_SET_RAND_ADDR && opcode <= HCI_OP_LE_CLEAR_ADV_SETS) ||
           opcode == HCI_OP_LE_SET_EXT_SCAN_PARAMS ||
           opcode == HCI_OP_LE_SET_EXT_SCAN_ENABLE;
}

IOReturn CAirportMtkBtPatcher::newHostDeviceRequest(void *that, IOService *provider, StandardUSB::DeviceRequest &request, void *data, IOMemoryDescriptor *descriptor, unsigned int &length, IOUSBHostCompletion *completion, unsigned int timeout)
{
    HciCommandHdr *hdr = nullptr;
    uint32_t hdrLen = 0;
    char hciBuf[MAX_HCI_BUF_LEN] = {0};
    bool didPrepare = false;

    const bool isOutClassReq = (request.bmRequestType & 0xE0) == 0x20;
    if (isOutClassReq) {
        if (data == nullptr) {
            if (descriptor != nullptr) {
                // Newer kernels require DMA preparation before reading the descriptor.
                bool needsPrepare = getKernelVersion() >= KernelVersion::Sequoia;
                IOReturn status = needsPrepare
                    ? descriptor->prepare(kIODirectionOut)
                    : kIOReturnSuccess;

                if (status == kIOReturnSuccess) {
                    if (needsPrepare)
                        didPrepare = true;
                    IOByteCount descLen = descriptor->getLength();
                    if (descLen > 0) {
                        hdrLen = (uint32_t)descriptor->readBytes(
                            0, hciBuf, min(descLen, (IOByteCount)MAX_HCI_BUF_LEN));
                    }
                }
            }
            if (hdrLen >= 3)
                hdr = (HciCommandHdr *)hciBuf;
        } else if (request.wLength >= 3) {
            hdr = (HciCommandHdr *)data;
            hdrLen = min((uint32_t)request.wLength, (uint32_t)MAX_HCI_BUF_LEN);
        }
    }

    if (hdr && hdrLen >= 3) {
        if (isTrackedExtAdvOpcode(hdr->opcode) && gExtAdvLogCount < 80) {
            ++gExtAdvLogCount;
            if (ADDPR(debugEnabled)) {
                size_t dumpLen = min((size_t)hdrLen, (size_t)40);
                const char *dump = _hexDumpHCIData((uint8_t *)hdr, dumpLen);
                if (dump) {
                    DBGLOG(DRV_NAME, "[HCI #%u] bmReq=0x%02x bReq=0x%02x op=0x%04x len=%u total=%u data=%s",
                           gExtAdvLogCount, request.bmRequestType, request.bRequest,
                           hdr->opcode, hdr->len, hdrLen, dump);
                    IOFree((void *)dump, dumpLen * 3 + 1);
                }
            }
        }

        if (hdr->opcode == HCI_OP_RESET) {
            _randomAddressInit = false;
            gExtAdvLogCount = 0;
            for (int i = 0; i < 8; ++i) {
                gAdvHandles[i].paramsSet = false;
                gAdvHandles[i].addrSent = false;
            }
        } else if (hdr->opcode == HCI_OP_LE_SET_RANDOM_ADDR) {
            // Host already programmed a real random address (CA); never overwrite it
            // with the fallback dummy address on subsequent 0x200B/0x2041 commands.
            _randomAddressInit = true;
        } else if (hdr->opcode == HCI_OP_LE_CLEAR_ADV_SETS) {
            for (int i = 0; i < 8; ++i) {
                gAdvHandles[i].paramsSet = false;
                gAdvHandles[i].addrSent = false;
            }
        } else if (hdr->opcode == HCI_OP_LE_REMOVE_ADV_SET && hdr->len >= 1 && hdrLen >= 4) {
            uint8_t handle = hdr->data[0];
            if (handle < 8) {
                gAdvHandles[handle].paramsSet = false;
                gAdvHandles[handle].addrSent = false;
            }
        } else if (hdr->opcode == HCI_OP_LE_SET_ADV_SET_RAND_ADDR && hdr->len == 7 && hdrLen >= 10) {
            uint8_t handle = hdr->data[0];
            if (handle < 8) {
                memcpy(gAdvHandles[handle].lastAddr, &hdr->data[1], 6);
                gAdvHandles[handle].hasLastAddr = true;
                // Stock MT7922 rejects 0x2035 with 0x42 (Unknown Advertising Identifier)
                // if sent before 0x2036 creates the advertising set. Only mark addrSent
                // when paramsSet is already true; otherwise we replay this exact real
                // address right before 0x2039 after 0x2036 has created the handle.
                if (gAdvHandles[handle].paramsSet)
                    gAdvHandles[handle].addrSent = true;
                DBGLOG(DRV_NAME, "[HCI 0x2035] handle=%u paramsSet=%u addr=%02x:%02x:%02x:%02x:%02x:%02x",
                       handle, gAdvHandles[handle].paramsSet ? 1 : 0,
                       hdr->data[6], hdr->data[5], hdr->data[4],
                       hdr->data[3], hdr->data[2], hdr->data[1]);
            }
        } else if (hdr->opcode == HCI_OP_LE_SET_EXT_ADV_PARAMS && hdr->len == 25 && hdrLen >= 28) {
            uint8_t handle = hdr->data[0];
            if (handle < 8) {
                gAdvHandles[handle].ownAddrType = hdr->data[10];
                gAdvHandles[handle].paramsSet = true;
            }
        } else if ((hdr->opcode == HCI_OP_LE_SET_SCAN_PARAM || hdr->opcode == HCI_OP_LE_SET_EXT_SCAN_PARAMS) && !_randomAddressInit) {
            randomAddressRequest.bmRequestType = request.bmRequestType;
            randomAddressRequest.bRequest = request.bRequest;
            randomAddressRequest.wIndex = request.wIndex;
            randomAddressRequest.wValue = request.wValue;
            randomAddressRequest.wLength = 9;
            unsigned int randLen = 9;
            if (writeHCIDescriptor == nullptr)
                writeHCIDescriptor = IOBufferMemoryDescriptor::withBytes(randomAddressHci, 9, kIODirectionOut);
            if (writeHCIDescriptor != nullptr) {
                writeHCIDescriptor->prepare(kIODirectionOut);
                unsigned int randTimeout = timeout > 0 ? min(timeout, 2000U) : 2000U;
                IOReturn ret = FunctionCast(newHostDeviceRequest, callbackMtkBtPatcher->oldHostDeviceRequest)(that, provider, randomAddressRequest, nullptr, writeHCIDescriptor, randLen, nullptr, randTimeout);
                writeHCIDescriptor->complete(kIODirectionOut);
                SYSLOG(DRV_NAME, "[PATCH] Sent 0x2005 before 0x%04x ret=0x%x", hdr->opcode, ret);
                _randomAddressInit = true;
            }
        } else if (hdr->opcode == HCI_OP_LE_SET_EXT_ADV_ENABLE && hdr->len >= 2 && hdrLen >= 5) {
            uint8_t enable = hdr->data[0];
            uint8_t numSets = hdr->data[1];
            if (enable == 1) {
                for (uint8_t i = 0; i < numSets; ++i) {
                    size_t off = 2 + (size_t)i * 4;
                    if (3 + off >= hdrLen)
                        break;
                    uint8_t handle = hdr->data[off];
                    if (handle < 8 &&
                        (gAdvHandles[handle].ownAddrType == 1 || gAdvHandles[handle].ownAddrType == 3) &&
                        !gAdvHandles[handle].addrSent) {
                        uint8_t setAddrCmd[10] = {
                            0x35, 0x20, 0x07, handle,
                            0x6B, 0x78, 0xD0, 0x64, 0x50, (uint8_t)(0xC0 | handle)
                        };
                        if (gAdvHandles[handle].hasLastAddr)
                            memcpy(&setAddrCmd[4], gAdvHandles[handle].lastAddr, 6);
                        StandardUSB::DeviceRequest setAddrReq = request;
                        setAddrReq.wLength = sizeof(setAddrCmd);
                        unsigned int setAddrLen = sizeof(setAddrCmd);
                        auto *desc = IOBufferMemoryDescriptor::withBytes(setAddrCmd, sizeof(setAddrCmd), kIODirectionOut);
                        if (desc) {
                            desc->prepare(kIODirectionOut);
                            unsigned int cmdTimeout = timeout > 0 ? min(timeout, 2000U) : 2000U;
                            IOReturn ret = FunctionCast(newHostDeviceRequest, callbackMtkBtPatcher->oldHostDeviceRequest)(
                                that, provider, setAddrReq, nullptr, desc, setAddrLen, nullptr, cmdTimeout);
                            desc->complete(kIODirectionOut);
                            desc->release();
                            gAdvHandles[handle].addrSent = true;
                            SYSLOG(DRV_NAME, "[PATCH] Replayed 0x2035 handle=%u (cached=%u) addr=%02x:%02x:%02x:%02x:%02x:%02x ret=0x%x",
                                   handle, gAdvHandles[handle].hasLastAddr ? 1 : 0,
                                   setAddrCmd[9], setAddrCmd[8], setAddrCmd[7],
                                   setAddrCmd[6], setAddrCmd[5], setAddrCmd[4], ret);
                        }
                    }
                }
            }
        }
    }
    IOReturn res = FunctionCast(newHostDeviceRequest, callbackMtkBtPatcher->oldHostDeviceRequest)(that, provider, request, data, descriptor, length, completion, timeout);
    if (didPrepare && descriptor != nullptr)
        descriptor->complete(kIODirectionOut);
    return res;
}
