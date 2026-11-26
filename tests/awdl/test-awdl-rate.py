#!/usr/bin/env python3
"""Host ASan/UBSan tests for Connac2 AWDL unicast data rate selection & feedback ladder."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
mwx_src = (root / "SimpleMtkWlan/hal_mwx/MtkMwx.cpp").read_text()

def extract_fn(src: str, sig: str) -> str:
    idx = src.index(sig)
    start = src.rfind("\nstatic ", 0, idx)
    end = src.index("\n}\n", idx) + 3
    return src[start + 1:end]

fn_rate_val = extract_fn(mwx_src, "\nmwx_awdl_rate_val(")
fn_rate_fb = extract_fn(mwx_src, "\nmwx_awdl_rate_feedback(")

harness = r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>

#define MT_PHY_TYPE_OFDM 1
#define MT_PHY_TYPE_HT   2
#define MT_TX_RATE_MODE_SHIFT 6

static int g_knob_rate = 1;
static int g_knob_ht = 1;

static int PE_parse_boot_argn(const char *arg, void *ptr, int len)
{
    if (len < static_cast<int>(sizeof(int)) || !ptr)
        return 0;
    if (strcmp(arg, "amtk_awdl_rate") == 0 && g_knob_rate != 1) {
        *static_cast<int *>(ptr) = g_knob_rate;
        return 1;
    }
    if (strcmp(arg, "amtk_awdl_ht") == 0 && g_knob_ht != 1) {
        *static_cast<int *>(ptr) = g_knob_ht;
        return 1;
    }
    return 0;
}

struct mwx_softc {
    uint8_t sc_awdl_rate_idx = 0;
    uint16_t sc_awdl_rate_hold = 0;
    uint8_t sc_awdl_rate_acks = 0;
    uint8_t sc_awdl_rate_fails = 0;
    uint8_t sc_awdl_rate_window = 0;
};
"""

tests = r"""
static inline uint32_t expected_ofdm(uint16_t rix)
{
    return (MT_PHY_TYPE_OFDM << MT_TX_RATE_MODE_SHIFT) | rix;
}

int main()
{
    mwx_softc sc{};
    // Initial rung is 6 Mbps OFDM (rix 11).
    assert(mwx_awdl_rate_val(&sc, true) == expected_ofdm(11));

    // Climb all rungs on 5 GHz (6 -> 12 -> 24 -> 36 -> 48 -> 54 -> HT MCS7).
    const uint32_t rungs[] = {
        expected_ofdm(11), expected_ofdm(10), expected_ofdm(9),
        expected_ofdm(13), expected_ofdm(8),  expected_ofdm(12),
        (MT_PHY_TYPE_HT << MT_TX_RATE_MODE_SHIFT) | 7,
    };
    for (size_t i = 0; i < 6; ++i) {
        assert(mwx_awdl_rate_val(&sc, true) == rungs[i]);
        for (int a = 0; a < 31; ++a)
            mwx_awdl_rate_feedback(&sc, false);
        assert(sc.sc_awdl_rate_idx == i);
        mwx_awdl_rate_feedback(&sc, false);
        assert(sc.sc_awdl_rate_idx == i + 1);
    }
    assert(mwx_awdl_rate_val(&sc, true) == rungs[6]);

    // 2.4 GHz (useHt=false) must cap at 54 Mbps OFDM even if idx==6.
    assert(mwx_awdl_rate_val(&sc, false) == expected_ofdm(12));

    // amtk_awdl_ht=0 must cap 5 GHz at 54 Mbps OFDM too.
    g_knob_ht = 0;
    assert(mwx_awdl_rate_val(&sc, true) == expected_ofdm(12));
    g_knob_ht = 1;

    // amtk_awdl_rate=0 locks permanently to 6 Mbps OFDM.
    g_knob_rate = 0;
    assert(mwx_awdl_rate_val(&sc, true) == expected_ofdm(11));
    g_knob_rate = 1;

    // Unconfirmed single failure steps down immediately and arms 256-ack holdback.
    sc.sc_awdl_rate_acks = 4;
    mwx_awdl_rate_feedback(&sc, true);
    assert(sc.sc_awdl_rate_idx == 5 && sc.sc_awdl_rate_hold == 256);

    // Subsequent ACKs decrement holdback first without climbing prematurely.
    for (int a = 0; a < 256; ++a)
        mwx_awdl_rate_feedback(&sc, false);
    assert(sc.sc_awdl_rate_idx == 5 && sc.sc_awdl_rate_hold == 0);

    // Exponential backoff caps at 4096 after repeated failures.
    for (int step = 0; step < 6; ++step)
        mwx_awdl_rate_feedback(&sc, true);
    assert(sc.sc_awdl_rate_idx == 0 && sc.sc_awdl_rate_hold == 4096);

    // Null guard.
    mwx_awdl_rate_feedback(nullptr, true);

    puts("PASS: extracted AWDL Connac2 rate ladder (6..54 Mbps OFDM + HT MCS7, channel 6/HT caps, boot-args, exponential backoff) under ASan/UBSan.");
    return 0;
}
"""

with tempfile.TemporaryDirectory(prefix="mtk-awdl-rate-") as tmp:
    cpp = Path(tmp) / "test-awdl-rate.cpp"
    exe = Path(tmp) / "test-awdl-rate"
    cpp.write_text("\n".join([harness, fn_rate_val, fn_rate_fb, tests]))
    subprocess.run(
        ["clang++", "-std=c++14", "-fsanitize=address,undefined", "-g", str(cpp), "-o", str(exe)],
        check=True,
    )
    subprocess.run([str(exe)], check=True)
