## AirportMtkWlan v1.6.1 (Hardware 160 MHz Isolation & AMD RZ616 PCI ID 0x0616)

AirportMtkWlan v1.6.1 brings official support for the **MediaTek MT7922K (AMD RZ616)** PCI ID (`14c3:0616`), hardware-level channel bandwidth isolation for 160 MHz networks, new `-no160` boot argument controls, and dynamic 802.11ax (Wi-Fi 6) rate accounting up to 2402 Mbps.

### What's Changed in v1.6.1

- **AMD RZ616 (MT7922K) Official PCI Support (`14c3:0616`)**:
  - Added `#define PCI_PRODUCT_MEDIATEK_MT7922K 0x0616` to HAL device matching table (`mwx_devices`).
  - Added `0x061614c3` to `SimpleMtkWlan/Info.plist` and verified in `AirportMtkWlan/WCL/Info.plist`.
  - Configures RZ616 cards under `MWX_HW_MT7922` hardware profile with MT7922 firmware/ROM patches and dual-stream 160 MHz capabilities.
- **Hardware-Aware 160 MHz Bandwidth Isolation**:
  - **MT7921 / MT7921K (AMD RZ608)**: Strictly capped at 80 MHz channel width (`IEEE80211_CHAN_VHT80`, `rx_mcs_160 = 0xffff`). Prevents previous reconnection loops and frame drops caused by APs attempting 160 MHz wideband transmission on 80 MHz-only physical RF filters.
  - **MT7922 / MT7922K (AMD RZ616)**: Full 160 MHz operation enabled on 5 GHz channels 36–64 & 100–128 (`IEEE80211_CHAN_VHT160`, `IEEE80211_VHTCAP_SUPP_CHAN_WIDTH_160MHZ`, `IEEE80211_HE_PHY_CAP0_CHANNEL_WIDTH_SET_160MHZ_IN_5G`, and 2×2 MIMO MCS 11 rates).
- **New Boot Argument `-no160`**:
  - Added `-no160` boot argument to allow MT7922 users to force-limit association to 80 MHz channel widths in areas with radar/DFS interference.
- **Dynamic HE (Wi-Fi 6) RX Rate Accounting**:
  - Implemented full IEEE 802.11ax rate table covering MCS 0–11 across 20/40/80/160 MHz channels up to 2402 Mbps PHY link speed.
  - Fixed initial HE association rate reporting in WCL so macOS Control Center never displays "0 Mbps".
- **Updated Native Installer App v1.6.1**:
  - Rebuilt installer bundle with all v1.6.1 release binaries and updated driver status detection.

### Binaries Included

| Asset | Target OS | Kernel Version Range |
| :--- | :--- | :--- |
| `AirportMtkWlan-Tahoe-v1.6.1-RELEASE.zip` | macOS 26 Tahoe | `25.0.0` - `26.99.99` |
| `AirportMtkWlan-Sequoia-v1.6.1-RELEASE.zip` | macOS 15 Sequoia (15.2+) | `24.2.0` - `24.99.99` |
| `AirportMtkWlan-Installer-v1.6.1.zip` | macOS 26 / 15 GUI Installer App | `24.0.0`+ |
| `SimpleMtkWlan-v1.6.1-RELEASE.zip` | macOS Sonoma / Ventura / Monterey / any | `*` |
