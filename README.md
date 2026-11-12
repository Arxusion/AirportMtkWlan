# AirportMtkWlan

[![Release](https://img.shields.io/github/v/release/Arxusion/AirportMtkWlan)](https://github.com/Arxusion/AirportMtkWlan/releases)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20Tahoe%20%7C%20Sequoia-lightgrey.svg)](https://apple.com/macos)

**Native AirPort & Skywalk Wi-Fi driver for MediaTek MT7921 / MT7921K (AMD RZ608) / MT7922 (AMD RZ616) PCIe cards on macOS.**

`AirportMtkWlan` is an open-source macOS kernel extension based on the OpenBSD `mwx(4)` driver and the `net80211` wireless stack. It integrates directly with Apple's `IO80211Family` and `IOSkywalkFamily` subsystems to provide a seamless, native Wi-Fi experience without requiring OpenCore Legacy Patcher (OCLP) root patches or system framework downgrades.

The repository builds two front-ends:
* **`AirportMtkWlan.kext` (Recommended)**: Drives the card as a genuine native AirPort interface on **macOS 26 Tahoe** and **macOS 15 Sequoia (15.2+)**. Features full support for the macOS Control Center Wi-Fi menu, System Settings, Keychain credentials, auto-join at boot, and private MAC addressing.
* **`SimpleMtkWlan.kext`**: Exposes the card as a virtual Ethernet interface (`enX`) managed via the [SimpleMTK](https://github.com/laobamac/SimpleMTKClient) menu-bar utility. Compatible with older macOS versions.

---

## Features & Implementation Status

| Capability | Status | Implementation Details |
|---|:---:|---|
| **PCIe Initialization & Firmware** | ✅ | Automated firmware staging in 4 KB DMA clusters; MSI interrupt registration |
| **Native macOS Wi-Fi UI** | ✅ | Direct binding to `IO80211SkywalkInterface` and `IO80211Controller` |
| **Channel Scanning** | ✅ | Concurrent 2.4 GHz and 5 GHz sweeps with fast background scan throttling |
| **WPA2-PSK & Enterprise** | ✅ | 4-way EAPOL handshake, PEAP/802.1X MSK & PMKSA caching, hardware CCMP |
| **WPA2 / WPA3 Transition Mode** | ✅ | Dynamic PMF/MFP negotiation and SAE-to-PSK fallback for mixed networks |
| **802.11n (HT20 / HT40)** | ✅ | MCS 0–15, Short Guard Interval (SGI), RX STBC, WMM QoS queuing |
| **802.11ac (VHT20 / 40 / 80)** | ✅ | 2×2 MIMO up to 867 Mbps PHY rate, VHT beamformee, HT LDPC |
| **Frame Aggregation** | ✅ | Hardware A-MPDU session management with TX A-MSDU subframe packing |
| **DMA Watchdog & Recovery** | ✅ | Automatic WFDMA stall detection, PCIe FLR reset, and firmware re-initialization |
| **Power Management (S3)** | ✅ | Clean hardware quiescing on sleep; full re-attach and firmware restore on wake |
| **Network Roaming** | ✅ | Band steering preferring 5 GHz when within 15 dBm RSSI of 2.4 GHz |
| **802.11ax (HE)** | ✅ | Wi-Fi 6 HE association, 256 BlockAck window, and A-MSDU reassembly enabled |
| **Apple Continuity / AWDL** | 🚧 | Dedicated research repository: [AirportMtk-AWDL](https://github.com/Arxusion/AirportMtk-AWDL) |

---

## Supported Hardware

| Wireless Card | PCI ID | macOS Target | Performance & Stability |
|---|---|---|---|
| **MediaTek MT7921K (AMD RZ608)** | `14c3:0608` | macOS 26 Tahoe / 15 Sequoia | Native Wi-Fi menu, Keychain auto-join, full VHT80 speeds |
| **MediaTek MT7921** | `14c3:7961` | macOS 26 Tahoe / 15 Sequoia | Verified operational on identical chip architecture |
| **MediaTek MT7922 (AMD RZ616)** | `14c3:0616` | macOS 26 Tahoe / 15 Sequoia | Native Wi-Fi menu and full 802.11ac support |
| **MediaTek MT7922** | `14c3:7922` | macOS 26 Tahoe / 15 Sequoia | Operational with standard channel widths |

> [!NOTE]
> - Ensure any vendor SSDT designed to disguise or disable non-Apple Wi-Fi cards (such as `SSDT-Disable_Network_*.aml`) is disabled in your OpenCore configuration. The device must present its native vendor ID `0x14C3`.
> - **Unsupported / Out-of-Scope Hardware**: USB MediaTek adapters such as **MT7921AU** (`0e8d:7961`) and different PCIe silicon such as **MediaTek MT7902 / MT7902LEN** are **not supported**. This driver exclusively targets PCIe MT7921 (`MT7921`/`MT7921K`/`RZ608`) and MT7922 (`MT7922`/`RZ616`) chipsets.

---

## Installation Guide (OpenCore)

### Option A: Graphical OpenCore Installer (Recommended)
Download **`AirportMtkWlan-Installer-v2.1.3.zip`** from [Releases](https://github.com/Arxusion/AirportMtkWlan/releases).
- Launch `AirportMtkWlan Installer.app`
- Select your target OpenCore EFI partition (or click Browse to locate your EFI folder)
- Choose your OS flavor (`macOS 26 Tahoe` or `macOS 15 Sequoia`)
- Click **Deploy Driver to EFI** — the app copies the driver into `EFI/OC/Kexts`, sets `DisableIoMapper = true`, and registers the kext in `config.plist`.

### Option B: Manual Installation

1. Download the latest release package matching your macOS version from [Releases](https://github.com/Arxusion/AirportMtkWlan/releases):
   * `AirportMtkWlan-Sequoia-v2.1.3-RELEASE.zip` for **macOS 15 Sequoia (15.2+)**
   * `AirportMtkWlan-Tahoe-v2.1.3-RELEASE.zip` for **macOS 26 Tahoe**
   * *For macOS 14 Sonoma, 13 Ventura, or earlier*: Native AirPort Skywalk is not compatible; download `SimpleMtkWlan.kext` and use [SimpleMTK](https://github.com/laobamac/SimpleMTKClient) (HeliPort).
2. Extract and place `AirportMtkWlan.kext` into your EFI directory: `EFI/OC/Kexts/`.
3. Add the kernel extension entry to your `config.plist` under `Kernel -> Add`:

#### For macOS 15 Sequoia:
```xml
<dict>
    <key>Arch</key>
    <string>x86_64</string>
    <key>BundlePath</key>
    <string>AirportMtkWlan.kext</string>
    <key>Comment</key>
    <string>MediaTek MT7921 / MT7922 Native Wi-Fi Driver (Sequoia)</string>
    <key>Enabled</key>
    <true/>
    <key>ExecutablePath</key>
    <string>Contents/MacOS/AirportMtkWlan</string>
    <key>MinKernel</key>
    <string>24.2.0</string>
    <key>MaxKernel</key>
    <string>24.99.99</string>
    <key>PlistPath</key>
    <string>Contents/Info.plist</string>
</dict>
```

#### For macOS 26 Tahoe:
```xml
<dict>
    <key>Arch</key>
    <string>x86_64</string>
    <key>BundlePath</key>
    <string>AirportMtkWlan.kext</string>
    <key>Comment</key>
    <string>MediaTek MT7921 / MT7922 Native Wi-Fi Driver (Tahoe)</string>
    <key>Enabled</key>
    <true/>
    <key>ExecutablePath</key>
    <string>Contents/MacOS/AirportMtkWlan</string>
    <key>MinKernel</key>
    <string>25.0.0</string>
    <key>MaxKernel</key>
    <string>25.99.99</string>
    <key>PlistPath</key>
    <string>Contents/Info.plist</string>
</dict>
```

> [!IMPORTANT]
> - **Enable `Kernel -> Quirks -> DisableIoMapper = true` in OpenCore**: The driver programs physical DMA rings directly and does not support AppleVTD IOMMU remapping. Leaving AppleVTD enabled can cause firmware/DMA stalls or Wi-Fi failures on Tahoe and Sequoia.
> - **Match your macOS kernel version**: Use the **Sequoia** build with `MinKernel = 24.2.0` / `MaxKernel = 24.99.99` on macOS 15.2+ and the **Tahoe** build with `MinKernel = 25.0.0` / `MaxKernel = 25.99.99` on macOS 26. Setting the wrong `MinKernel` prevents injection, and injecting the wrong OS build breaks `IO80211SkywalkInterface` vtables.
> - **Fixing OpenCore `Invalid Parameter` at boot**: Re-download the matching zip (do not rename/strip inside the `.kext` bundle), confirm `Arch = x86_64`, `ExecutablePath = Contents/MacOS/AirportMtkWlan`, `PlistPath = Contents/Info.plist`, and remove any old copies from `/Library/Extensions` or `EFI/OC/Kexts`.
> - **Do NOT** load `AirportMtkWlan.kext` and `SimpleMtkWlan.kext` simultaneously.

---

## Configuration & Tuning

### NVRAM Variables

Configuration properties can be set in OpenCore NVRAM (`7C436110-AB2A-4BBB-A880-FE41995C9F82`) as either `<string>` or `<data>` values:

| Property | Values | Description |
|---|---|---|
| `mtk-wifi-band` | `5`, `2`, *unset* | `5` restricts the driver to 5 GHz channels only; `2` restricts to 2.4 GHz channels only. Unset enables dual-band operation preferring 5 GHz when RSSI is comparable. |
| `mtk-wifi-cc` | e.g. `CN`, `US`, `IN`, `DE`, `00` | Overrides the regulatory country code (`<string>` or ASCII `<data>`) for 802.11d channel availability. |

### Boot Arguments

Optional boot arguments can be added to `boot-args` in OpenCore:

* `mtk_cc=XX` — Overrides the 2-letter ISO country code.
* `-no160` — Restricts 802.11ac/ax to 80 MHz channel width (disables 160 MHz).
* `-novht` — Disables 802.11ac VHT capabilities (limits connection to 802.11n).
* `-noht40` — Restricts 802.11n to 20 MHz channel width.
* `-mtknoamsdu` — Disables hardware TX A-MSDU inside A-MPDU aggregation.
* `-mtkwlanoff` — Emergency safe-boot flag: parks the driver and halts initialization without panicking.

---

## Diagnostics, Log Grabber & Bug Reporting

When something fails to load, scan, toggle Wi-Fi, or connect, use the built-in diagnostic log grabber to capture every log needed for debugging in one automatically redacted `.tar.gz` archive:

* **From the GUI Installer (Recommended)**: Open **AirportMtkWlan Installer**, click **Grab Logs**, choose **Grab Full Logs (Admin)** (so `dmesg`, `wdutil`, previous-boot kernel logs, and your sanitized OpenCore config are included), then click **Open GitHub Issue & Attach** and drag the archive from your Desktop into the issue.
* **From Terminal or Finder**:

```sh
# Full redacted diagnostic archive saved to Desktop:
sudo ./tools/mtk-grab-logs.sh
# Or double-click tools/Grab Logs.command in Finder

# Quick in-kernel MtkDebugLog ring buffer only (no root required):
./tools/mtklog.sh > mtk_debug.log
```

Captured archives automatically redact usernames, hostnames, serial numbers, UUIDs, `MLB`/`ROM`, Wi-Fi keys/passphrases, SSIDs, BSSID/MAC host bytes, and IP addresses before saving, while preserving `MtkDebugLog`, MediaTek PCI/USB IDs, `kmutil` & `/Library/Extensions` state, `airportd`/`kernel` logs, and sanitized OpenCore settings.

---

## Building from Source

Detailed build requirements, Xcode project instructions, and unit test details are documented in [DEVELOPMENT.md](DEVELOPMENT.md).

```sh
# Clone with submodules
git clone --recurse-submodules https://github.com/Arxusion/AirportMtkWlan.git
cd AirportMtkWlan

# Compile Release build for macOS 26 Tahoe
AIRPORT_OS=tahoe ./build-macos.sh Release AirportMtkWlan
```

---

## Credits & Upstream Acknowledgements

* **[laobamac (王孝慈)](https://github.com/laobamac)** — Original creator of SimpleMtkWlan, SimpleMTK, and contributor to Tahoe/Sequoia WCL native Wi-Fi architecture.
* **[zxystd (钟先耀)](https://github.com/OpenIntelWireless/itlwm)** — Pioneer of the macOS `net80211` kernel port and AirportItlwm framework.
* **[pengubow](https://github.com/pengubow/SimpleMtkWlan)** — MediaTek HAL integration for AirportItlwm WCL front-end.
* **[flxxxxddd](https://github.com/flxxxxddd/SimpleMtkWlan)** — MT7921/RZ608 bringing up, 802.11n/ac aggregation, and initial Tahoe build support.
* **[Aswini Soni (Arxusion)](https://github.com/Arxusion)** — WPA2/WPA3 transition mode & WPA2-Enterprise fixes, PMF/MFP & WCL stability improvements, country/band NVRAM fixes, and release packaging.
* **[yusufcanyavic](https://github.com/yusufcanyavic/YYavicWiFi)** (`GPL-3.0-or-later`) — 256-entry RX BlockAck reorder window and 100 ms gap timeout, HE STA firmware TLV builder (`mwx_yy_sta_he_tlv`), and RX A-MSDU reassembly (`mwx_amsdu_*`).
* **OpenBSD & Linux mt76 Developers** — Hardware reference and `mwx(4)` driver implementation.
* **[Acidanthera](https://github.com/acidanthera)** — `MacKernelSDK` and the OpenCore bootloader ecosystem.

---

## License

This project is licensed under the **GNU General Public License v3.0 or later (GPL-3.0-or-later)**. See [LICENSE](LICENSE) and [CREDITS.md](CREDITS.md) for complete terms and upstream source attributions. Individual files retain their original copyright and license notices, and embedded MediaTek firmware binaries remain under their respective vendor redistribution licenses.
