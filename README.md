<!--
  README.md
  SimpleMtkWlan

  Created by laobamac (王孝慈) on 2026/5/5.
  Copyright © 2026 laobamac (王孝慈). All rights reserved.
-->

# SimpleMtkWlan

[![Build](https://github.com/flxxxxddd/SimpleMtkWlan/actions/workflows/build.yml/badge.svg)](https://github.com/flxxxxddd/SimpleMtkWlan/actions/workflows/build.yml)
[![Release](https://img.shields.io/github/v/release/flxxxxddd/SimpleMtkWlan)](https://github.com/flxxxxddd/SimpleMtkWlan/releases)
[![License: GPL v2](https://img.shields.io/badge/license-GPLv2-blue.svg)](LICENSE)

**Wi-Fi for MediaTek MT7921 / MT7921K (AMD RZ608) / MT7922 PCIe cards on macOS.**

An experimental macOS kernel extension, based on the OpenBSD `mwx(4)` driver and
the itlwm-style `net80211` port. It exposes the card as an Ethernet interface
(`enX`); networks are scanned and joined with the
[SimpleMTK](https://github.com/laobamac/SimpleMTKClient) menu-bar client.

> This fork contains the fixes needed to make **MT7921 / RZ608** actually work
> (it was attaching but never passing traffic), plus 802.11n. See
> [What changed in this fork](#what-changed-in-this-fork).

## Status

| Feature | State |
|---|---|
| Probe, firmware load, MSI interrupts | ✅ |
| Scan (2.4 GHz + 5 GHz) | ✅ |
| WPA2-PSK (CCMP) association, 4-way handshake | ✅ |
| Hardware RX decryption (software fallback for anything the chip misses) | ✅ |
| Switching between networks / bands | ✅ |
| 802.11n (HT20, MCS 0–15, SGI20, WMM) | ✅ |
| A-MPDU: RX Block Ack + TX aggregation | ✅ |
| Auto-recovery of a wedged chip (DMA stall watchdog, PCIe FLR at attach) | ✅ |
| 802.11n HT40 | ❌ not yet |
| 802.11ac (VHT) / 802.11ax (HE) | ❌ not yet |
| Native macOS Wi-Fi menu (IO80211Family) | ❌ use SimpleMTK |
| Sleep / wake | ⚠️ untested |
| AirDrop / Handoff / Continuity | ❌ not possible with this design |

### Tested hardware

| Card | PCI ID | macOS | Result |
|---|---|---|---|
| MediaTek MT7921K (AMD RZ608) | `14c3:0608` | 15.8.1 Sequoia, Intel desktop | 22 Mbit/s down / 4 Mbit/s up on 5 GHz HT20 with a weak signal; 2.4 GHz works |
| MediaTek MT7922 | `14c3:7922` | Tahoe (upstream PR #5) | legacy 20 MHz on 5 GHz |
| MediaTek MT7921 | `14c3:7961` | — | same chip family as RZ608, expected to work |

Other MediaTek devices are not supported.

## Installation

1. Download the latest `SimpleMtkWlan-x.y.z-RELEASE.zip` from
   [Releases](https://github.com/flxxxxddd/SimpleMtkWlan/releases) (or build it yourself, see below).
2. Copy `SimpleMtkWlan.kext` to `EFI/OC/Kexts/`.
3. Add it to `config.plist → Kernel → Add`:

   ```xml
   <dict>
       <key>Arch</key>           <string>x86_64</string>
       <key>BundlePath</key>     <string>SimpleMtkWlan.kext</string>
       <key>Comment</key>        <string>MediaTek Wi-Fi</string>
       <key>Enabled</key>        <true/>
       <key>ExecutablePath</key> <string>Contents/MacOS/SimpleMtkWlan</string>
       <key>MaxKernel</key>      <string></string>
       <key>MinKernel</key>      <string></string>
       <key>PlistPath</key>      <string>Contents/Info.plist</string>
   </dict>
   ```

4. **Make sure the card is not hidden.** Many prebuilt EFIs ship an SSDT
   (e.g. `SSDT-Disable_Network_*.aml`) that replaces the card's `vendor-id` /
   `device-id` with `0xFFFF` so macOS ignores it. Disable it, otherwise the
   driver never matches. `ioreg -l | grep -A40 'pci14c3'` should show
   `vendor-id = <c3140000>`.
5. Install [SimpleMTK](https://github.com/laobamac/SimpleMTKClient), reboot and
   join a network from the menu bar.

Optional boot-args: `-novht`, `-noht40`.

## Troubleshooting

* **Read the driver log.** The driver keeps a persistent ring buffer that
  survives a failed start and is readable without root:

  ```sh
  ./tools/mtklog.sh > mtk.txt
  ```

  A periodic `stats` line shows RX counters, hardware vs software decryption
  (`rx_hwdec` / `rx_swdec`) and the reasons frames are dropped.
* **"SimpleMtkWlan is not running" after a reboot.** A warm reboot does not
  power-cycle an M.2 card. The driver now recovers the chip automatically
  (WFSYS reset, then PCIe function-level reset); if it still fails, shut the
  machine down completely and power it on again.
* **Slow speed.** Check `rx_swdec` in the stats line: it should stay small
  compared to `rx_hwdec`. Speed tests are only meaningful with the SimpleMTK
  menu closed (the client triggers scans; they are throttled to one per two
  minutes while connected).
* Unrelated kernel panics (`element modified after free` at ~2 s of uptime)
  were caused by `NVMeFix.kext` on the test machine, not by this driver.

## Building

Requirements: macOS with Xcode (command line tools are not enough). The kernel
headers come from [acidanthera/MacKernelSDK](https://github.com/acidanthera/MacKernelSDK),
which is a git submodule.

```sh
git clone --recurse-submodules https://github.com/flxxxxddd/SimpleMtkWlan.git
cd SimpleMtkWlan
xcodebuild -project SimpleMtkWlan.xcodeproj -scheme SimpleMtkWlan \
  -configuration Release -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
# -> build/Build/Products/Release/SimpleMtkWlan.kext
```

Already cloned without submodules? `git submodule update --init`.

> **Do a clean build (`rm -rf build`) after editing headers in `mtk80211/` or
> `include/`.** They are on the system header search path, which Xcode does
> not track for dependencies, so stale objects would otherwise be linked.

Host tests (extract real driver functions and run them against stubs with
ASan/UBSan):

```sh
./tests/run-all.sh
```

CI builds Debug and Release on every push and pull request; pushing a tag
`vX.Y.Z` publishes a GitHub release with the zipped kexts.

## Repository layout

| Path | Contents |
|---|---|
| `SimpleMtkWlan/SimpleMtkWlan.cpp` | IOEthernetController front end, persistent debug log, watchdog |
| `SimpleMtkWlan/MtkWlanUserClient.cpp` | IOUserClient used by the SimpleMTK app |
| `SimpleMtkWlan/hal_mwx/` | MT7921/MT7922 hardware layer (port of OpenBSD `mwx`) |
| `mtk80211/` | `net80211` and BSD/Linux compatibility layer |
| `include/` | HAL interfaces, embedded firmware (`FwBinary.cpp`), client API |
| `tests/` | host tests |
| `tools/mtklog.sh` | dumps the driver log |
| `MacKernelSDK/` | submodule with kernel headers |

## What changed in this fork

On top of upstream and [PR #5](https://github.com/laobamac/SimpleMtkWlan/pull/5)
(association context, TX serialization, packet ownership):

* **Firmware load:** firmware chunks no longer need 16 KB jumbo mbuf clusters
  (they were unavailable at boot → `ENOMEM`, no MAC address, no interface).
* **Interrupts:** register the real MSI vector instead of INTx and stop setting
  the MSI enable bit by hand (the device stopped raising INTx and only got
  serviced through a shared line); drain pending status before re-enabling.
* **TX DMA stall:** multi-mbuf frames are linearized into one cluster; the
  WFDMA stalled forever on the first DHCP frame.
* **Group traffic:** the chip does not decrypt group-addressed frames, so
  broadcast ARP/DHCP was dropped. Keys are now also set up for `net80211`
  software CCMP as a fallback.
* **Network switching:** send the deauth to the old AP on its channel before
  switching, ignore stale disassoc frames while authenticating, and remove the
  peer station / disable the BSS in firmware when leaving (otherwise hardware
  decryption stopped after the first switch).
* **Roaming:** RSSI-triggered background roaming is disabled (it hopped between
  2.4 and 5 GHz networks of the same router every few seconds).
* **Throughput:** background scans while associated are throttled.
* **802.11n:** HT capabilities, WMM, full peer STA record on association, RX
  Block Ack and TX A-MPDU sessions passed to the firmware.
* **Robustness:** DMA stall watchdog with hard reset + firmware reload, chip
  recovery at attach (WFSYS reset → PCIe FLR), TXWI leak fix.
* **Debuggability:** persistent `MtkDebugLog` ring buffer published on the PCI
  device, periodic hardware/stats dump, quiet logging on the data path.
* **Build:** builds from a clean clone (MacKernelSDK submodule, no absolute
  paths), host tests fixed, CI + releases.

## License

GPLv2, see [LICENSE](LICENSE). Some files carry additional or more specific
notices inherited from upstream GPL/BSD/OpenBSD/NetBSD/FreeBSD components;
those apply to their respective files. Firmware is redistributed under the
MediaTek firmware license (as in linux-firmware).

## Credits

* [laobamac (王孝慈)](https://github.com/laobamac) — SimpleMtkWlan and SimpleMTK
* [mavizao](https://github.com/mavizao) — PR #5 (MT7922 association/TX fixes, host tests)
* OpenBSD `mwx(4)` driver authors
* [OpenIntelWireless/itlwm](https://github.com/OpenIntelWireless/itlwm) (zxystd) — net80211 port and driver architecture
* Linux [mt76](https://github.com/openwrt/mt76) — hardware reference
* [acidanthera](https://github.com/acidanthera) — MacKernelSDK

See also [CREDITS.md](CREDITS.md).
