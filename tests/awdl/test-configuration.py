"""Exercise the AWDL storage implementation with the actual Tahoe request structs."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
ioctl = (root / "include/Airport/apple80211_ioctl.h").read_text()
variables = (root / "include/Airport/apple80211_var.h").read_text()
structs = (
    "apple80211_awdl_sync_enabled", "apple80211_awdl_sync_frame_template",
    "apple80211_channel_sequence", "apple80211_awdl_sync_channel_sequence",
    "apple80211_awdl_sync_params", "apple80211_awdl_bssid", "apple80211_awdl_election_metric",
    "apple80211_awdl_election_id",
    "apple80211_awdl_master_channel", "apple80211_awdl_secondary_master_channel",
    "apple80211_awdl_sync_state", "apple80211_awdl_election_rssi_thresholds",
    "apple80211_awdl_min_rate",
)
definitions = "\n".join(
    re.search(r"struct " + name + r"\s*\{.*?\} __attribute__\(\(packed\)\);",
              ioctl, re.S)[0]
    for name in structs
)
defines = "\n".join(
    re.search(r"^#define\s+" + name + r"\s+\d+", ioctl + "\n" + variables, re.M)[0]
    for name in ("APPLE80211_VERSION", "APPLE80211_MAX_CHANNELS", "APPLE80211_ADDR_LEN")
)
test = r"""
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#define _APPLE80211_IOCTL_H_
""" + defines + "\n" + definitions + r"""
#include "MtkAwdlConfiguration.hpp"

int main()
{
    MtkAwdlConfiguration config;
    apple80211_awdl_sync_channel_sequence sequence = {}, reply = {};
    assert(config.readSequence(&reply) == kIOReturnNotReady);
    assert(config.readSequence(nullptr) == kIOReturnBadArgument);
    sequence.length = 16;
    sequence.encoding = 2;
    std::memset(sequence.seqs, 0x5a, sizeof(sequence.seqs));
    assert(config.setSequence(&sequence) == kIOReturnSuccess);
    sequence.length = 33;
    std::memset(sequence.seqs, 0, sizeof(sequence.seqs));
    assert(config.setSequence(&sequence) == kIOReturnBadArgument);
    assert(config.readSequence(&reply) == kIOReturnSuccess);
    assert(reply.version == 1 && reply.length == 16 && reply.encoding == 2);
    assert(reinterpret_cast<const uint8_t *>(reply.seqs)[383] == 0x5a);

    apple80211_awdl_sync_enabled sync = {};
    sync.unk1 = 99;
    assert(config.readSyncEnabled(&sync) == kIOReturnSuccess);
    assert(sync.version == 1 && sync.enabled == 0 && sync.unk1 == 0);
    sync.enabled = 1;
    assert(config.setSyncEnabled(&sync) == kIOReturnSuccess);
    sync.enabled = 2;
    assert(config.setSyncEnabled(&sync) == kIOReturnBadArgument);
    assert(config.readSyncEnabled(&sync) == kIOReturnSuccess && sync.enabled == 1);
    sync.enabled = 0;
    assert(config.setSyncEnabled(&sync) == kIOReturnSuccess);
    assert(config.readSyncEnabled(&sync) == kIOReturnSuccess && sync.enabled == 0);

    uint8_t bytes[0x724] = {42};
    apple80211_awdl_sync_frame_template frame = {0, sizeof(bytes), bytes};
    assert(config.setFrameTemplate(&frame) == kIOReturnSuccess);
    assert(config.frameTemplateLength() == sizeof(bytes));
    frame.payload_len++;
    assert(config.setFrameTemplate(&frame) == kIOReturnBadArgument);
    frame.payload = nullptr;
    frame.payload_len = 1;
    assert(config.setFrameTemplate(&frame) == kIOReturnBadArgument);
    assert(config.frameTemplateLength() == sizeof(bytes));
    frame.payload_len = 0;
    assert(config.setFrameTemplate(&frame) == kIOReturnSuccess);
    assert(config.frameTemplateLength() == 0);

    apple80211_awdl_sync_params params = {0, 16, 64, 0, 110}, readback = {};
    assert(config.syncParams.read(&readback) == kIOReturnNotReady);
    assert(config.syncParams.set(&params) == kIOReturnSuccess);
    params.version = 2;
    params.availability_window_period = 0;
    assert(config.syncParams.set(&params) == kIOReturnBadArgument);
    assert(config.syncParams.read(&readback) == kIOReturnSuccess);
    assert(readback.version == 1 && readback.availability_window_period == 64);

    apple80211_awdl_bssid bssid = {}, bssidReply = {};
    assert(config.bssid.read(&bssidReply) == kIOReturnNotReady);
    bssid.bssid[0] = 0x02;
    bssid.bssid[5] = 0x7a;
    assert(config.bssid.set(&bssid) == kIOReturnSuccess);
    bssid.version = 2;
    bssid.bssid[5] = 0;
    assert(config.bssid.set(&bssid) == kIOReturnBadArgument);
    assert(config.bssid.set(nullptr) == kIOReturnBadArgument);
    assert(config.bssid.read(&bssidReply) == kIOReturnSuccess);
    assert(bssidReply.version == 1 && bssidReply.bssid[0] == 0x02 && bssidReply.bssid[5] == 0x7a);

    apple80211_awdl_election_metric metric = {0, 0x12345678}, metricReply = {};
    assert(config.electionMetric.read(&metricReply) == kIOReturnNotReady);
    assert(config.electionMetric.set(&metric) == kIOReturnSuccess);
    metric.version = 2;
    metric.metric = 0;
    assert(config.electionMetric.set(&metric) == kIOReturnBadArgument);
    assert(config.electionMetric.read(&metricReply) == kIOReturnSuccess);
    assert(metricReply.version == 1 && metricReply.metric == 0x12345678);
    metric.version = 1;
    assert(config.electionMetric.set(&metric) == kIOReturnSuccess);
    assert(config.electionMetric.read(&metricReply) == kIOReturnSuccess);
    assert(metricReply.version == 1 && metricReply.metric == 0);

    apple80211_awdl_election_id election = {0, 0x87654321}, electionReply = {};
    assert(config.electionId.read(&electionReply) == kIOReturnNotReady);
    assert(config.electionId.set(&election) == kIOReturnSuccess);
    election.version = 2;
    election.election_id = 0;
    assert(config.electionId.set(&election) == kIOReturnBadArgument);
    assert(config.electionId.read(&electionReply) == kIOReturnSuccess);
    assert(electionReply.version == 1 && electionReply.election_id == 0x87654321);
    assert(config.electionId.read(nullptr) == kIOReturnBadArgument);

    config.addSupportedChannel(6);
    config.addSupportedChannel(44);
    config.addSupportedChannel(149);
    config.addSupportedChannel(256);
    config.addSupportedChannel(0);
    apple80211_awdl_master_channel master = {0, 6}, masterReply = {};
    assert(config.readMasterChannel(&masterReply) == kIOReturnNotReady);
    assert(config.setMasterChannel(&master) == kIOReturnSuccess);
    master.master_channel = 149;
    assert(config.setMasterChannel(&master) == kIOReturnSuccess);
    for (uint32_t bad : {0u, 13u, 256u, 0xffffffffu}) {
        master.master_channel = bad;
        assert(config.setMasterChannel(&master) == kIOReturnBadArgument);
    }
    assert(config.readMasterChannel(&masterReply) == kIOReturnSuccess);
    assert(masterReply.version == 1 && masterReply.master_channel == 149);
    master.version = 2;
    master.master_channel = 6;
    assert(config.setMasterChannel(&master) == kIOReturnBadArgument);
    assert(config.setMasterChannel(nullptr) == kIOReturnBadArgument);
    assert(config.readMasterChannel(nullptr) == kIOReturnBadArgument);
    assert(config.readMasterChannel(&masterReply) == kIOReturnSuccess && masterReply.master_channel == 149);

    apple80211_awdl_secondary_master_channel secondary = {1, 44}, secondaryReply = {};
    assert(config.readSecondaryMasterChannel(&secondaryReply) == kIOReturnNotReady);
    assert(config.setSecondaryMasterChannel(&secondary) == kIOReturnSuccess);
    secondary.secondary_master_channel = 153;
    assert(config.setSecondaryMasterChannel(&secondary) == kIOReturnBadArgument);
    assert(config.readSecondaryMasterChannel(&secondaryReply) == kIOReturnSuccess);
    assert(secondaryReply.version == 1 && secondaryReply.secondary_master_channel == 44);
    secondary.secondary_master_channel = 0;
    assert(config.setSecondaryMasterChannel(&secondary) == kIOReturnSuccess);
    assert(config.readSecondaryMasterChannel(&secondaryReply) == kIOReturnSuccess);
    assert(secondaryReply.secondary_master_channel == 0);

    apple80211_awdl_sync_state state = {}, stateReply = {};
    assert(config.readSyncState(&stateReply) == kIOReturnSuccess);
    assert(stateReply.version == 1 && stateReply.state == 1);
    state.state = 3;
    assert(config.setSyncState(&state) == kIOReturnSuccess);
    state.state = 4;
    assert(config.setSyncState(&state) == kIOReturnBadArgument);
    assert(config.readSyncState(&stateReply) == kIOReturnSuccess && stateReply.state == 3);

    apple80211_awdl_election_rssi_thresholds thresholds = {0, 1, 2, 3}, thresholdsReply = {};
    assert(config.electionRssiThresholds.set(&thresholds) == kIOReturnSuccess);
    assert(config.electionRssiThresholds.read(&thresholdsReply) == kIOReturnSuccess);
    assert(thresholdsReply.version == 1 && thresholdsReply.unk3 == 3);
    apple80211_awdl_min_rate rate = {0, 12}, rateReply = {};
    assert(config.minRate.set(&rate) == kIOReturnSuccess);
    assert(config.minRate.read(&rateReply) == kIOReturnSuccess);
    assert(rateReply.version == 1 && rateReply.min_rate == 12);
}
"""
with tempfile.TemporaryDirectory(prefix="mtk-awdl-config-") as temporary:
    directory = Path(temporary)
    (directory / "IOKit").mkdir()
    (directory / "Airport").mkdir()
    (directory / "Airport/apple80211_ioctl.h").touch()
    (directory / "IOKit/IOReturn.h").write_text(
        "#pragma once\nusing IOReturn = int;\n"
        "enum { kIOReturnSuccess, kIOReturnBadArgument, kIOReturnNotReady };\n"
    )
    source = directory / "test.cpp"
    source.write_text(test)
    binary = directory / "test"
    subprocess.run(["clang++", "-std=c++14", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-I", str(directory),
                    "-I", str(root / "AirportMtkWlan"), str(source), "-o", str(binary)],
                   check=True)
    subprocess.run([str(binary)], check=True)
