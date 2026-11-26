"""Verify fixed-channel serialization and preservation of the native service TLV."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
test = r"""
#include <cassert>
#include <cstring>
#include <initializer_list>
#include <HAL/MtkAwdlAnnouncement.hpp>
#include <HAL/MtkAwdlActionFrame.hpp>
#include <HAL/MtkAwdlPeerIdentity.hpp>

int main()
{
    const uint8_t ourAddress[] = {2, 3, 4, 5, 6, 7};
    const uint8_t supplied[] = {
        18, 2, 0, 149, 124,   // Replace Tahoe's multi-channel schedule.
        4, 1, 0, 149,        // Replace Tahoe's sync data.
        6, 5, 0, 0, 0, 0, 1, 0,
        2, 3, 0, 0x12, 0x34, 0x56,
    };
    uint8_t tlvs[128], frame[256];
    size_t length = 0;
    MtkAwdl::ServiceSummary services;
    assert(MtkAwdl::buildAnnouncement(ourAddress, 36, 1, 500000, supplied,
        sizeof(supplied), tlvs, sizeof(tlvs), frame, sizeof(frame), &length, &services, true));
    assert(MtkAwdl::actionFrameLength(frame, length) == length);
    assert(services.records == 1 && frame[30] == 3 && frame[22] == 0x10);
    assert(!memcmp(frame + 10, ourAddress, 6));
    assert(frame[43] == 36 && frame[46] == 36);
    const size_t slots = 43 + 73;
    assert(frame[slots] == 18);
    for (size_t index = 0; index < 16; ++index) {
        assert(frame[slots + 9 + index * 2] == 36);
        assert(frame[slots + 10 + index * 2] == 115);
    }
    assert(!memcmp(frame + slots + 44, supplied + 9, sizeof(supplied) - 9));
    assert(length == slots + 44 + sizeof(supplied) - 9);
    for (const uint8_t channel : {uint8_t(6), uint8_t(44), uint8_t(149), uint8_t(165)}) {
        assert(MtkAwdl::buildAnnouncement(ourAddress, channel, 1, 500000, supplied,
            sizeof(supplied), tlvs, sizeof(tlvs), frame, sizeof(frame), &length, &services, true));
        assert(MtkAwdl::actionFrameLength(frame, length) == length);
        assert(frame[43] == channel && frame[46] == channel);
        for (size_t index = 0; index < 16; ++index) {
            assert(frame[slots + 9 + index * 2] == channel);
            assert(frame[slots + 10 + index * 2] == ItlAWDL::globalOperatingClass20(channel));
        }
    }
    assert(!MtkAwdl::buildAnnouncement(ourAddress, 52, 1, 500000, supplied,
        sizeof(supplied), tlvs, sizeof(tlvs), frame, sizeof(frame), &length, &services, true));
    assert(MtkAwdl::buildAnnouncement(ourAddress, 36, 2, 612640, supplied, 17,
        tlvs, sizeof(tlvs), frame, sizeof(frame), &length, &services, false));
    assert(frame[30] == 0 && !services.advertisesService());
    const uint8_t ptr[] = {3, 0, 0xc0, 7, 12, 4, 0, 0, 0, 1, 'x', 0xc0, 7};
    assert(MtkAwdl::isAirDropPtr(ptr, sizeof(ptr)));
    using MtkAwdl::PtrResult;
    assert(MtkAwdl::inspectAirDropPtr(ptr, sizeof(ptr) - 1) == PtrResult::BadLength);
    assert(MtkAwdl::inspectAirDropPtr(ptr, 6) == PtrResult::BadLength);
    const uint8_t wrongType[] = {3, 0, 0xc0, 7, 16};
    assert(MtkAwdl::inspectAirDropPtr(wrongType, sizeof(wrongType)) == PtrResult::WrongType);
    const uint8_t unknown[] = {100, 0, 0xc0, 7, 12};
    assert(MtkAwdl::inspectAirDropPtr(unknown, sizeof(unknown)) == PtrResult::UnknownLayout);
    assert(MtkAwdl::hasAirDropNameHint(unknown, sizeof(unknown)));
    const uint8_t badTarget[] = {3, 0, 0xc0, 7, 12, 4, 0, 0, 0, 1, 'x', 0xc0, 1};
    assert(MtkAwdl::inspectAirDropPtr(badTarget, sizeof(badTarget)) == PtrResult::BadTarget);
    MtkAwdl::ServiceSummary diag;
    diag.add(2, wrongType, sizeof(wrongType));
    diag.add(2, unknown, sizeof(unknown));
    diag.add(2, badTarget, sizeof(badTarget));
    assert(!diag.airDropPtrs && diag.airDropOtherTypes == 1 && diag.airDropBadTargets == 1 &&
           diag.serviceUnknownLayouts == 1 && diag.airDropOtherHints == 1);
    const uint8_t foreign[] = {3, 0, 0xc0, 1, 12, 4, 0, 0, 0, 1, 'x', 0xc0, 7};
    assert(!MtkAwdl::isAirDropPtr(foreign, sizeof(foreign)));
    const uint8_t abbreviated[] = {
        2, 11, 0, 3, 0, 0xc0, 7, 12, 2, 0, 0, 0, 1, 'x',
        2, 19, 0, 5, 0, 1, 'X', 0xc0, 7, 33, 8, 0, 0, 0,
        0, 0, 0, 0, 0x34, 0x56, 0xc0, 12
    };
    assert(MtkAwdl::buildAnnouncement(ourAddress, 36, 3, 500000, abbreviated, sizeof(abbreviated),
        tlvs, sizeof(tlvs), frame, sizeof(frame), &length, &diag, true));
    assert(diag.airDropPtrs == 1 && diag.airDropCorroborated == 1 && !diag.airDropBadTargets);
    assert(!memcmp(frame + slots + 44, abbreviated, sizeof(abbreviated)));
    assert(MtkAwdl::buildAnnouncement(ourAddress, 36, 3, 500000, abbreviated, 14,
        tlvs, sizeof(tlvs), frame, sizeof(frame), &length, &diag, true));
    assert(!diag.airDropPtrs && diag.airDropBadTargets == 1 && diag.airDropShortTargets == 1);
    assert(diag.airDropTargetBytes == 2 && diag.airDropTargetLabelBytes == 1);

    uint8_t identity[50] = {};
    const uint8_t arpa[] = {16, 7, 0, 0, 5, 'P', 'h', 'o', 'n', 'e'};
    memcpy(identity + 40, arpa, sizeof(arpa));
    assert(MtkAwdl::matchHostname(identity, sizeof(identity), "phone"));
    assert(!MtkAwdl::matchHostname(identity, sizeof(identity), "phone2"));
    assert(!MtkAwdl::matchHostname(identity, sizeof(identity), "phon"));
    assert(!MtkAwdl::matchHostname(identity, sizeof(identity) - 1, "phone"));
    assert(MtkAwdl::inspectArpaName(identity, sizeof(identity), "phone") == MtkAwdl::ArpaName::DnsLabel);
    const uint8_t nativeArpa[] = {16, 7, 0, 0, 'P', 'h', 'o', 'n', 'e', 0};
    memcpy(identity + 40, nativeArpa, sizeof(nativeArpa));
    assert(MtkAwdl::inspectArpaName(identity, sizeof(identity), "phone") == MtkAwdl::ArpaName::PlainLabel);
    assert(MtkAwdl::inspectArpaName(identity, sizeof(identity), "phon") == MtkAwdl::ArpaName::Other);
    assert(MtkAwdl::matchNativeHostname("PhOnE.LoCaL", "phone"));
    assert(!MtkAwdl::matchNativeHostname("phone2", "phone"));
    assert(!MtkAwdl::matchNativeHostname("abcdefghijklmnopqrstuvwxyzabcdef", "phone"));
    const uint8_t compressed[] = {0xc0, 9, 0xc0, 10};
    assert(MtkAwdl::localAirDropName(compressed, sizeof(compressed), false));
    uint8_t mi[] = {24, 28, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        35, 2, 0, 1, 1,
        2, 13, 0, 3, 0, 0xc0, 7, 12, 4, 0, 0, 0, 1, 'x', 0xc0, 7,
    };
    assert(MtkAwdl::inspectMasterIndication(mi, sizeof(mi), services));
    assert(services.records == 1 && services.airDrop && services.airDropPtrs == 1);
    assert(MtkAwdl::buildAnnouncement(ourAddress, 36, 3, 500000, mi, sizeof(mi),
        tlvs, sizeof(tlvs), frame, sizeof(frame), &length, &services, true));
    assert(frame[30] == 3 && services.records == 1 && services.airDrop);
    assert(!memcmp(frame + slots + 44, mi, sizeof(mi)));
    assert(!MtkAwdl::inspectMasterIndication(mi, sizeof(mi) - 1, services));
    assert(!MtkAwdl::inspectMasterIndication(mi + 31, sizeof(mi) - 31, services));
    mi[35] = 0;
    assert(MtkAwdl::inspectMasterIndication(mi, sizeof(mi) - 16, services));
    assert(!services.advertisesService());
    assert(!MtkAwdl::buildAnnouncement(ourAddress, 36, 1, 0, supplied, sizeof(supplied)-1,
        tlvs, sizeof(tlvs), frame, sizeof(frame), &length, &services, true));
    assert(!MtkAwdl::buildAnnouncement(ourAddress, 36, 1, 0, supplied, sizeof(supplied),
        tlvs, sizeof(tlvs), frame, 80, &length, &services, true));
}
"""
with tempfile.TemporaryDirectory(prefix="mtk-awdl-announcement-") as directory:
    source = Path(directory) / "test.cpp"
    binary = Path(directory) / "test"
    source.write_text(test)
    subprocess.run(["clang++", "-std=c++14", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-I", str(root / "include"),
                    str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
