## AirportMtkWlan v2.1.6

### Overview
**AirportMtkWlan v2.1.6** is a critical stability and performance release. It resolves system hard-freezes on AMD Ryzen platforms and permanent `lpctl=0x00000004` attach failures across warm reboots on PCIe riser cards without dedicated `PERST#` lines (#11). It also incorporates the v2.1.5 throughput engine overhaul, resolving the `< 40 Mbps` ceiling on MT7921/MT7922 hardware by enabling RX A-MSDU BlockAck agreements, uncapping RX batch processing to 512 frames, and eliminating edge-triggered MSI interrupt stranding.

---

### What's Fixed in v2.1.6

1. **Fix AMD Ryzen PCIe Root Port Deadlock & Section 5.4.1.3 ASPM Sequencing (`MtkMwx.cpp`)**:
   - Fixed ASPM link disable order to clear the Downstream Port (`parent`) before the Upstream Port (`ep`) per PCIe Base Specification Section 5.4.1.3.
   - Bypassed parent bridge ASPM modification entirely on AMD host bridges/root ports (`parent_vendor == 0x1022`). On AMD platforms, macOS lacks native PCIe power management control via ACPI `_OSC`; modifying root port registers corrupted the link state machine and deadlocked the PCIe bus as soon as traffic/DMA began (Issue #11).
   - Parent bridges now never have their L1SS extended capability registers modified directly, matching upstream Linux `mt76_pci_disable_aspm`.
   - Added new boot-args: `-mtkallowaspm` (keep ASPM intact), `-mtknoparentaspm` (skip parent bridge modification), and `-mtkforceparentaspm` (override AMD check if explicitly requested).

2. **Fix Warm-Boot Attach Failures & `lpctl=0x00000004` on Riser Cards (`MtkMwx.cpp`)**:
   - When running on M.2-to-PCIe riser cards without a dedicated `PERST#` line, standby power keeps the MT7922 active across soft/warm reboots.
   - In `mwx_ensure_drv_own()`, early-return if the driver already holds ownership (`(lpctl & PCIE_LPCR_HOST_OWN_SYNC) == 0`).
   - Removed premature `mwx_mcu_fw_pmctrl()` calls that surrendered chip ownership to firmware right before requesting driver ownership.
   - Increased `mwx_mcu_drv_pmctrl()` polling timeout from 50 ms to 500 ms (matching Linux `mt76_poll_msec`), allowing sufficient settling time for firmware/hardware power transitions without dropping into failed WFSYS reset/FLR loops.

3. **Gate AWDL & RSDB Multi-Channel Scheduling behind Boot-Args (`AirportItlwmSkywalkInterface.cpp`, `AirportItlwmV2.cpp`)**:
   - Prevented Skywalk and `wifip2pd` from forcibly initiating Real Simultaneous Dual Band (RSDB) and virtual `awdl0` multi-channel interfaces on single-MAC OpenBSD HALs.
   - Gated `rsdb` capability, SDB flags, and virtual interface creation behind `-mtkawdl` and `-mtkrsdb`.

---

## AirportMtkWlan v2.1.5

### Overview
**AirportMtkWlan v2.1.5** resolves the sustained `< 40 Mbps` bottleneck on MediaTek MT7921/MT7922 Wi-Fi hardware.

---

### What's Fixed in v2.1.5

1. **Enable RX A-MSDU in MCU BlockAck Agreement (`mwx_ampdu_rx_start`)**:
   - Programmed MCU BlockAck parameters to accept aggregated MSDUs inside A-MPDUs.
2. **Prevent Multi-Chunk A-MSDU Packet Drops (`mwx_amsdu_flush`)**:
   - Preserved chained mbufs using linear `mbuf_copyback` so large frame segments are delivered intact to the network stack.
3. **Uncapped RX Queue Drain Budget (`MtkMwx.cpp`)**:
   - Raised per-call RX processing budget to 512 frames (128x4) and up to 2048 descriptors per interrupt pass.
4. **Eliminate Edge-Triggered MSI Stranding (`mwx_intr`)**:
   - Re-triggered `interruptOccurred` when unconsumed work remained in the DMA ring after yielding the workloop.

---

## AirportMtkWlan v2.1.4

### Overview
**AirportMtkWlan v2.1.4** fixes the `< 40 Mbps` throughput ceiling and 15-second workloop starvation on AMD Ryzen / PCIe ASPM systems, removes per-packet TX MMIO doorbell stalls, preserves in-flight RX A-MSDU chains against unrelated management/control traffic (`ba_below` drops), and fixes Wi-Fi `Off -> On` HAL disable/reset recovery.

---

### What's Fixed in v2.1.4

1. **Disable PCIe ASPM (L0s/L1) & L1 PM Substates (L1.1/L1.2) (`MtkMwx.cpp`)**:
   - Added `mwx_pci_disable_aspm()` called during attach, post-FLR, and resume to clear L1SS `CTL1` (`0x0f`) and PCIe `LNKCTL` (`0x03`) on the downstream `MT7921`/`MT7922` endpoint first and its upstream root/switch bridge second (override via `-mtkallowaspm`).
2. **Eliminate `_fWorkloop` (`IO80211WorkQueue`) Starvation (`AirportItlwmV2.cpp`, `SimpleMtkWlan.cpp`, `MtkMwx.cpp`)**:
   - Switched `configureOutputPullModel` off `kIONetworkWorkLoopSynchronous` to the async pull thread (`0`), serializing each `<= 64`-packet burst once via `_fCommandGate->runAction(outputStartGated, ...)`.
   - Bounded `mwx_intr()` (`max_passes = 2`) and `mwx_dma_rx_done()` (`max_chunks = 2`) so the workloop yields `gateLock` promptly to WCL commands, output bursts, and watchdog timers.
3. **Batch TX MMIO Doorbells & Wake `oactive` on Ring Free (`MtkMwx.cpp`)**:
   - Updated `mwx_start()` / `mwx_dma_txwi_enqueue()` to defer `MT_DMA_CPU_IDX` writes to once per 16 frames (or burst end), and updated `mwx_dma_tx_done()` to invoke `mwx_tx_kick(sc)` when TX slots reopen under `oactive`.
4. **Prevent Premature RX A-MSDU Splits & Fix Wi-Fi `Off -> On` Recovery (`MtkMwx.cpp`)**:
   - Restricted non-AMSDU flushes in `mwx_rx()` to `IEEE80211_FC0_TYPE_DATA` frames from `sc_amsdu_ta` so neighbor beacons/control frames do not split A-MSDUs into `ba_below` drops.
   - Completed `Off -> On` HAL disable/reset recovery when firmware state must be reinitialized.

---

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
