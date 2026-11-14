#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="2.2.1"
kernelsdk="${MACKERNELSDK:-$here/MacKernelSDK}"
sdkhdr="$kernelsdk/Headers"
libkmod="$kernelsdk/Library/x86_64/libkmod.a"
clangxx="$(xcrun -f clang++)"
clang="$(xcrun -f clang)"
ld64="$(xcrun -f ld)"
otool="$(xcrun -f otool)"
nm_tool="$(xcrun -f nm)"
out="$here/build/Release"

mkdir -p "$out"

echo "=== Building AirportMtkBt Suite (v$version) ==="

# 1. Build AirportMtkBtFw.kext
echo "[1/2] Building AirportMtkBtFw.kext..."
fw_obj="$out/obj-AirportMtkBtFw"
fw_bundle="$out/AirportMtkBtFw.kext"
rm -rf "$fw_obj" "$fw_bundle"
mkdir -p "$fw_obj" "$fw_bundle/Contents/MacOS"

fw_sources=(
    bluetooth/AirportMtkBtFw/BtMtk.cpp
    bluetooth/AirportMtkBtFw/FwBinary.cpp
    bluetooth/AirportMtkBtFw/AirportMtkBtFw.cpp
    bluetooth/AirportMtkBtFw/USBDeviceController.cpp
    bluetooth/AirportMtkBtFw/zutil.c
)

fw_flags=(
    -target x86_64-apple-macos10.12 -x c++ -std=gnu++14
    -mkernel -fapple-kext -fno-rtti -fno-exceptions -fno-builtin -fno-common -nostdlib
    -fno-use-cxa-atexit -fno-asynchronous-unwind-tables
    -DKERNEL -D__PRIVATE_SPI__ -DMODULE_VERSION=\"$version\" -DPRODUCT_NAME=\"AirportMtkBtFw\"
    -O2 -Wno-deprecated-register -Wno-everything -Werror=return-type
)

fw_incs=(
    -I "$sdkhdr"
    -I "$here/bluetooth/AirportMtkBtFw"
)

fw_objects=()
for src in "${fw_sources[@]}"; do
    o="$fw_obj/$(basename "$src").o"
    fw_objects+=("$o")
    "$clangxx" "${fw_flags[@]}" "${fw_incs[@]}" -c "$here/$src" -o "$o"
done

cat > "$fw_obj/kmod_info.c" <<KMOD
#include <mach/kmod.h>
extern kern_return_t _start(kmod_info_t *, void *);
extern kern_return_t _stop(kmod_info_t *, void *);
__attribute__((visibility("default"))) kmod_start_func_t *_realmain = 0;
__attribute__((visibility("default"))) kmod_stop_func_t *_antimain = 0;
__attribute__((visibility("default"))) kmod_info_t kmod_info = {
    0, KMOD_INFO_VERSION, -1U, "com.arxusion.AirportMtkBtFw", "$version", -1, 0, 0, 0, 0, _start, _stop,
};
KMOD
"$clang" -target x86_64-apple-macos10.12 -mkernel -fno-builtin -fno-common -nostdlib -DKERNEL \
    -I "$sdkhdr" -c "$fw_obj/kmod_info.c" -o "$fw_obj/kmod_info.o"
fw_objects+=("$fw_obj/kmod_info.o")

"$ld64" -arch x86_64 -kext -static -macos_version_min 10.12 -undefined dynamic_lookup \
    -o "$fw_bundle/Contents/MacOS/AirportMtkBtFw" "${fw_objects[@]}" "$libkmod"

python3 -I - "$here/bluetooth/AirportMtkBtFw/Info.plist" "$fw_bundle/Contents/Info.plist" "$version" "AirportMtkBtFw" "com.arxusion.AirportMtkBtFw" <<'PY'
import sys
src, dst, ver, name, bid = sys.argv[1:6]
s = open(src).read()
for k, v in {"$(DEVELOPMENT_LANGUAGE)": "en", "$(EXECUTABLE_NAME)": name,
             "$(PRODUCT_BUNDLE_IDENTIFIER)": bid, "$(PRODUCT_NAME)": name,
             "$(PRODUCT_BUNDLE_PACKAGE_TYPE)": "KEXT", "$(MODULE_VERSION)": ver,
             "$(CURRENT_PROJECT_VERSION)": ver, "$(MARKETING_VERSION)": ver}.items():
    s = s.replace(k, v)
open(dst, "w").write(s)
PY
plutil -lint -s "$fw_bundle/Contents/Info.plist"
echo "Built $fw_bundle"

# 2. Build AirportMtkBtPatcher.kext
echo "[2/2] Building AirportMtkBtPatcher.kext..."
patch_obj="$out/obj-AirportMtkBtPatcher"
patch_bundle="$out/AirportMtkBtPatcher.kext"
rm -rf "$patch_obj" "$patch_bundle"
mkdir -p "$patch_obj" "$patch_bundle/Contents/MacOS"

patch_sources=(
    bluetooth/AirportMtkBtPatcher/plugin_start.cpp
    bluetooth/AirportMtkBtPatcher/AirportMtkBtPatcher.cpp
)

patch_flags=(
    -target x86_64-apple-macos10.12 -x c++ -std=gnu++14
    -mkernel -fapple-kext -fno-rtti -fno-exceptions -fno-builtin -fno-common -nostdlib
    -fno-use-cxa-atexit -fno-asynchronous-unwind-tables
    -DKERNEL -DMODULE_VERSION=\"$version\" -DPRODUCT_NAME=AirportMtkBtPatcher -DPRODUCT_NAME_VALUE=\"AirportMtkBtPatcher\"
    -O2 -Wno-deprecated-register -Wno-everything -Werror=return-type
)

patch_incs=(
    -I "$sdkhdr"
    -I "$here/include/Lilu"
    -I "$here/bluetooth/AirportMtkBtPatcher"
)

patch_objects=()
for src in "${patch_sources[@]}"; do
    o="$patch_obj/$(basename "$src").o"
    patch_objects+=("$o")
    "$clangxx" "${patch_flags[@]}" "${patch_incs[@]}" -c "$here/$src" -o "$o"
done

cat > "$patch_obj/kmod_info.c" <<KMOD
#include <mach/kmod.h>
extern kern_return_t AirportMtkBtPatcher_kern_start(kmod_info_t *, void *);
extern kern_return_t AirportMtkBtPatcher_kern_stop(kmod_info_t *, void *);
__attribute__((visibility("default"))) kmod_start_func_t *_realmain = AirportMtkBtPatcher_kern_start;
__attribute__((visibility("default"))) kmod_stop_func_t *_antimain = AirportMtkBtPatcher_kern_stop;
__attribute__((visibility("default"))) kmod_info_t kmod_info = {
    0, KMOD_INFO_VERSION, -1U, "com.arxusion.AirportMtkBtPatcher", "$version", -1, 0, 0, 0, 0,
    AirportMtkBtPatcher_kern_start, AirportMtkBtPatcher_kern_stop,
};
KMOD
"$clang" -target x86_64-apple-macos10.12 -mkernel -fno-builtin -fno-common -nostdlib -DKERNEL \
    -I "$sdkhdr" -c "$patch_obj/kmod_info.c" -o "$patch_obj/kmod_info.o"
patch_objects+=("$patch_obj/kmod_info.o")

"$ld64" -arch x86_64 -kext -static -macos_version_min 10.12 -undefined dynamic_lookup \
    -o "$patch_bundle/Contents/MacOS/AirportMtkBtPatcher" "${patch_objects[@]}" "$libkmod"

python3 -I - "$here/bluetooth/AirportMtkBtPatcher/Info.plist" "$patch_bundle/Contents/Info.plist" "$version" "AirportMtkBtPatcher" "com.arxusion.AirportMtkBtPatcher" <<'PY'
import sys
src, dst, ver, name, bid = sys.argv[1:6]
s = open(src).read()
for k, v in {"$(DEVELOPMENT_LANGUAGE)": "en", "$(EXECUTABLE_NAME)": name,
             "$(PRODUCT_BUNDLE_IDENTIFIER)": bid, "$(PRODUCT_NAME)": name,
             "$(PRODUCT_NAME:rfc1034identifier)": name,
             "$(PRODUCT_BUNDLE_PACKAGE_TYPE)": "KEXT", "$(MODULE_VERSION)": ver,
             "$(CURRENT_PROJECT_VERSION)": ver, "$(MARKETING_VERSION)": ver}.items():
    s = s.replace(k, v)
open(dst, "w").write(s)
PY
plutil -lint -s "$patch_bundle/Contents/Info.plist"
echo "Built $patch_bundle"

echo "=== Bluetooth Drivers Built Successfully ==="
