#!/usr/bin/env python3
"""Host ASan/UBSan tests for AWDL IPv6 EUI-64 link-local math and PF_ROUTE wire layout."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
cpp_src = (root / "AirportMtkWlan/MtkAwdlNeighbors.cpp").read_text()

def extract_fn(src: str, sig: str) -> str:
    idx = src.index(sig)
    end = src.index("\n}\n", idx) + 3
    return src[idx:end]

fn_write_in6 = extract_fn(cpp_src, "size_t writeIn6(")
fn_write_gw = extract_fn(cpp_src, "size_t writeLinkGateway(")

test_code = r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <net/if_dl.h>
#include <net/if_types.h>
#include <net/route.h>
#include <netinet/in.h>

#include "AirportMtkWlan/MtkAwdlNeighbors.hpp"

""" + fn_write_in6 + "\n" + fn_write_gw + r"""

int main()
{
    uint8_t ip6[16] = {};
    const uint8_t mac[6] = {0x02, 0x11, 0x22, 0x33, 0x44, 0x55};
    // KAME embedded scope ID 0x001a + EUI-64 bit invert (0x02 ^ 0x02 == 0x00).
    MtkAwdlNdp::fillEui64LinkLocal(ip6, 0x001a, mac);
    const uint8_t expected[16] = {
        0xfe, 0x80, 0x00, 0x1a, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x11, 0x22, 0xff, 0xfe, 0x33, 0x44, 0x55,
    };
    assert(memcmp(ip6, expected, 16) == 0);

    // Non-local MAC 0xaa -> 0xa8 in EUI-64 IID.
    const uint8_t mac2[6] = {0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff};
    MtkAwdlNdp::fillEui64LinkLocal(ip6, 12, mac2);
    assert(ip6[2] == 0x00 && ip6[3] == 12 && ip6[8] == 0xa8);
    assert(ip6[11] == 0xff && ip6[12] == 0xfe && ip6[15] == 0xff);

    // 4-byte PF_ROUTE alignment contract.
    assert(MtkAwdlNdp::alignRouteSockaddr(0) == 4);
    for (size_t n = 1; n <= 64; ++n) {
        size_t a = MtkAwdlNdp::alignRouteSockaddr(n);
        assert(a >= n && (a % 4) == 0 && (a - n) < 4);
    }

    // Exercise extracted writeIn6 and writeLinkGateway for prefix & host layouts.
    uint8_t prefixBuf[MtkAwdlNdp::kMaxRouteMsgBytes] = {};
    size_t off = sizeof(struct rt_msghdr);
    uint8_t prefix6[16] = {0xfe, 0x80, 0x00, 0x09};
    off += writeIn6(prefixBuf + off, prefix6);
    assert((off % 4) == 0);
    off += writeLinkGateway(prefixBuf + off, 9, "awdl0", nullptr);
    assert((off % 4) == 0);
    uint8_t mask64[16] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff};
    off += writeIn6(prefixBuf + off, mask64);
    assert(off <= MtkAwdlNdp::kMaxRouteMsgBytes);

    const auto *gwIf = reinterpret_cast<const struct sockaddr_dl *>(
        prefixBuf + sizeof(struct rt_msghdr) + MtkAwdlNdp::alignRouteSockaddr(sizeof(struct sockaddr_in6)));
    assert(gwIf->sdl_family == AF_LINK && gwIf->sdl_index == 9);
    assert(gwIf->sdl_type == IFT_ETHER && gwIf->sdl_nlen == 5 && gwIf->sdl_alen == 0);
    assert(memcmp(gwIf->sdl_data, "awdl0", 5) == 0);

    uint8_t hostBuf[MtkAwdlNdp::kMaxRouteMsgBytes] = {};
    size_t hoff = sizeof(struct rt_msghdr);
    MtkAwdlNdp::fillEui64LinkLocal(ip6, 9, mac);
    hoff += writeIn6(hostBuf + hoff, ip6);
    hoff += writeLinkGateway(hostBuf + hoff, 9, nullptr, mac);
    assert(hoff <= MtkAwdlNdp::kMaxRouteMsgBytes && (hoff % 4) == 0);

    const auto *gwMac = reinterpret_cast<const struct sockaddr_dl *>(
        hostBuf + sizeof(struct rt_msghdr) + MtkAwdlNdp::alignRouteSockaddr(sizeof(struct sockaddr_in6)));
    assert(gwMac->sdl_family == AF_LINK && gwMac->sdl_nlen == 0 && gwMac->sdl_alen == 6);
    assert(memcmp(gwMac->sdl_data, mac, 6) == 0);

    puts("PASS: extracted AWDL PF_ROUTE EUI-64 scope embedding, 4-byte alignment, and sockaddr_in6/sockaddr_dl wire layout under ASan/UBSan.");
    return 0;
}
"""

with tempfile.TemporaryDirectory(prefix="mtk-ndp-test-") as tmp:
    cpp = Path(tmp) / "test-ndp-routes.cpp"
    exe = Path(tmp) / "test-ndp-routes"
    cpp.write_text(test_code)
    subprocess.run(
        ["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", "-I", str(root), str(cpp), "-o", str(exe)],
        check=True,
    )
    subprocess.run([str(exe)], check=True)
