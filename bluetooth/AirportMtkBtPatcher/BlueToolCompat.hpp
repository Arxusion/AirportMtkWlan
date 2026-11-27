// BlueTool/third-party controller compatibility adapted from:
// acidanthera/BrcmPatchRAM, 65389020769837e92e9fb939bac34bd9a3e25bb2,
// BrcmPatchRAM/BlueToolFixup.cpp (created by Dhinak G, 2021).
// SPDX-License-Identifier: GPL-2.0-only
#pragma once

#include <Headers/kern_user.hpp>

namespace AirportMtkBlueTool {
static mach_vm_address_t originalValidatePage;

template <size_t N, size_t M>
static void patch(const void *page, const uint8_t (&find)[N], const uint8_t (&replace)[M])
{
    KernelPatcher::findAndReplace(const_cast<void *>(page), PAGE_SIZE,
                                 find, N, replace, M);
}

static void validatePage(vnode_t vnode, memory_object_t pager,
                         memory_object_offset_t offset, const void *data,
                         int *validated, int *tainted, int *nx)
{
    FunctionCast(validatePage, originalValidatePage)(vnode, pager, offset, data,
                                                    validated, tainted, nx);
    char path[PATH_MAX];
    int length = sizeof(path);
    if (vn_getpath(vnode, path, &length) != 0)
        return;

    if (strcmp(path, "/usr/sbin/BlueTool") == 0) {
        // Firmware is supplied by AirportMtkBtFw. BlueTool must skip Apple's
        // DFU/serial-flash updater and proceed to the normal HCI transport.
        static const uint8_t find[] = "/etc/bluetool/SkipBluetoothAutomaticFirmwareUpdate";
        static const uint8_t replace[] = "/System/Library/CoreServices/boot.efi";
        patch(data, find, replace);
    } else if (strcmp(path, "/usr/sbin/bluetoothd") == 0) {
        // Admit USB controllers outside Apple's Broadcom chipset table.
        static const uint8_t vendor[] = {0x81, 0xFA, 0x5C, 0x0A, 0x00, 0x00, 0x74};
        static const uint8_t vendorPatch[] = {0x81, 0xFA, 0x5C, 0x0A, 0x00, 0x00, 0xEB};
        static const uint8_t chipset[] = {0x81, 0xF9, 0xCF, 0x07, 0x00, 0x00, 0x72};
        static const uint8_t chipsetPatch[] = {0x81, 0xF9, 0xCF, 0x07, 0x00, 0x00, 0xEB};
        static const uint8_t chipset13[] = {0x81, 0xF9, 0x9E, 0x0F, 0x00, 0x00, 0x77, 0x1A};
        static const uint8_t chipset15[] = {0x81, 0xF9, 0x6F, 0x17, 0x00, 0x00, 0x77, 0x30};
        static const uint8_t nops[] = {0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90};
        patch(data, vendor, vendorPatch);
        patch(data, chipset, chipsetPatch);
        if (getKernelVersion() >= KernelVersion::Sequoia)
            patch(data, chipset15, nops);
        else if (getKernelVersion() >= KernelVersion::Ventura)
            patch(data, chipset13, nops);
    }
}

static void route(KernelPatcher &patcher)
{
    KernelPatcher::RouteRequest request {"_cs_validate_page", validatePage, originalValidatePage};
    if (!patcher.routeMultipleLong(KernelPatcher::KernelID, &request, 1)) {
        SYSLOG(DRV_NAME, "failed to route BlueTool compatibility: %d", patcher.getError());
        patcher.clearError();
    }
}
}
