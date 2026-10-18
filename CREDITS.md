<!--
  CREDITS.md
  SimpleMtkWlan

  Created by laobamac (王孝慈) on 2026/5/17.
  Copyright © 2026 laobamac (王孝慈). All rights reserved.
-->

# Credits

SimpleMtkWlan is maintained by laobamac (王孝慈).

This repository contains code from several upstream projects and systems. Their
copyright notices and license headers are intentionally preserved in source
files.

## Major Sources

- Original macOS WLAN driver framework and compatibility layer by zxystd
  (钟先耀), released under the GNU General Public License terms present in the
  source files.
- OpenBSD `net80211`, PCI, crypto, and driver support code, including work by
  OpenBSD, NetBSD, FreeBSD, and individual contributors credited in the source
  headers.
- MediaTek MT792x/OpenBSD `if_mwx` related driver code and definitions,
  including credits retained in `SimpleMtkWlan/hal_mwx/MtkMwx.cpp` and
  `SimpleMtkWlan/hal_mwx/if_mwxreg.h`.
- Firmware blobs and firmware packaging support for MediaTek MT7921 and MT7922.
- `AirportMtkWlan/` and `include/Airport/`: AirportItlwm by zxystd (钟先耀) and
  the OpenIntelWireless contributors, with laobamac's Sequoia/Tahoe (WCL) native
  Wi-Fi work (https://github.com/laobamac/itlwm, GPL-2.0), adapted to this
  driver's HAL.
- The MediaTek adaptation of that front end (AirportMtkWlan) by pengubow
  (https://github.com/pengubow/SimpleMtkWlan): WCL scan/join hooks in the HAL
  and net80211, private Wi-Fi address, Infrastructure role property fix,
  passphrase joins, command-gate sleep, link rate reporting.
- MT7921/RZ608 bring-up, 802.11n/ac, Tahoe build of AirportMtkWlan and
  integration with this hardware layer: flxxxxddd
  (https://github.com/flxxxxddd/SimpleMtkWlan).

## Current Project Work

- Project rename, packaging, and MT7921/MT7922-focused maintenance by laobamac
  (王孝慈).
- MediaTek MT7921/MT7922 attach, firmware load, DMA, scan, and TX/authentication path
  development continues in this repository.

## License Notes

The top-level project is distributed under GPLv2. Individual files may include
more specific GPL, BSD, OpenBSD, NetBSD, FreeBSD, or permissive license notices;
those notices remain authoritative for the corresponding files.
