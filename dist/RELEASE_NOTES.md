## AirportMtkWlan v2.1.3

### Overview
**AirportMtkWlan v2.1.3** resolves sustained throughput bottlenecks, 600–1200 ms loaded bufferbloat/latency spikes, spurious 1000 ms RX stalls, and BlockAck timer/workloop contention under heavy traffic on MediaTek `MT7921`, `MT7921K` (RZ608), and `MT7922` (RZ616) adapters (GitHub Issue `#2`).

---

### What's Fixed in v2.1.3

1. **Advertise Actual Hardware Spatial Streams Before Capability Registration (`MtkMwx.cpp`)**:
   - Extracted `mwx_update_stream_caps()` and called it both at attach and in `mwx_preinit()` once `sc_capa.num_streams` is loaded from MCU (`MT7921`), enabling 2x2 HT/VHT/HE MCS rates instead of being stuck at 1x1 (`mcs_map = 0xfffe`) when `sc_capa.num_streams` was initially `0`.
2. **Prevent Edge-Triggered MSI Interrupt Stranding (`MtkMwx.cpp`)**:
   - In `mwx_intr()`, flush `MT_WFDMA0_HOST_INT_ENA` write with readback and recheck `MT_WFDMA0_HOST_INT_STA & sc_intr_mask` before returning so interrupts arriving while masked are processed immediately rather than stalling up to 1000 ms until `watchdogAction`.
   - Capped `mwx_intr()` at 8 passes and scheduled a 1 ms `sc_intr_to` fallback timeout when still pending so the workloop yields cleanly.
3. **RX DMA Drain Snapshot & Batch Replenish (`MtkMwx.cpp`)**:
   - Removed the mid-loop `MT_DMA_DMA_IDX` re-read inside `mwx_dma_rx_dequeue()` and bounded RX drain + buffer replenishment (`mwx_queue_fill()` every `<= 64` frames, up to 256 frames per interrupt pass) while preserving multi-descriptor `MT_DMA_CTL_LAST_SEC0` chains.
4. **Suppress Active-Traffic Background Scans (`MtkMwx.cpp`)**:
   - Added `mwx_traffic_active()` (`>= 200 pps` in `IEEE80211_S_RUN`) so non-explicit-SSID background scans in `mwx_bgscan()` return `EBUSY` (replaying WCL cache cleanly) instead of pulling the radio off-channel during active transfers.
5. **Firmware WMM/EDCA Configuration & 1024-Slot TX Queue (`MtkMwx.cpp`)**:
   - Updated `mt7921_mcu_set_tx()` to set `.qos = 1` when `IEEE80211_F_QOS` is active and program `req.edca[{2,3,0,1}]` from `ic->ic_edca_ac[EDCA_AC_BE/BK/VI/VO]`, wired `ic->ic_updateedca = mwx_updateedca`, and increased `getTxQueueSize()` from `256` to `1024`.
6. **Throttle BlockAck Reorder Timeout Re-Arming (`ieee80211_input.c`, `ieee80211_node.h`)**:
   - Added `ba_to_last_ns` and `ieee80211_input_ba_rearm_timeout()` to rate-limit `timeout_add_usec(&ba->ba_to, ...)` resets to at most once every `250 ms` (or half of `ba_timeout_val`) per BlockAck RX window.

---

## AirportMtkWlan v1.5.2

### Overview
**AirportMtkWlan v1.5.2** brings Wi-Fi 6 (802.11ax / HE) association capabilities, 256-frame BlockAck window expansion, RX A-MSDU subframe reassembly, and Skywalk link quality metric (LQM) fixes for MediaTek MT7921 / MT7921K (AMD RZ608) and MT7922 (AMD RZ616) wireless chipsets on macOS 26 Tahoe and macOS 15 Sequoia.

---

### What's New in v1.5.2

- **Wi-Fi 6 (802.11ax / HE) Association & Capabilities:**
  - Integrated HE MAC / PHY capability information elements into association requests in `AirportItlwm` and MediaTek HAL (`hal_mwx`).
  - Enables clean association with Wi-Fi 6 APs without falling back prematurely or experiencing handshake disconnects.
- **RX BlockAck Window Scaled to 256:**
  - Increased `net80211` BlockAck reorder buffer from 64 to 256 frames for 802.11ax streams.
  - Eliminates packet drops, retransmission storms, and buffer starvation during sustained multi-hundred Mbps transfers.
- **Hardware RX A-MSDU Reassembly:**
  - Added native A-MSDU subframe unpacking in the packet receive path, delivering true gigabit-class local throughput without truncation.
- **Skywalk RSSI & LQM Metrics Fix:**
  - Fixed `getRSSI` header version formatting and eliminated zero-snapshot anomalies in `LqmBeaconUpdate` to provide smooth, accurate signal bars in macOS menu bar and Control Center.
- **Resolved TXWI Upload Throttling:**
  - Retained and verified the critical TXWI frame-type mask fix ensuring data frames are never misrouted at basic management rates (resolving the previous 1–2 Mbps upload cap).
- **AirportMtkWlan Installer v1.5.2:**
  - Updated native installer utility with automated EFI mounting, OpenCore kext injection, and live kernel extension status reporting.

---

### Package Contents

| Archive | Intended Operating System | Kernel Range |
|---|---|---|
| **`AirportMtkWlan-Tahoe-v1.5.2-RELEASE.zip`** | macOS 26 Tahoe | `25.0.0` - `25.99.99` |
| **`AirportMtkWlan-Sequoia-v1.5.2-RELEASE.zip`** | macOS 15 Sequoia (15.2+) | `24.2.0` - `24.99.99` |
| **`AirportMtkWlan-Installer-v1.5.2.zip`** | macOS 26 / 15 GUI Installer | `24.0.0`+ |
| **`SimpleMtkWlan-v1.5.2-RELEASE.zip`** | Any supported macOS version (Ethernet mode) | `*` |

---

## AirportMtkWlan v1.5.1

### Overview
**AirportMtkWlan** is an open-source native AirPort / Skywalk Wi-Fi kernel extension for **MediaTek MT7921, MT7921K (AMD RZ608), and MT7922 (AMD RZ616)** PCIe wireless adapters on macOS.

This release brings crucial association fixes for modern WPA2/WPA3 mixed access points, updated regulatory domain discovery, and production-ready distribution builds for macOS 26 Tahoe and macOS 15 Sequoia.

---

### What's New in v1.5.1

- **WPA2 / WPA3 Transition Mode Support:**
  - Resolved association failures on mixed WPA2/WPA3 networks and smartphone hotspots.
  - Relaxed strict Protected Management Frame (PMF / MFP) enforcement: client will not mandate MFPR/MFPC when operating in legacy WPA2 transition mode.
  - WCL (Wireless Control Layer) automatically translates SAE candidate targets to PSK for mixed-mode BSSIDs.
- **Regulatory Domain Discovery:**
  - Streamlined country code acquisition hierarchy (`mtk_cc` boot-arg > NVRAM `mtk-wifi-cc` > geolocation / 802.11d country IE > firmware domain).
  - Unlocked full 5 GHz channel tables across standard global regulatory domains.
- **Band Prioritization:**
  - Added configurable band selection knob via NVRAM (`mtk-wifi-band`).
  - Scans 5 GHz channels first by default and automatically de-duplicates overlapping 2.4 GHz twin BSSIDs when signal strength is comparable.
- **Production Build Architecture:**
  - Clean separation of Tahoe (macOS 26) and Sequoia (macOS 15.2+) IO80211 vtable ABI layers.
  - Strict compliance with public Darwin kernel KPIs (`com.apple.kpi.iokit`, `com.apple.kpi.libkern`, `com.apple.kpi.mach`).
  - Comprehensive unit test suite with ASan/UBSan stubs.

---

### Package Contents

| Archive | Intended Operating System | Kernel Range |
|---|---|---|
| **`AirportMtkWlan-Tahoe-v1.5.1-RELEASE.zip`** | macOS 26 Tahoe | `25.0.0` - `25.99.99` |
| **`AirportMtkWlan-Sequoia-v1.5.1-RELEASE.zip`** | macOS 15 Sequoia (15.2+) | `24.2.0` - `24.99.99` |
| **`SimpleMtkWlan-v1.5.1-RELEASE.zip`** | Any supported macOS version (Ethernet mode) | `*` |

---

### OpenCore Quick Setup

1. Copy `AirportMtkWlan.kext` matching your macOS version into `EFI/OC/Kexts/`.
2. Inject into `config.plist` under `Kernel -> Add` with the appropriate `MinKernel` / `MaxKernel`.
3. Set `Kernel -> Quirks -> DisableIoMapper` = `true`.
4. Ensure no conflicting Broadcom or Intel OCLP root patches or Skywalk blocks are applied.
