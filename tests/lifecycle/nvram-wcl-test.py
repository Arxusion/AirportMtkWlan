from pathlib import Path
import subprocess, tempfile

root = Path(__file__).resolve().parents[2]
code = f'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "{root / 'include/HAL/MtkNvramHelper.hpp'}"
#include "{root / 'AirportMtkWlan/WCL/WCL.hpp'}"

int main() {{
    // NVRAM ASCII trimming, band selection, and country normalization.
    assert(mtkParseBandOption(" 2\\r\\n", 4) == '2');
    assert(mtkParseBandOption("5", 1) == '5');
    assert(mtkParseBandOption("6", 1) == 0);
    assert(mtkParseBandOption(nullptr, 0) == 0);

    char cc[3] = {{0}};
    assert(mtkNormalizeCountryCode(" cn \\n", 5, cc) && strcmp(cc, "CN") == 0);
    assert(mtkNormalizeCountryCode("us", 2, cc) && strcmp(cc, "US") == 0);
    assert(mtkNormalizeCountryCode("00", 2, cc) && strcmp(cc, "00") == 0);
    assert(!mtkNormalizeCountryCode("XZ", 2, cc));
    assert(!mtkNormalizeCountryCode("xx", 2, cc));
    assert(!mtkNormalizeCountryCode("ZZ", 2, cc));
    assert(!mtkNormalizeCountryCode("U", 1, cc));

    // WCL cipher key checks: 32-byte PMK/MSK/PMKSA and 64-byte EAP MSK.
    assert(AirportWCL::validCipherKey(6, 32, 0, 0, 8));
    assert(AirportWCL::validCipherKey(7, 32, 0, 0, 0));
    assert(AirportWCL::validCipherKey(7, 64, 0, 0, 0));
    assert(AirportWCL::validCipherKey(9, 32, 0, 0, 8));
    assert(!AirportWCL::validCipherKey(6, 64, 0, 0, 0));
    assert(!AirportWCL::validCipherKey(7, 16, 0, 0, 0));
    assert(!AirportWCL::validCipherKey(7, 64, 0, 0, 9));

    // WCL join auth classification across Personal, FT, Enterprise, and WPA3-Enterprise.
    AirportWCL::JoinRequest j = {{}};
    j.lowerAuth = 1;
    j.upperAuth = (1u << 4); // FT_PSK
    j.keyLength = 10;
    memcpy(j.key, "passphrase", 10);
    assert(AirportWCL::classifyLegacyAuth(j) == AirportWCL::LegacyAuth::Personal);

    j = {{}};
    j.lowerAuth = 1;
    j.upperAuth = (1u << 7); // FT_8021X
    assert(AirportWCL::classifyLegacyAuth(j) == AirportWCL::LegacyAuth::Enterprise);

    j = {{}};
    j.lowerAuth = 1;
    j.upperAuth = (1u << 14); // WPA3_ENTERPRISE
    j.keyLength = 32;
    j.keyCipher = 6; // PMK
    assert(AirportWCL::classifyLegacyAuth(j) == AirportWCL::LegacyAuth::Enterprise);

    j = {{}};
    j.lowerAuth = 1;
    j.upperAuth = (1u << 15); // WPA3_FT_ENTERPRISE
    j.keyLength = 64;
    j.keyCipher = 7; // MSK
    assert(AirportWCL::classifyLegacyAuth(j) == AirportWCL::LegacyAuth::Enterprise);

    // decodeJoin must accept a 64-byte MSK payload inside the 0x2cc join request.
    uint8_t rawJoin[0x2cc] = {{}};
    uint32_t tmp32 = 1;
    memcpy(rawJoin + 0x10, &tmp32, 4); // lowerAuth = 1
    tmp32 = (1u << 2);
    memcpy(rawJoin + 0x14, &tmp32, 4); // upperAuth = WPA2 Enterprise
    tmp32 = 4;
    memcpy(rawJoin + 0x1c, &tmp32, 4); // ssidLength
    memcpy(rawJoin + 0x20, "Corp", 4);
    tmp32 = 64;
    memcpy(rawJoin + 0x44, &tmp32, 4); // keyLength = 64
    tmp32 = 7;
    memcpy(rawJoin + 0x48, &tmp32, 4); // keyCipher = MSK
    memset(rawJoin + 0x50, 0xab, 64);
    tmp32 = 1;
    memcpy(rawJoin + 0x214, &tmp32, 4); // candidate count
    rawJoin[0x21c] = 0x02; rawJoin[0x21d] = 0x11;
    AirportWCL::JoinRequest decoded = {{}};
    assert(AirportWCL::decodeJoin(rawJoin, sizeof(rawJoin), decoded));
    assert(decoded.keyLength == 64 && decoded.key[63] == 0xab);
    assert(AirportWCL::classifyLegacyAuth(decoded) == AirportWCL::LegacyAuth::Enterprise);

    // Selected-channel filtering stays strict for restricted 2 GHz scans.
    uint8_t chans[32] = {{}};
    chans[6 / 8] |= (1u << (6 % 8));
    assert(AirportWCL::scanChannelSelected(chans, true, 6));
    assert(!AirportWCL::scanChannelSelected(chans, true, 36));
    assert(AirportWCL::scanChannelSelected(chans, false, 36));

    puts("PASS: MtkNvramHelper + AirportWCL auth/cipher/scan unit checks.");
    return 0;
}}
'''
with tempfile.TemporaryDirectory(prefix='mtk-nvram-wcl-') as tmp:
    cpp = Path(tmp) / 'nvram-wcl-test.cpp'
    exe = Path(tmp) / 'nvram-wcl-test'
    cpp.write_text(code)
    subprocess.run(['clang++', '-std=c++14', '-Wall', '-Wextra', '-fsanitize=address,undefined', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
