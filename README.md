# AirportMtkWlan

[![Release](https://img.shields.io/github/v/release/Arxusion/AirportMtkWlan)](https://github.com/Arxusion/AirportMtkWlan/releases)
[![License: GPL v2](https://img.shields.io/badge/license-GPLv2-blue.svg)](LICENSE)
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
| **WPA2-PSK Authentication** | ✅ | Robust 4-way EAPOL handshake with hardware CCMP decryption |
| **WPA2 / WPA3 Transition Mode** | ✅ | Dynamic PMF/MFP negotiation and SAE-to-PSK fallback for mixed networks |
| **802.11n (HT20 / HT40)** | ✅ | MCS 0–15, Short Guard Interval (SGI), RX STBC, WMM QoS queuing |
| **802.11ac (VHT20 / 40 / 80)** | ✅ | 2×2 MIMO up to 867 Mbps PHY rate, VHT beamformee, HT LDPC |
| **Frame Aggregation** | ✅ | Hardware A-MPDU session management with TX A-MSDU subframe packing |
| **DMA Watchdog & Recovery** | ✅ | Automatic WFDMA stall detection, PCIe FLR reset, and firmware re-initialization |
| **Power Management (S3)** | ✅ | Clean hardware quiescing on sleep; full re-attach and firmware restore on wake |
| **Network Roaming** | ✅ | Band steering preferring 5 GHz when within 15 dBm RSSI of 2.4 GHz |
| **802.11ax (HE)** | ⏳ | Under active development |
| **Apple Continuity / AWDL** | ❌ | Requires proprietary Apple wireless driver extensions |

---

## Supported Hardware

| Wireless Card | PCI ID | macOS Target | Performance & Stability |
|---|---|---|---|
| **MediaTek MT7921K (AMD RZ608)** | `14c3:0608` | macOS 26 Tahoe / 15 Sequoia | Native Wi-Fi menu, Keychain auto-join, full VHT80 speeds |
| **MediaTek MT7921** | `14c3:7961` | macOS 26 Tahoe / 15 Sequoia | Verified operational on identical chip architecture |
| **MediaTek MT7922 (AMD RZ616)** | `14c3:0616` | macOS 26 Tahoe / 15 Sequoia | Native Wi-Fi menu and full 802.11ac support |
| **MediaTek MT7922** | `14c3:7922` | macOS 26 Tahoe / 15 Sequoia | Operational with standard channel widths |

> [!NOTE]
> Ensure any vendor SSDT designed to disguise or disable non-Apple Wi-Fi cards (such as `SSDT-Disable_Network_*.aml`) is disabled in your OpenCore configuration. The device must present its native vendor ID `0x14C3`.

---

## Installation Guide (OpenCore)

1. Download the latest release package for your macOS version from [Releases](https://github.com/Arxusion/AirportMtkWlan/releases):
   * `AirportMtkWlan-Tahoe-v1.5.1-RELEASE.zip` for **macOS 26 Tahoe**
   * `AirportMtkWlan-Sequoia-v1.5.1-RELEASE.zip` for **macOS 15 Sequoia**
2. Extract and place `AirportMtkWlan.kext` into your EFI directory: `EFI/OC/Kexts/`.
3. Add the kernel extension entry to your `config.plist` under `Kernel -> Add`:

```xml
<dict>
    <key>Arch</key>
    <string>x86_64</string>
    <key>BundlePath</key>
    <string>AirportMtkWlan.kext</string>
    <key>Comment</key>
    <string>MediaTek MT7921 / MT7922 Native Wi-Fi Driver</string>
    <key>Enabled</key>
    <true/>
    <key>ExecutablePath</key>
    <string>Contents/MacOS/AirportMtkWlan</string>
    <key>MaxKernel</key>
    <string>25.99.99</string>
    <key>MinKernel</key>
    <string>25.0.0</string>
    <key>PlistPath</key>
    <string>Contents/Info.plist</string>
</dict>
```

> [!IMPORTANT]
> - Set `MinKernel` and `MaxKernel` appropriately: `25.0.0` / `25.99.99` for **Tahoe**, or `24.2.0` / `24.99.99` for **Sequoia**. The IO80211 internal vtable layouts differ across major OS releases.
> - Enable `Kernel -> Quirks -> DisableIoMapper` = `true` in OpenCore. The driver interacts directly with physical DMA and does not currently support AppleVTD remapping.
> - **Do NOT** load `AirportMtkWlan.kext` and `SimpleMtkWlan.kext` simultaneously.

---

## Configuration & Tuning

### NVRAM Variables

Configuration properties can be set in OpenCore NVRAM (`7C436110-AB2A-4BBB-A880-FE41995C9F82`):

| Property | Values | Description |
|---|---|---|
| `mtk-wifi-band` | `5`, `2`, *unset* | `5` locks the driver to 5 GHz channels only. `2` disables band prioritization. Unset defaults to preferring 5 GHz when RSSI is comparable. |
| `mtk-wifi-cc` | e.g. `US`, `IN`, `DE`, `00` | Overrides the regulatory country code for 802.11d channel availability. |

### Boot Arguments

Optional boot arguments can be added to `boot-args` in OpenCore:

* `mtk_cc=XX` — Overrides the 2-letter ISO country code.
* `-novht` — Disables 802.11ac VHT capabilities (limits connection to 802.11n).
* `-noht40` — Restricts 802.11n to 20 MHz channel width.
* `-mtknoamsdu` — Disables hardware TX A-MSDU inside A-MPDU aggregation.
* `-mtkwlanoff` — Emergency safe-boot flag: parks the driver and halts initialization without panicking.

---

## Diagnostics & Kernel Logging

The driver maintains an in-kernel circular debug ring buffer that persists across soft reboots and is accessible without root permissions:

```sh
./tools/mtklog.sh > mtk_debug.log
```

The output contains periodic frame statistics (`rx_hwdec`, `rx_swdec`, drop counts), PHY link rate distribution, and DMA ring health status.

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
* **[Aswini Soni (Arxusion)](https://github.com/Arxusion)** — WPA2/WPA3 transition mode association engine, PMF/MFP negotiation fixes, WCL authentication mapping, country code discovery improvements, and release packaging.
* **OpenBSD & Linux mt76 Developers** — Hardware reference and `mwx(4)` driver implementation.
* **[Acidanthera](https://github.com/acidanthera)** — `MacKernelSDK` and the OpenCore bootloader ecosystem.

---

## License

This project is licensed under the **GNU General Public License v2.0 (GPL-2.0)**. See the [LICENSE](LICENSE) file for complete terms. Embedded MediaTek firmware binaries remain under their respective vendor redistribution licenses.
