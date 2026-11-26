"""Check the AWDL RX boundary and optional FCS normalization."""
from pathlib import Path
import subprocess
import tempfile
import zlib

root = Path(__file__).resolve().parents[2]
action = bytearray(40)
action[0] = 0xd0
action[16:22] = bytes.fromhex("002500ff9473")
action[24:31] = bytes.fromhex("7f0017f2081003")
action.extend(bytes([4, 27, 0]) + bytes(27))
fcs = zlib.crc32(action).to_bytes(4, "little")
fixture = ",".join(str(value) for value in action + fcs)
test = r"""
#include <cassert>
#include <vector>
#include <HAL/MtkAwdlActionFrame.hpp>

int main()
{
    const uint8_t capture[] = {""" + fixture + r"""};
    const size_t length = sizeof(capture) - 4;
    assert(MtkAwdl::actionFrameLength(capture, sizeof(capture)) == length);
    assert(MtkAwdl::actionFrameLength(capture, length) == length);
    assert(!MtkAwdl::actionFrameLength(nullptr, length));
    assert(!MtkAwdl::actionFrameLength(capture, length - 1));
    assert(!MtkAwdl::actionFrameLength(capture, 40));

    std::vector<uint8_t> data(capture, capture + length);
    for (size_t field : {size_t(0), size_t(16), size_t(24), size_t(29)}) {
        data[field] ^= 1;
        assert(!MtkAwdl::actionFrameLength(data.data(), data.size()));
        data[field] ^= 1;
    }
    data[1] = 0x40;
    assert(!MtkAwdl::actionFrameLength(data.data(), data.size()));
    data[1] = 0;
    data[22] = 1;
    assert(!MtkAwdl::actionFrameLength(data.data(), data.size()));
    data[22] = 0;
    data[30] = 0;
    assert(MtkAwdl::actionFrameLength(data.data(), data.size()) == length);
    data[41] = 30;
    assert(!MtkAwdl::actionFrameLength(data.data(), data.size()));
    data[41] = 27;
    data.insert(data.end(), capture + 40, capture + length);
    assert(!MtkAwdl::actionFrameLength(data.data(), data.size()));
    data.resize(length);
    data[40] = 3;
    assert(!MtkAwdl::actionFrameLength(data.data(), data.size()));
    data[40] = 4;
    data.resize(MtkAwdl::maximumFrameLength + 1);
    assert(!MtkAwdl::actionFrameLength(data.data(), data.size()));

    data.assign(capture, capture + sizeof(capture));
    data.back() ^= 0x80;
    assert(!MtkAwdl::actionFrameLength(data.data(), data.size()));
}
"""
with tempfile.TemporaryDirectory(prefix="mtk-awdl-action-") as temporary:
    folder = Path(temporary)
    source = folder / "test.cpp"
    binary = folder / "test"
    source.write_text(test)
    subprocess.run(["clang++", "-std=c++14", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-I", str(root / "include"),
                    str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
