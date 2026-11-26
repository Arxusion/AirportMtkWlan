#!/usr/bin/env python3
"""Host ASan/UBSan tests for Phase 1 Country/11d, SCAN_SSID_LIST, and WCL auth/hotspot parsing."""
from pathlib import Path
import subprocess, tempfile

root = Path(__file__).resolve().parents[2]
src = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "AirportMtkWlan/CountryLocale.hpp"
#include "mtk80211/openbsd/net80211/ieee80211_11d.h"

namespace AirportWCL {
static constexpr size_t kChannelBitmapBits = 256;
inline uint16_t read16(const uint8_t *p) { return uint16_t(p[0]) | (uint16_t(p[1]) << 8); }
inline uint32_t read32(const uint8_t *p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) |
           (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
}
''' + "\n"

wcl_hpp = (root / "AirportMtkWlan/WCL/WCL.hpp").read_text()
start_idx = wcl_hpp.index("struct ScanSsidTargets {")
end_idx = wcl_hpp.index("inline bool validCipherKey(")
tail_idx = wcl_hpp.index("inline bool isPassphrase(")
tail_end = wcl_hpp.index("enum class LegacyAuth")
src += "namespace AirportWCL {\n" + wcl_hpp[start_idx:end_idx] + "\n" + wcl_hpp[tail_idx:tail_end] + "}\n"

src += r'''
static void put32(uint8_t *buf, size_t off, uint32_t v) {
    buf[off + 0] = v & 0xff;
    buf[off + 1] = (v >> 8) & 0xff;
    buf[off + 2] = (v >> 16) & 0xff;
    buf[off + 3] = (v >> 24) & 0xff;
}

int main() {
    // 1. IEEE 802.11d parsing and tallying
    {
        uint8_t cc[2] = {};
        uint8_t de[] = {7, 6, 'd', 'e', 36, 4, 20};
        uint8_t xx[] = {7, 6, 'X', 'X', 1, 11, 20};
        uint8_t zz[] = {7, 6, 'Z', 'Z', 1, 11, 20};
        uint8_t bad[] = {7, 1, 'U'};
        assert(ieee80211_parse_11d_country(de, cc) && cc[0] == 'D' && cc[1] == 'E');
        assert(!ieee80211_parse_11d_country(xx, cc));
        assert(!ieee80211_parse_11d_country(zz, cc));
        assert(!ieee80211_parse_11d_country(bad, cc));
        assert(!ieee80211_parse_11d_country(nullptr, cc));

        ieee80211_11d_tally table[IEEE80211_11D_MAX_SLOTS] = {};
        uint8_t bss[4][2] = {};
        const uint8_t IT[2] = {'I', 'T'}, FR[2] = {'F', 'R'};
        ieee80211_record_11d_country(table, bss[0], IT);
        ieee80211_record_11d_country(table, bss[0], IT);
        ieee80211_record_11d_country(table, bss[1], IT);
        ieee80211_record_11d_country(table, bss[2], FR);
        assert(table[0].cc[0] == 'I' && table[0].count == 2);
        // Vote moves cleanly when a BSS changes country
        ieee80211_record_11d_country(table, bss[0], FR);
        assert(table[0].count == 1 && table[1].count == 2);
    }

    // 2. Country priority & locale mapping
    {
        mtkcc::Source s = mtkcc::kFirmware;
        assert(strcmp(mtkcc::resolveCountry("US", "00", "DE", "IT", "FR", &s), "US") == 0 && s == mtkcc::kOverride);
        assert(strcmp(mtkcc::resolveCountry("", "JP", "DE", "IT", "FR", &s), "JP") == 0 && s == mtkcc::kFirmware);
        assert(strcmp(mtkcc::resolveCountry("", "00", "DE", "IT", "FR", &s), "DE") == 0 && s == mtkcc::kGeo);
        assert(strcmp(mtkcc::resolveCountry("", "00", "", "IT", "FR", &s), "IT") == 0 && s == mtkcc::kBss11d);
        assert(strcmp(mtkcc::resolveCountry("", "00", "", "", "FR", &s), "FR") == 0 && s == mtkcc::kScan11d);
        assert(mtkcc::appleLocaleForCountry("DE") == 2);
        assert(mtkcc::appleLocaleForCountry("JP") == 3);
        assert(mtkcc::appleLocaleForCountry("KR") == 4);
        assert(mtkcc::appleLocaleForCountry("US") == 1);
        assert(mtkcc::appleLocaleForCountry("00") == 1);
    }

    // 3. Tahoe SCAN_SSID_LIST decoding & Instant Hotspot / SAE passphrase handling
    {
        uint8_t req[0x1550] = {};
        put32(req, 0x40, 1); // active scan
        put32(req, 0x1c, 5);
        memcpy(req + 0x20, "iPhon", 5);
        put32(req, 0x1318, 3);
        // Entry 0: duplicate legacy SSID
        put32(req, 0x131c + 0 * 56, 1);
        put32(req, 0x131c + 0 * 56 + 4, 5);
        memcpy(req + 0x131c + 0 * 56 + 8, "iPhon", 5);
        // Entry 1: distinct SSID
        put32(req, 0x131c + 1 * 56, 1);
        put32(req, 0x131c + 1 * 56 + 4, 6);
        memcpy(req + 0x131c + 1 * 56 + 8, "Office", 6);
        // Entry 2: zeroed wildcard tail
        AirportWCL::ScanRequest out = {};
        assert(AirportWCL::decodeScan(req, sizeof(req), out));
        assert(out.targets.count == 2);
        assert(out.targets.wildcard);
        assert(memcmp(out.targets.ssids[0], "iPhon", 5) == 0);
        assert(memcmp(out.targets.ssids[1], "Office", 6) == 0);

        // Corrupt count rejected
        put32(req, 0x1318, 11);
        assert(!AirportWCL::decodeScan(req, sizeof(req), out));

        AirportWCL::JoinRequest j = {};
        j.keyCipher = 10; // APPLE80211_CIPHER_PWD
        j.keyLength = 63;
        memset(j.key, 'a', 63);
        assert(AirportWCL::isPassphrase(j));
        j.keyLength = 4; // Short SAE password with CIPHER_PWD allowed
        assert(AirportWCL::isPassphrase(j));
        j.keyCipher = 1; // Non-PWD short password rejected
        assert(!AirportWCL::isPassphrase(j));
        assert(AirportWCL::instantHotspotFlag(2) == 2);
        assert(AirportWCL::instantHotspotFlag(4) == 1);
    }

    puts("PASS: 802.11d tally, country/locale mapping, Tahoe SCAN_SSID_LIST, Instant Hotspot, and SAE cipher-10 passphrases.");
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="mtk-phase1-") as td:
    cpp = Path(td) / "phase1.cpp"
    exe = Path(td) / "phase1"
    cpp.write_text(src)
    subprocess.run(["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", "-I", str(root), str(cpp), "-o", str(exe)], check=True)
    r = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
    print(r.stdout, end="")
