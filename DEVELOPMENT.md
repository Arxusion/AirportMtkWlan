# Development & Contributing Guide

This document outlines the architecture, build procedure, test suite, and kernel programming guidelines for **AirportMtkWlan** and **SimpleMtkWlan**.

---

## 1. Building from Source

### Prerequisites
- macOS workstation with Xcode and Xcode Command Line Tools installed.
- Git with submodules initialized (`git submodule update --init`).
- MacKernelSDK (`acidanthera/MacKernelSDK`) pinned for kernel headers and `libkmod`.

### Build Commands

```sh
# Ensure submodules are present
git submodule update --init

# Build AirportMtkWlan for macOS 26 Tahoe (Default)
AIRPORT_OS=tahoe ./build-macos.sh Release AirportMtkWlan

# Build AirportMtkWlan for macOS 15 Sequoia (macOS 15.2+)
AIRPORT_OS=sequoia ./build-macos.sh Release AirportMtkWlan

# Build SimpleMtkWlan (Ethernet client front-end)
./build-macos.sh Release SimpleMtkWlan
```

> [!IMPORTANT]
> **Clean Builds on Header Changes:**
> Always clean the build cache (`rm -rf build`) after modifying headers inside `mtk80211/` or `include/`. Because these directories are included in the compiler system search path, incremental builds will not detect struct layout updates, risking ABI drift and vtable mismatches.

### Verification of Linked Symbols
Verify that the generated binary contains no unresolved symbols against the Darwin kernel:
```sh
kmutil libraries -p build/Release/tahoe/AirportMtkWlan.kext --undef-symbols
```
No undefined symbols or private KPI violations (`com.apple.kpi.private`) should be reported.

---

## 2. Test Suite

The project includes isolated host unit tests that extract core driver functions and execute them against simulated stubs under AddressSanitizer (ASan) and UndefinedBehaviorSanitizer (UBSan).

```sh
./tests/run-all.sh
```

When modifying functions extracted by tests, update the test stubs to reflect new struct fields or parameters rather than weakening test assertions.

---

## 3. Architecture & Repository Layout

```
AirportMtkWlan / SimpleMtkWlan
├── AirportMtkWlan/                  # IO80211 and Skywalk native Wi-Fi front end (WCL)
│   ├── AirportItlwmV2.cpp           # IO80211Controller interface
│   ├── AirportItlwmSkywalkInterface.cpp # Skywalk Ethernet interface binding
│   ├── IOPCIEDeviceWrapper.cpp      # PCI matching & hardware initialization
│   └── WCL/                         # Apple 802.11 Wireless Control Layer (scan/join hooks)
├── SimpleMtkWlan/                   # IOEthernetController front end (Ethernet mode)
│   ├── SimpleMtkWlan.cpp            # Ethernet controller, work loop, watchdog
│   ├── MtkWlanUserClient.cpp        # IOUserClient interface for menu client
│   ├── MtkLog.cpp                   # Ring buffer debug logging
│   └── hal_mwx/                     # MediaTek MT7921 / MT7922 hardware layer (port of OpenBSD mwx)
│       ├── MtkMwx.cpp               # DMA rings, MCU commands, firmware loader, TX/RX, BA
│       └── if_mwxreg.h              # Registers, MCU TLV structures and descriptor definitions
├── mtk80211/                        # OpenBSD net80211 stack & Darwin kernel compatibility glue
├── include/                         # HAL interfaces, embedded firmware, Apple 80211 headers
├── tests/                           # Host ASan / UBSan test suites
├── tools/                           # Developer utilities (mtklog.sh)
└── MacKernelSDK/                    # macOS Kernel SDK headers (git submodule)
```

---

## 4. Kernel Driver Guidelines & Hardware Pitfalls

When making modifications to the hardware abstraction layer (`hal_mwx`) or the 802.11 state machine, keep the following hard-earned constraints in mind:

1. **Firmware Upload Framing:** Firmware chunks are transmitted in payloads strictly sized at `4096 - sizeof(mwx_mcu_txd)` so each message fits into a single 4 KB mbuf cluster. 16 KB jumbo clusters are unavailable during early boot attach.
2. **Interrupt Handling:** Use `kIOInterruptTypePCIMessaged` MSI index. Do not manually manipulate MSI enable bits in PCI config space. Always drain pending interrupts in `mwx_intr` before re-enabling.
3. **TX Linearization:** Multi-mbuf packets must be linearized into a single cluster buffer (`mwx_tx_linearize`) prior to DMA submission to prevent WFDMA ring stalls on small/split frames like DHCP.
4. **Group Traffic Decryption:** MediaTek hardware decryption does not process group-addressed (broadcast/multicast) frames. Keys must be mirrored to `net80211` software CCMP routines for fallback decryption.
5. **State Transition Cleanup:** On leaving `IEEE80211_S_RUN`, disable BSS and delete the peer STA record in the MCU. Reusing WCID 1 on a stale record corrupts subsequent hardware decryption sessions.
6. **WPA2/WPA3 Transition Mode:** When connecting to transition mode networks, Protected Management Frames (PMF / MFP) must be negotiated flexibly. MFPC/MFPR bits must not enforce mandatory PMF on standard WPA2-PSK 4-way handshakes.
7. **Sleep & Wake Lifecycle:** The PCIe card enters D3cold during S3 system sleep. On resume, the driver triggers a WFSYS reset / PCIe FLR and completely reloads firmware through the recovery work queue. Ensure hardware access is guarded by `sc_suspended`.

---

## 5. Persistent Ring Logging

All HAL diagnostic output (`XYLog`, `MWX_DEV_LOG`, `printf`) is stored in an in-memory ring buffer published as the `MtkDebugLog` property on the PCI device node.

To read the log without administrative privileges:
```sh
./tools/mtklog.sh > mtk_debug.log
```
> [!WARNING]
> Never log per-packet on the fast path. Use rate-limiting counters to avoid dropping throughput or flooding the debug ring buffer.

## 6. Optional Throughput Diagnostics

The shell build supports `MTK_PERF=1` for AirportMtkWlan. It defaults to `0`;
SimpleMtkWlan builds keep instrumentation disabled. Build and load a diagnostic
kext before reading its numeric `MtkThroughput` IORegistry property:

```sh
MTK_PERF=1 AIRPORT_OS=tahoe ./build-macos.sh Release AirportMtkWlan
python3 -B tools/airport_throughput.py snapshot
python3 -B tools/airport_throughput.py run --server '<wired-iperf3-server>' \
  --direction down --seconds 20 --omit 3 --streams 1
```

Use `--direction up` for upload or `--streams 4` for a parallel TCP test.
Python 3 is required; `run` also requires iperf3. Output stays in the terminal
unless `--output <new-file.json>` is supplied. Reports contain allowlisted numeric
snapshots and TCP totals; server addresses and other registry properties are
omitted. Existing output files are never overwritten.

Counters cover DMA bounce copies, RX processing and delivery, A-MSDU completion
and failures, BA message submission, TX resource pressure, and queue/state gauges.
The current driver uses a shared workloop and one adapter; the reader requires
exactly one diagnostic property. Most updates run under the main gate; the
watchdog contention counter uses atomic updates. Snapshots are published as a
complete dictionary by the gated watchdog poll. The disabled build omits the
collector, diagnostic fields, and timing calls.

Interpretation:

- Schema 2 includes a kext-session timestamp, sequence number, and timebase.
  The reader rejects session changes, stale snapshots, and decreasing counters.
- Timing regions measure elapsed time, can overlap, and include scheduling;
  their sum is not CPU utilization. RX bounce timing samples one in 64 copies.
- Maximum times cover the kext session, not just the measurement interval.
  A TX pause is counted when it ends, so its duration can cross snapshot boundaries.
- Diagnostic windows include warm-up and snapshot polling; iperf3 receiver
  throughput excludes `--omit`. The two rates use different time windows.
- TX-full events indicate temporary backpressure, not packet drops. BA submission
  counts describe host submission, not firmware acknowledgment. BSD packet/byte
  counts cover infrastructure delivery; AWDL routing is unchanged.

The diagnostic build adds measurement overhead. Use it to locate bottlenecks,
then validate performance and behavior on hardware with the intended release build.
