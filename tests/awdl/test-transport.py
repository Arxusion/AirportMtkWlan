"""Compile the actual d16 transport and window helpers under sanitizers."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
body = r"""
#include <cassert>
#include <cstring>
#include <HAL/MtkAwdlData.hpp>
#include <HAL/Awdl/AWDLPeerSchedule.hpp>

int main()
{
    uint8_t eth[62] = {};
    eth[0] = 0x33; eth[1] = 0x33; eth[5] = 0xfb; eth[6] = 2;
    eth[12] = 0x86; eth[13] = 0xdd;
    uint8_t *ip = eth + 14;
    ip[0] = 0x60; ip[5] = 8; ip[6] = 17; ip[7] = 255;
    ip[8] = 0xfe; ip[9] = 0x80; ip[23] = 1;
    ip[24] = 0xff; ip[25] = 2; ip[39] = 0xfb;
    ip[40] = ip[42] = 0x14; ip[41] = ip[43] = 0xe9; ip[45] = 8;

    uint8_t frame[128], copy[128];
    size_t written = 0, copied = 0;
    assert(MtkAwdl::buildData(eth, sizeof(eth), 111, frame, sizeof(frame), written));
    ItlAWDL::DataFrameView view;
    assert(ItlAWDL::parseDataFrame(frame, written, false, &view) == ItlAWDL::ParseResult::Valid);
    assert(view.wifiSequence == 111 && view.ip.bytes[46] == 0xd7 && view.ip.bytes[47] == 0x8c);
    assert(ItlAWDL::copyDataEthernet(view, copy, sizeof(copy), &copied) == ItlAWDL::BuildResult::Ready);
    assert(copied == sizeof(eth) && !memcmp(eth, copy, sizeof(eth) - 2));
    assert(!MtkAwdl::buildData(eth, sizeof(eth), 111, frame, 70, written));
    ip[45]--;
    assert(!MtkAwdl::buildData(eth, sizeof(eth), 111, frame, sizeof(frame), written));

    ItlAWDL::PeerSchedule peer = {};
    peer.assumeZero = true;
    ItlAWDL::PeerSyncInfo s = {};
    s.awPeriodTU = 16; s.downCounterTU = 64; s.channels[0] = 36; s.channels[1] = 149;
    peer.note(s, 100000, 36);
    assert(peer.inPresentAwStart(101000, 4500));
    assert(!peer.inPresentAwStart(108000, 4500));
    assert(!peer.inPresentAwStart(166000, 4500));
    assert(!peer.inPresentAwStart(2200000, 4500));
    using Update = ItlAWDL::PeerSchedule::Update;
    assert(peer.note(s, 101024, 36) == Update::Stable);
    assert(peer.phaseErrorUS == 1024 && peer.anchorEndUS == 165792);
    assert(peer.note(s, 101024 + ItlAWDL::kPeerScheduleStaleUS, 36) == Update::Gap);
    s.channels[0] = 149;
    assert(peer.note(s, 101025 + ItlAWDL::kPeerScheduleStaleUS, 36) == Update::Sequence);
    assert(peer.sequenceChanges == 1 && peer.presentEntries() == 0);
    assert(peer.note(s, 121025 + ItlAWDL::kPeerScheduleStaleUS, 36) == Update::Phase);

    ItlAWDL::PeerSchedule wrapped = {};
    s.awCounter = 65532;
    s.downCounterTU = 1;
    wrapped.note(s, 100000, 149);
    s.awCounter = 0;
    s.downCounterTU = 63;
    assert(wrapped.note(s, 102048, 149) == Update::Stable);
    assert(wrapped.phaseErrorUS == 0);

    ItlAWDL::PeerWindowEvidence history;
    for (int i = 0; i < 7; ++i) history.add(true);
    assert(!history.reliable());
    history.add(true);
    assert(history.reliable());
    for (int i = 0; i < 32; ++i) history.add(false);
    assert(history.samples == 32 && history.matches() == 0 && !history.reliable());
    for (int i = 0; i < 24; ++i) history.add(true);
    assert(history.samples == 32 && history.matches() == 24 && history.reliable());
}
"""
with tempfile.TemporaryDirectory(prefix="mtk-awdl-d16-test-") as path:
    source = Path(path, "test.cpp")
    exe = Path(path, "test")
    source.write_text(body)
    subprocess.run(["clang++", "-std=c++14", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-I", str(root / "include"),
                    str(source), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
