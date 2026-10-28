#!/usr/bin/env bash
# Builds on macOS with Xcode's toolchain:
#   ./build-macos.sh [Debug|Release] [SimpleMtkWlan|AirportMtkWlan|all]
# SimpleMtkWlan: the driver with SimpleMTK / HeliPort control (the Xcode project builds it too).
# AirportMtkWlan: the same driver behind macOS's native Wi-Fi interface, from laobamac's
#                 AirportItlwm (WCL) on our MediaTek HAL. AIRPORT_OS=tahoe (default, macOS 26)
#                 or sequoia (15.2+) picks the IO80211 ABI; the kext only works on that one.
set -euo pipefail
config="${1:-Release}"
product="${2:-all}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
version="${MODULE_VERSION:-$(sed -n 's/.*MODULE_VERSION = \([0-9.]*\);.*/\1/p' "$here/SimpleMtkWlan.xcodeproj/project.pbxproj" | head -1)}"
commit="$(git -C "$here" rev-parse --short HEAD 2>/dev/null || echo unknown)"
kernelsdk="${MACKERNELSDK:-$here/MacKernelSDK}"
sdkhdr="$kernelsdk/Headers"
libkmod="$kernelsdk/Library/x86_64/libkmod.a"
clangxx="$(xcrun -f clang++)"; clang="$(xcrun -f clang)"; ld64="$(xcrun -f ld)"
otool="$(xcrun -f otool)"; nm_tool="$(xcrun -f nm)"
[[ -e "$libkmod" ]] || { echo "MacKernelSDK not found at $kernelsdk (set MACKERNELSDK)" >&2; exit 1; }
case "$config" in
	Debug)   opt=(-O0 -DDEBUG=1) ;;
	Release) opt=(-O1) ;;
	*) echo "usage: $0 [Debug|Release] [SimpleMtkWlan|AirportMtkWlan|all]" >&2; exit 2 ;;
esac
out="$here/build/$config"
mkdir -p "$out"

common_sources=(
	include/FwBinary.cpp include/HAL/MtkHalService.cpp mtk80211/compat.cpp mtk80211/zutil.c
	$(cd "$here" && ls mtk80211/openbsd/crypto/*.c)
	$(cd "$here" && ls mtk80211/openbsd/net80211/*.c mtk80211/openbsd/net80211/*.cpp)
	mtk80211/openbsd/sys/arp.c mtk80211/openbsd/sys/_ifq.cpp mtk80211/openbsd/sys/_mbuf.cpp
	mtk80211/openbsd/sys/_task.cpp
	SimpleMtkWlan/hal_mwx/MtkMwx.cpp SimpleMtkWlan/MtkLog.cpp
)

# build <name> <bundle id> <Info.plist> <extra defines...> -- <sources...>
build() {
	local name="$1" bundleid="$2" plist="$3"; shift 3
	local defines=() sources=()
	while [[ $# -gt 0 && "$1" != "--" ]]; do defines+=("$1"); shift; done
	shift
	sources=("$@")
	local obj="$out/obj-$name" bundle="$out/$name.kext"
	rm -rf "$obj" "$bundle"; mkdir -p "$obj" "$bundle/Contents/MacOS"
	local incs=(-I "$sdkhdr")
	for d in mtk80211/openbsd mtk80211 include; do incs+=(-isystem "$here/$d"); done
	while IFS= read -r d; do incs+=(-I "$d"); done < <(find "$here/SimpleMtkWlan" "$here/include" "$here/mtk80211" -type d)
	[[ -d "$here/AirportMtkWlan" ]] && incs+=(-I "$here/AirportMtkWlan")
	local flags=(
		-target x86_64-apple-macos10.12 -x c++ -std=gnu++14
		-mkernel -fapple-kext -fno-rtti -fno-exceptions -fno-builtin -fno-common -nostdlib
		-fno-use-cxa-atexit -fno-asynchronous-unwind-tables
		-DKERNEL -DIEEE80211_STA_ONLY -D__PRIVATE_SPI__ ${defines[@]+"${defines[@]}"}
		"-DSMTW_VERSION=\"$version\"" "-DGIT_COMMIT=\"$commit\"" "-DITLWM_VERSION=\"$version\""
		-include "$here/SimpleMtkWlan/PrivateSPI.pch"
		-Wno-deprecated-register -Wno-everything -Werror=return-type
	)
	local objects=() pids=() failed=0
	for src in "${sources[@]}"; do
		local o="$obj/$(echo "$src" | tr '/' '_').o"
		objects+=("$o")
		( "$clangxx" "${flags[@]}" "${opt[@]}" "${incs[@]}" -c "$here/$src" -o "$o" 2> "$o.log" || { echo "FAILED: $src" >&2; head -30 "$o.log" >&2; exit 1; } ) &
		pids+=($!)
		if (( ${#pids[@]} >= 8 )); then wait "${pids[0]}" || failed=1; pids=("${pids[@]:1}"); fi
	done
	for p in "${pids[@]}"; do wait "$p" || failed=1; done
	(( failed == 0 )) || exit 1
	cat > "$obj/kmod_info.c" <<KMOD
#include <mach/kmod.h>
extern kern_return_t _start(kmod_info_t *, void *);
extern kern_return_t _stop(kmod_info_t *, void *);
__attribute__((visibility("default"))) kmod_start_func_t *_realmain = 0;
__attribute__((visibility("default"))) kmod_stop_func_t *_antimain = 0;
__attribute__((visibility("default"))) kmod_info_t kmod_info = {
	0, KMOD_INFO_VERSION, -1U, "$bundleid", "$version", -1, 0, 0, 0, 0, _start, _stop,
};
KMOD
	"$clang" -target x86_64-apple-macos10.12 -mkernel -fno-builtin -fno-common -nostdlib -DKERNEL \
		-I "$sdkhdr" -c "$obj/kmod_info.c" -o "$obj/kmod_info.o"
	objects+=("$obj/kmod_info.o")
	"$ld64" -arch x86_64 -kext -static -macos_version_min 10.12 -undefined dynamic_lookup \
		-o "$bundle/Contents/MacOS/$name" "${objects[@]}" "$libkmod"
	python3 -I - "$here/$plist" "$bundle/Contents/Info.plist" "$version" "$name" "$bundleid" <<'PY'
import sys
src, dst, ver, name, bid = sys.argv[1:6]
s = open(src).read()
for k, v in {"$(DEVELOPMENT_LANGUAGE)": "en", "$(EXECUTABLE_NAME)": name,
             "$(PRODUCT_BUNDLE_IDENTIFIER)": bid, "$(PRODUCT_NAME)": name,
             "$(PRODUCT_BUNDLE_PACKAGE_TYPE)": "KEXT", "$(MODULE_VERSION)": ver,
             "$(CURRENT_PROJECT_VERSION)": ver}.items():
    s = s.replace(k, v)
open(dst, "w").write(s)
PY
	plutil -lint -s "$bundle/Contents/Info.plist"
	"$otool" -hv "$bundle/Contents/MacOS/$name" | grep -q KEXTBUNDLE || { echo "not a kext bundle" >&2; exit 1; }
	local syms; syms="$("$nm_tool" "$bundle/Contents/MacOS/$name")"
	for sym in _kmod_info __realmain __antimain; do grep -q " $sym\$" <<<"$syms" || { echo "missing $sym" >&2; exit 1; }; done
	echo "built $bundle (${#sources[@]} sources)"
}

if [[ "$product" == all || "$product" == SimpleMtkWlan ]]; then
	build SimpleMtkWlan com.laobamac.SimpleMtkWlan SimpleMtkWlan/Info.plist -- "${common_sources[@]}" \
		SimpleMtkWlan/MtkWlanUserClient.cpp SimpleMtkWlan/pm.cpp SimpleMtkWlan/SimpleMtkWlan.cpp
	if [[ -f "$here/mtkwifi/mtkwifi.c" ]]; then
		sdk="$(xcrun --show-sdk-path)"
		"$clang" -target x86_64-apple-macos11 -isysroot "$sdk" -O2 -Wall -framework IOKit -framework CoreFoundation \
			-o "$out/mtkwifi" "$here/mtkwifi/mtkwifi.c"
		echo "built $out/mtkwifi"
	fi
fi
if [[ "$product" == all || "$product" == AirportMtkWlan ]] && [[ -d "$here/AirportMtkWlan" ]]; then
	case "${AIRPORT_OS:-tahoe}" in
		tahoe)   target=__MAC_26_0 ;;
		sequoia) target=__MAC_15_2 ;;
		*) echo "AIRPORT_OS must be tahoe or sequoia" >&2; exit 2 ;;
	esac
	out="$here/build/$config/${AIRPORT_OS:-tahoe}"
	mkdir -p "$out"
	build AirportMtkWlan com.flxxxxddd.AirportMtkWlan AirportMtkWlan/WCL/Info.plist \
		-DAIRPORT -DAIRPORT_WCL "-D__IO80211_TARGET=$target" -DIO80211FAMILY_V2 -- "${common_sources[@]}" \
		$(cd "$here" && ls AirportMtkWlan/*.cpp AirportMtkWlan/WCL/*.cpp 2>/dev/null)
fi
