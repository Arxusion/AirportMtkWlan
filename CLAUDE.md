# CLAUDE.md

Guidance for working on SimpleMtkWlan, a macOS kext for MediaTek MT7921 / MT7921K
(RZ608) / MT7922 PCIe Wi-Fi.

## Build

```sh
git submodule update --init            # MacKernelSDK (kernel headers + libkmod)
xcodebuild -project SimpleMtkWlan.xcodeproj -scheme SimpleMtkWlan \
  -configuration Debug -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
```

- **Clean build (`rm -rf build`) after touching any header in `mtk80211/` or
  `include/`.** Those directories are in `SYSTEM_HEADER_SEARCH_PATHS`, so Xcode
  does not track them and silently links stale objects (this once left all of
  `net80211` logging to `kprintf` and risked mismatched vtables). Editing only
  `.cpp` files is safe incrementally.
- Check the result links against the running kernel:
  `kmutil libraries -p build/Build/Products/Debug/SimpleMtkWlan.kext --undef-symbols`
  must report no unresolved symbols.
- `MODULE_VERSION` must stay purely numeric (`1.2.3`); a suffix makes the kernel
  reject the kext. CI derives it from `vX.Y.Z` tags.

## Tests

`./tests/run-all.sh` runs all host tests. They slice real functions out of the
sources (by signature string) and compile them with stub headers under
ASan/UBSan. When you change a function a test extracts, update that test's
stubs (new fields, structs or helper calls) rather than weakening its asserts.

## Layout

- `SimpleMtkWlan/SimpleMtkWlan.cpp`: `IOEthernetController` front end, work loop,
  watchdog, persistent debug log (`mtk_dbg_log` → `MtkDebugLog` property).
- `SimpleMtkWlan/MtkWlanUserClient.cpp`: ioctl-style user client for SimpleMTK.
- `SimpleMtkWlan/hal_mwx/MtkMwx.cpp`: the hardware layer (OpenBSD `mwx` port):
  DMA rings, MCU commands, firmware load, RX/TX, STA/BSS records, keys, BA.
- `SimpleMtkWlan/hal_mwx/if_mwxreg.h`: registers, MCU TLV structs and tags
  (tags follow Linux `mt76_connac_mcu.h`).
- `mtk80211/openbsd/net80211/`: 802.11 stack (state machine, EAPOL, crypto, BA
  reordering). `mtk80211/compat.cpp`: bus_dma, interrupts, timeouts glue.
- `include/FwBinary.cpp`: embedded firmware (MT7961 = MT7921/RZ608, MT7922).

## Logging and debugging

- `XYLog` / `printf` in the HAL / `MWX_DEV_LOG` all go to `mtk_dbg_log`, a ring
  buffer published as `MtkDebugLog` on the PCI provider. Read it with
  `tools/mtklog.sh`. Early boot output is otherwise lost (unified log
  overflows, `dmesg` is overwritten, kprintf goes to serial).
- **Never log per packet.** Rate-limit with a static counter like the existing
  code. Per-packet logging visibly cut throughput and evicted useful history.
- `MtkMwx::debugPoll()` runs from the watchdog every second on the main gate:
  periodic `poll`/`stats` lines, TX stall descriptor dump, automatic hard reset
  (firmware reload) if a DMA ring stops moving.
- In zsh, `log` is a builtin; use `/usr/bin/log`.

## Hardware lessons (do not regress)

- Firmware is sent in chunks of `4096 - sizeof(mwx_mcu_txd)` so each message
  fits a 4 KB cluster; 16 KB jumbo clusters are not available at boot.
- Interrupts: register the `kIOInterruptTypePCIMessaged` index; never set the
  MSI enable bit by hand. `mwx_intr` re-reads status before re-enabling.
- TX frames made of several mbufs are copied into one cluster
  (`mwx_tx_linearize`); otherwise the WFDMA stalls on the first DHCP frame.
- Group-addressed frames are not hardware-decrypted (no WTBL match,
  `wlan_idx=1023`); keys are also loaded for net80211 software CCMP. net80211
  never software-encrypts TX, so this only affects RX.
- When leaving RUN, disable the BSS and remove the peer STA record in firmware;
  reusing wcid 1 on top of the stale record breaks hardware decryption.
- Before switching APs, flush the queued deauth on the old channel.
- RSSI-triggered roaming is disabled (`ieee80211_bgscan_timeout` is a no-op);
  background scans in RUN are throttled to one per 120 s.
- MCU commands sent from RX/interrupt context (BA setup) must not wait for the
  response; the response arrives through the same interrupt path.
- Only advertise VHT to the firmware (`PHY_TYPE_BIT_VHT`) once VHT is
  negotiated. The operating width comes from the association
  (`mwx_node_chan_width`); the channel is switched to 40/80 MHz on RUN.
- Advertise HT `CBW20_40` in the HT caps even when running VHT80: APs only
  transmit 80 MHz to clients that claim 40 MHz support.
- net80211 sends AUTH/ASSOC_REQ once and waits 5 s; `debugPoll()` retransmits
  them up to 3 times. A lost association response is common on 2.4 GHz.
- Scan completions that arrive in RUN without `F_BGSCAN` are stale and must
  be ignored (they caused re-joins). Prefer 5 GHz within 15 RSSI points.
- BAR frames are not delivered by the firmware (`bar_rx=0` in the `ba` debug
  line); reorder gaps rely on the 100 ms `IEEE80211_BA_GAP_TIMEOUT`.
- A warm reboot keeps the M.2 card powered; attach recovers via WFSYS reset and
  PCIe FLR.

## Testing on hardware

The kext is injected by OpenCore (`EFI/OC/Kexts` + `Kernel → Add`), so every
test needs a reboot. On the development machine the EFI partition's disk
number changes between boots: find the 1.2 GB `EFI` partition with
`diskutil list` and verify `EFI/OC/OpenCore.efi` exists before writing to it.
Keep a known-good kext around for rollback.
