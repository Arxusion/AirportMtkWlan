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
the itlwm-style `net80211` port. It comes in two flavours with the same
hardware layer:

* **`AirportMtkWlan.kext`** — the card is a real macOS Wi-Fi interface: the
  native Wi-Fi menu, System Settings, private Wi-Fi addresses, Keychain
  passwords. Built for **macOS 26 Tahoe** (and Sequoia 15.2+), no OCLP root
  patch, no IOSkywalkFamily downgrade.
* **`SimpleMtkWlan.kext`** — the card is an Ethernet interface (`enX`);
  networks are scanned and joined with the
  [SimpleMTK](https://github.com/laobamac/SimpleMTKClient) menu-bar client.
  Works on any macOS version the kext loads on.

> **Bluetooth** for the same card: **[SimpleMtkBtFw](https://github.com/flxxxxddd/SimpleMtkBtFw)**
> (firmware loader + patcher; AirPods audio works).

> This fork contains the fixes needed to make **MT7921 / RZ608** actually work
> (it was attaching but never passing traffic), plus 802.11n, 802.11ac
> (VHT80) and the native Wi-Fi menu on Tahoe. See
> [What changed in this fork](#what-changed-in-this-fork).

## Status

| Feature | State |
|---|---|
| Probe, firmware load, MSI interrupts | ✅ |
| Scan (2.4 GHz + 5 GHz) | ✅ |
| WPA2-PSK (CCMP) association, 4-way handshake | ✅ |
| Hardware RX decryption (software fallback for anything the chip misses) | ✅ |
| Switching between networks / bands | ✅ |
| 802.11n (HT20/HT40, MCS 0–15, SGI, RX STBC, WMM) | ✅ |
| 802.11ac (VHT20/40/80, 2×2 MCS 0–9, RX STBC) | ✅ |
| A-MPDU: RX Block Ack + TX aggregation | ✅ |
| Hardware TX A-MSDU (inside A-MPDU), VHT beamformee | ✅ |
| Auto-join at boot, 5 GHz preferred over 2.4 GHz of the same router | ✅ |
| AUTH / ASSOC retransmission (lost frames no longer cost a full rescan) | ✅ |
| Auto-recovery of a wedged chip (DMA stall watchdog, PCIe FLR at attach) | ✅ |
| Native macOS Wi-Fi menu (IO80211Family / Skywalk), Tahoe | ✅ `AirportMtkWlan` |
| Native Wi-Fi menu, Sequoia 15.2+ | ⚠️ builds, not tested on hardware with this HAL |
| 802.11ax (HE) | ❌ not yet |
| WPA3-only (SAE) networks | ❌ |
| Sleep / wake | ⚠️ untested |
| AirDrop / Handoff / Continuity (AWDL) | ❌ |

### Tested hardware

| Card | PCI ID | macOS | Result |
|---|---|---|---|
| MediaTek MT7921K (AMD RZ608) | `14c3:0608` | 26.7.1 Tahoe, Intel desktop | `AirportMtkWlan`: native Wi-Fi menu, joins from Keychain, 50+ Mbit/s on 5 GHz VHT80 (weak signal, 100 Mbit/s line) |
| MediaTek MT7921K (AMD RZ608) | `14c3:0608` | 15.8.1 Sequoia, Intel desktop | `SimpleMtkWlan`: 30–50 Mbit/s on 5 GHz VHT80 (a MacBook in the same spot gets ~85); 2.4 GHz works; joins automatically at boot |
| MediaTek MT7922 (RZ616) | `14c3:0616` | 15.8.1 Sequoia | native Wi-Fi menu in [pengubow's fork](https://github.com/pengubow/SimpleMtkWlan) (its own HAL) |
| MediaTek MT7922 | `14c3:7922` | Tahoe (upstream PR #5) | legacy 20 MHz on 5 GHz |
| MediaTek MT7921 | `14c3:7961` | — | same chip family as RZ608, expected to work |

Other MediaTek devices are not supported.

## Installation

Use **either** `AirportMtkWlan.kext` **or** `SimpleMtkWlan.kext`, never both:
they match the same card.

### Native Wi-Fi menu (AirportMtkWlan, Tahoe)

1. Download `AirportMtkWlan-Tahoe-x.y.z-RELEASE.zip` (or `-Sequoia-` for macOS
   15.2+) from [Releases](https://github.com/flxxxxddd/SimpleMtkWlan/releases).
2. Copy `AirportMtkWlan.kext` to `EFI/OC/Kexts/` and add it to
   `Kernel → Add` (same entry as below, `BundlePath` `AirportMtkWlan.kext`,
   `ExecutablePath` `Contents/MacOS/AirportMtkWlan`). Set `MinKernel`
   `25.0.0` / `MaxKernel` `25.99.99` for the Tahoe build (`24.2.0` /
   `24.99.99` for Sequoia): each build only fits that IO80211 version and
   would panic on the other.
3. `Kernel → Quirks → DisableIoMapper` = `true` (the driver does not support
   AppleVTD DMA remapping yet).
4. **Do not** apply OCLP "Modern Wireless" root patches and **do not** block
   or replace `IOSkywalkFamily` / inject `IO80211FamilyLegacy`: this kext uses
   the system's own Wi-Fi stack. Remove such leftovers from Intel/Broadcom
   guides.
5. Disable `SimpleMtkWlan.kext` if present and quit / remove the SimpleMTK app.
6. Make sure the card is not hidden (step 4 below), reboot and pick a network
   in the Wi-Fi menu.

`itlwm_he=1` turns on 802.11ax capabilities (experimental, off by default).

### SimpleMtkWlan + SimpleMTK app

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

Optional boot-args: `-novht`, `-noht40`, `-mtknoamsdu` (no TX A-MSDU).

## Troubleshooting

* **Read the driver log.** The driver keeps a persistent ring buffer that
  survives a failed start and is readable without root:

  ```sh
  ./tools/mtklog.sh > mtk.txt
  ```

  A periodic `stats` line shows RX counters, hardware vs software decryption
  (`rx_hwdec` / `rx_swdec`) and the reasons frames are dropped. Both kexts
  write the same log.
* **No Wi-Fi in the menu with AirportMtkWlan.** Check that only one of the
  two kexts is enabled, that no OCLP wireless patch / `IOSkywalkFamily` block
  is active, that `DisableIoMapper` is on and that the build matches your
  macOS (Tahoe vs Sequoia). `ioreg -l -w0 | grep IO80211InterfaceRole` should
  print `Infrastructure`.
* **"SimpleMtkWlan is not running" after a reboot.** A warm reboot does not
  power-cycle an M.2 card. The driver now recovers the chip automatically
  (WFSYS reset, then PCIe function-level reset); if it still fails, shut the
  machine down completely and power it on again.
* **Slow speed.** Check `rx_swdec` in the stats line: it should stay small
  compared to `rx_hwdec`. Speed tests are only meaningful with the SimpleMTK
  menu closed (the client triggers scans; they are throttled to one per two
  minutes while connected).
* **A 2.4 GHz wireless mouse/keyboard stutters while Wi-Fi is on 2.4 GHz.**
  That is RF coexistence in the same band, not a driver bug: keep the card on
  5 GHz (leave only the 5 GHz network in SimpleMTK) or move the dongle away
  from the antennas with a USB extension.
* **Slow to connect after boot.** The network is chosen by the SimpleMTK app,
  which only starts after login; the driver scans until then.
* **Throughput below a real Mac.** On weak signal the AP mostly sends VHT
  MCS 3–4 (see the `rxrate` line). Block Ack Request frames are not delivered
  by the firmware, so the rare reorder gaps close by a 100 ms timeout
  (`ba gap_timeout`).
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

The native Wi-Fi kext is built with a script (not part of the Xcode project):

```sh
./build-macos.sh Release AirportMtkWlan                        # Tahoe (default)
AIRPORT_OS=sequoia ./build-macos.sh Release AirportMtkWlan     # Sequoia 15.2+
# -> build/Release/{tahoe,sequoia}/AirportMtkWlan.kext
```

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
| `SimpleMtkWlan/SimpleMtkWlan.cpp` | IOEthernetController front end (SimpleMtkWlan.kext), watchdog |
| `AirportMtkWlan/` | IO80211 / Skywalk front end (AirportMtkWlan.kext), from AirportItlwm (WCL) |
| `include/Airport/` | IO80211Family / Skywalk headers (`macOS15`, `macOS26` ABI sets) |
| `SimpleMtkWlan/MtkLog.cpp` | persistent debug log shared by both kexts |
| `build-macos.sh` | builds AirportMtkWlan (and SimpleMtkWlan) without Xcode project changes |
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
  Block Ack and TX A-MPDU sessions passed to the firmware. HT 20/40 is
  advertised (APs only send 80 MHz to clients that claim 40 MHz support).
* **802.11ac:** VHT capabilities, STA_REC_VHT, operating width (20/40/80 MHz)
  taken from the association, RX STBC; per-interval RX rate histogram in the
  debug log.
* **Joining:** 5 GHz preferred when within 15 RSSI points of 2.4 GHz, stale
  peer records and stale scan results cleaned up, deauth before the first
  AUTH and on stop, AUTH/ASSOC retransmitted up to 3 times (one lost
  association response used to cost ~20 s).
* **Robustness:** DMA stall watchdog with hard reset + firmware reload, chip
  recovery at attach (WFSYS reset → PCIe FLR), TXWI leak fix.
* **Debuggability:** persistent `MtkDebugLog` ring buffer published on the PCI
  device, periodic hardware/stats dump, quiet logging on the data path.
* **Native Wi-Fi menu (AirportMtkWlan):** laobamac's AirportItlwm Tahoe/Sequoia
  (WCL) front end, as adapted to the MediaTek HAL by pengubow, on top of this
  fork's MT7921 hardware layer. Changes for this card: Tahoe ABI build, the
  front end's watchdog drives the HAL housekeeping (stall recovery,
  AUTH/ASSOC retransmit), no manual MSI enable, shared persistent log, link
  rate from the measured RX rate, and short scans macOS asks for allowed while
  connected (full sweeps stay throttled).
* **TX path:** data frames go to the hardware queue of their access
  category (everything was on VO), no per-frame TX status events, Block Ack
  disabled for TIDs without an agreement, output pauses when the TX ring is
  full instead of dropping packets, hardware A-MSDU inside A-MPDU when the AP
  allows it. VHT SU/MU beamformee and HT LDPC are advertised (Linux defaults).
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
* [pengubow](https://github.com/pengubow/SimpleMtkWlan) — AirportMtkWlan: AirportItlwm's native Wi-Fi front end on the MediaTek HAL (WCL scan/join hooks, private address, Infrastructure role fix, passphrase joins, command-gate sleep)
* [laobamac/itlwm](https://github.com/laobamac/itlwm) — AirportItlwm for Sequoia/Tahoe (WCL layer, macOS 15/26 IO80211 headers, TX pull model, link quality)
* OpenBSD `mwx(4)` driver authors
* [OpenIntelWireless/itlwm](https://github.com/OpenIntelWireless/itlwm) (zxystd) — net80211 port, driver architecture and the original AirportItlwm
* Linux [mt76](https://github.com/openwrt/mt76) — hardware reference
* [acidanthera](https://github.com/acidanthera) — MacKernelSDK

Related: [SimpleMtkBtFw](https://github.com/flxxxxddd/SimpleMtkBtFw) — Bluetooth for MT7921 / RZ608 / MT7922.

See also [CREDITS.md](CREDITS.md).
