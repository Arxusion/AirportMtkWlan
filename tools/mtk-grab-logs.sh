#!/bin/bash
# AirportMtkWlan / SimpleMtkWlan Comprehensive Diagnostic Log Grabber
# Collects hardware, boot, OpenCore, IORegistry, MtkDebugLog, kernel, Wi-Fi
# daemon, and crash logs into a single privacy-redacted .tar.gz archive.

set -u
set -o pipefail
umask 077

TOOL_VERSION="2.1.0"
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH

SCRIPT_NAME=$(basename "$0")
MODE="full"
NO_EFI=0
QUIET=0
BUDGET_SECS=150
OUT_PATH=""
SESSION_LOG=""
FIXTURE_DIR="${MTK_DIAG_FIXTURE_DIR:-}"

usage() {
    cat <<'EOF'
Usage: mtk-grab-logs.sh [options]

Collects redacted diagnostic logs for AirportMtkWlan / SimpleMtkWlan bug reports.

Options:
  --out <path.tar.gz>     Output archive path (default: ~/Desktop/AirportMtkWlan-Logs-<ts>.tar.gz)
  --session-log <path>    Include installer/UI session log file
  --timeout <seconds>     Overall collection deadline in seconds (default: 150)
  --quick                 Fast pass (skip previous-boot log query and unmounted EFI scan)
  --no-efi                Do not mount unmounted EFI partitions (still checks mounted volumes)
  --quiet                 Minimal stdout (still prints OUTPUT <path> on success)
  -h, --help              Show this help message
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --out)
            [ "$#" -ge 2 ] || { echo "Missing argument for --out" >&2; exit 2; }
            OUT_PATH=$2; shift 2 ;;
        --session-log)
            [ "$#" -ge 2 ] || { echo "Missing argument for --session-log" >&2; exit 2; }
            SESSION_LOG=$2; shift 2 ;;
        --timeout)
            [ "$#" -ge 2 ] || { echo "Missing argument for --timeout" >&2; exit 2; }
            BUDGET_SECS=$2; shift 2 ;;
        --quick)
            MODE="quick"; shift ;;
        --no-efi)
            NO_EFI=1; shift ;;
        --quiet)
            QUIET=1; shift ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$BUDGET_SECS" in
    ''|*[!0-9]*) BUDGET_SECS=150 ;;
esac

progress() {
    if [ "$QUIET" -eq 0 ]; then
        printf 'STEP %s\n' "$1"
    fi
}

warn_msg() {
    printf 'WARN %s\n' "$1" >&2
}

resolve_target_user() {
    local u=""
    if [ -n "${MTK_TARGET_USER:-}" ]; then
        u=$MTK_TARGET_USER
    elif [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
        u=$SUDO_USER
    elif [ "$(id -u)" -eq 0 ]; then
        u=$(stat -f %Su /dev/console 2>/dev/null || true)
    else
        u=${USER:-$(id -un 2>/dev/null || true)}
    fi
    case "$u" in
        ""|root|loginwindow|_mbsetupuser) u="" ;;
    esac
    printf '%s' "$u"
}

resolve_home_for_user() {
    local u=$1 h=""
    if [ -n "$u" ]; then
        h=$(dscl . -read "/Users/$u" NFSHomeDirectory 2>/dev/null | awk '{print $2; exit}')
        [ -n "$h" ] || h="/Users/$u"
    else
        h=${HOME:-/tmp}
    fi
    printf '%s' "$h"
}

TARGET_USER=$(resolve_target_user)
TARGET_HOME=$(resolve_home_for_user "$TARGET_USER")
STAMP=$(date '+%Y%m%d-%H%M%S')

if [ -z "$OUT_PATH" ]; then
    if [ -d "$TARGET_HOME/Desktop" ] && [ -w "$TARGET_HOME/Desktop" -o "$(id -u)" -eq 0 ]; then
        OUT_PATH="$TARGET_HOME/Desktop/AirportMtkWlan-Logs-${STAMP}.tar.gz"
    else
        OUT_PATH="${TMPDIR:-/tmp}/AirportMtkWlan-Logs-${STAMP}.tar.gz"
    fi
fi

OUT_DIR=$(dirname "$OUT_PATH")
if [ ! -d "$OUT_DIR" ]; then
    mkdir -p "$OUT_DIR" || { echo "ERROR: cannot create output directory $OUT_DIR" >&2; exit 1; }
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/mtk-logs.XXXXXXXX") || { echo "ERROR: mktemp failed" >&2; exit 1; }
BUNDLE_NAME="AirportMtkWlan-Logs-${STAMP}"
ROOT_DIR="$WORK/$BUNDLE_NAME"
mkdir -p "$ROOT_DIR" "$ROOT_DIR/08-efi-opencore" "$ROOT_DIR/09-crashes-panics" || exit 1

MOUNTED_BY_US=""
DEADLINE=$(( $(date +%s) + BUDGET_SECS ))

cleanup() {
    local d
    for d in $MOUNTED_BY_US; do
        diskutil unmount "$d" >/dev/null 2>&1 || true
    done
    rm -rf "$WORK"
}
trap cleanup EXIT HUP INT TERM

bounded() {
    local secs=$1 p w rc left
    shift
    left=$(( DEADLINE - $(date +%s) ))
    if [ "$left" -lt "$secs" ]; then
        secs=$left
    fi
    if [ "$secs" -le 0 ]; then
        printf '(%s skipped: overall time budget exhausted)\n' "$1"
        return 124
    fi
    "$@" &
    p=$!
    ( sleep "$secs" >/dev/null 2>&1; kill "$p" 2>/dev/null && printf '(%s stopped after %ss timeout)\n' "$1" "$secs" ) &
    w=$!
    wait "$p"; rc=$?
    kill "$w" 2>/dev/null || true
    wait "$w" 2>/dev/null || true
    return "$rc"
}

lshow() {
    local secs=$1 p w rc left
    shift
    left=$(( DEADLINE - $(date +%s) ))
    if [ "$left" -lt "$secs" ]; then
        secs=$left
    fi
    if [ "$secs" -le 0 ]; then
        printf '(log query skipped: overall time budget exhausted)\n'
        return 124
    fi
    /usr/bin/log show "$@" &
    p=$!
    ( sleep "$secs" >/dev/null 2>&1; kill "$p" 2>/dev/null && printf '(log query stopped after %ss timeout)\n' "$secs" ) &
    w=$!
    wait "$p"; rc=$?
    kill "$w" 2>/dev/null || true
    wait "$w" 2>/dev/null || true
    return "$rc"
}

headtail() {
    awk -v h="$1" -v t="$2" '
        NR <= h { print; next }
        { r[NR % t] = $0 }
        END {
            if (NR > h) {
                s = (NR - t > h) ? NR - t + 1 : h + 1
                if (s > h + 1) printf "... %d lines omitted ...\n", s - h - 1
                for (i = s; i <= NR; i++) print r[i % t]
            }
        }'
}

squash_repeats() {
    awk '{
            l[NR] = $0
            k = $0
            gsub(/[0-9]+(\.[0-9]+)?|0x[0-9a-fA-F]+/, "#", k)
            key[NR] = k
            n[k]++
        }
        END {
            for (i = 1; i <= NR; i++) {
                k = key[i]
                seen[k]++
                if (n[k] <= 300 || seen[k] <= 30 || seen[k] > n[k] - 30) {
                    print l[i]
                } else if (seen[k] == 31) {
                    printf "... %d similar lines omitted: %s\n", n[k] - 60, substr(l[i], 1, 100)
                }
            }
        }'
}

HOST_SHORT=$(hostname -s 2>/dev/null || true)
HOST_FQDN=$(hostname 2>/dev/null || true)

# Privacy redactor applied to every collected text/json/plist file before archiving.
redact_file_inplace() {
    local f=$1
    [ -f "$f" ] && [ ! -L "$f" ] || return 0
    [ -s "$f" ] || return 0
    MTK_REDACT_USER="$TARGET_USER" \
    MTK_REDACT_CUR_USER="${USER:-}" \
    MTK_REDACT_HOST="$HOST_SHORT" \
    MTK_REDACT_FQDN="$HOST_FQDN" \
    /usr/bin/perl -i -e '
        use strict;
        use warnings;

        my $in = do { local $/; <> };
        exit 0 unless defined $in;

        my @users = grep { defined && length($_) >= 3 && $_ ne "root" && $_ ne "staff" && $_ ne "wheel" && $_ ne "admin" }
                    ($ENV{MTK_REDACT_USER} // "", $ENV{MTK_REDACT_CUR_USER} // "");
        my %seen_u;
        @users = grep { !$seen_u{$_}++ } @users;

        for my $u (@users) {
            $in =~ s{/Users/\Q$u\E(?=/|\b)}{/Users/<USER>}g;
            if (length($u) >= 4) {
                $in =~ s{\b\Q$u\E\b}{<USER>}g;
            }
        }

        for my $h ($ENV{MTK_REDACT_FQDN} // "", $ENV{MTK_REDACT_HOST} // "") {
            next unless length($h) >= 3 && $h ne "localhost";
            $in =~ s{\b\Q$h\E\b}{<HOST>}g;
        }

        # 1. AirportMtkWlan / SimpleMtkWlan key, EAPOL, and passphrase dumps
        $in =~ s{(Set key request:[^\r\n]*?\bkey=)[0-9a-fA-F]{6,}}{$1<KEY_REDACTED>}gi;
        $in =~ s{(Set key request:[^\r\n]*?\brsc=)[0-9a-fA-F]{4,}}{$1<RSC_REDACTED>}gi;
        $in =~ s{(PSK key check\s+)[0-9a-fA-F]{2,}}{$1<REDACTED>}gi;
        $in =~ s{(input EAPOL packet,[^\r\n]*?\bdata:\s*)[0-9a-fA-F :]+}{$1<EAPOL_HEX_REDACTED>}gi;
        $in =~ s{\b((?:passphrase|password|psk|pmk|msk|wep[_-]?key|shared[_-]?secret|wpa[_-]?key|auth[_-]?secret|Passphrase)\s*[:=]\s*)(?:"[^"]*"|\x27[^\x27]*\x27|[^\s,;)]+)}{$1<SECRET_REDACTED>}gi;
        $in =~ s{("(?:Passphrase|Password|PSK|PMK|MSK|WEPKey|EAPPassword)"\s*=\s*)(?:<[^>]*>|"[^"]*")}{$1<SECRET_REDACTED>}gi;

        # 2. Hardware serials, UUIDs, MLB, ROM, and crash telemetry identifiers
        $in =~ s{("(?:IOPlatformSerialNumber|IOPlatformUUID|SystemSerialNumber|BoardSerialNumber|SerialNumber|MLB|ROM|SystemUUID)"\s*=\s*)(?:"[^"]*"|<[^>]*>)}{$1<ID_REDACTED>}gi;
        $in =~ s{(<key>(?:SystemSerialNumber|MLB|SystemUUID|ROM|BoardSerialNumber|PlatformUUID|SmUUID)</key>\s*<string>)[^<]*(</string>)}{$1<ID_REDACTED>$2}gi;
        $in =~ s{(<key>ROM</key>\s*<data>)[A-Za-z0-9+/=\s]+(</data>)}{$1PElEX1JFREFDVEVEPg==$2}gi;
        $in =~ s{("(?:crashReporterKey|deviceIdentifierForVendor|sessionID|userID|incident|bootSessionUUID|sleepWakeUUID|serial[A-Za-z]*)"\s*:\s*)"[^"]*"}{$1"<ID_REDACTED>"}gi;

        # 3. SSIDs & neighboring Wi-Fi scan leak protection
        $in =~ s{(Current Wi-Fi Network:\s*).+}{$1<SSID_REDACTED>}gi;
        $in =~ s{(\b(?:SSID|ssid|nwid|networkName|Network Name|nwName)\s*[:=]\s*)"[^"]*"}{$1"<SSID_REDACTED>"}gi;
        $in =~ s{(\b(?:SSID|ssid|nwid)\s*[:=]\s*)\x27[^\x27]*\x27}{$1\x27<SSID_REDACTED>\x27}gi;
        $in =~ s{^(\s*(?:SSID|Network Name)\s*:\s*).+$}{$1<SSID_REDACTED>}gim;
        # Redact Current Network Name heading inside system_profiler SPAirPortDataType
        $in =~ s{(^\s*Current Network Information:\s*\r?\n)(\s*)([^\r\n:]+):(\s*\r?\n)}{$1$2<SSID_REDACTED>:$4}gm;
        # Replace Other Local Wi-Fi Networks block in SPAirPortDataType (prevents WiGLE geolocation)
        $in =~ s{(^\s*Other Local Wi-Fi Networks:\s*\r?\n)(.*?)(?=\r?\n\s{4,10}(?:awdl\d*|en\d*|p2p\d*):|\r?\n\s*Peer-to-Peer|\Z)}{
            my ($hdr, $body) = ($1, $2);
            my $count = () = ($body =~ m{^\s{12,}[^:\s][^:\r\n]*:\s*$}mg);
            $count ||= () = ($body =~ m{PHY Mode:}mg);
            "$hdr              <NEARBY_NETWORKS_REDACTED count=$count>"
        }gmes;

        # 4. 6-octet MAC / BSSID addresses (preserve OUI + broadcast/zero, hide unique host suffix)
        $in =~ s{(?<![0-9a-fA-F:])([0-9a-fA-F]{2}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})(?![0-9a-fA-F:])}{
            my ($a,$b,$c,$d,$e,$f) = ($1,$2,$3,$4,$5,$6);
            my $full = lc("$a:$b:$c:$d:$e:$f");
            ($full eq "ff:ff:ff:ff:ff:ff" || $full eq "00:00:00:00:00:00")
                ? "$a:$b:$c:$d:$e:$f"
                : lc("$a:$b:$c") . ":XX:XX:XX"
        }ge;
        $in =~ s{(?<![0-9a-fA-F-])([0-9a-fA-F]{2})-([0-9a-fA-F]{2})-([0-9a-fA-F]{2})-([0-9a-fA-F]{2})-([0-9a-fA-F]{2})-([0-9a-fA-F]{2})(?![0-9a-fA-F-])}{
            my ($a,$b,$c,$d,$e,$f) = ($1,$2,$3,$4,$5,$6);
            my $full = lc("$a-$b-$c-$d-$e-$f");
            ($full eq "ff-ff-ff-ff-ff-ff" || $full eq "00-00-00-00-00-00")
                ? "$a-$b-$c-$d-$e-$f"
                : lc("$a-$b-$c") . "-XX-XX-XX"
        }ge;

        # 5. IPv4 / IPv6 addresses & domain names anchored to network output fields
        $in =~ s{(\b(?:inet|broadcast|router|server_identifier|yiaddr|ciaddr|siaddr|giaddr|nameserver(?:\[[0-9]+\])?|address #[0-9]+|IPv4\.Addresses|IPv4 address|subnet_mask)\s*[:=]?\s*)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})}{
            my ($pfx, $ip) = ($1, $2);
            if ($ip eq "127.0.0.1" || $ip eq "0.0.0.0" || $ip =~ m{^255\.}) {
                "$pfx$ip";
            } elsif ($ip =~ m{^169\.254\.}) {
                "${pfx}169.254.<LINK_LOCAL>";
            } elsif ($ip =~ m{^(?:192\.168\.|10\.|172\.(?:1[6-9]|2\d|3[01])\.)}) {
                "${pfx}<RFC1918_LAN_IP>";
            } else {
                "${pfx}<IPv4_REDACTED>";
            }
        }ge;
        $in =~ s{(\binet6\s+)([0-9a-fA-F:]+)(%[A-Za-z0-9_.-]+)?}{
            my ($pfx, $ip, $zone) = ($1, $2, $3 // "");
            if ($ip eq "::1") {
                "${pfx}::1$zone";
            } elsif ($ip =~ m{^fe80:}i) {
                "${pfx}fe80::<LINK_LOCAL_V6>$zone";
            } else {
                "${pfx}<IPv6_REDACTED>$zone";
            }
        }ge;
        $in =~ s{^(\s*domain_name\s*\([^)]+\)\s*:\s*).+$}{$1<DOMAIN_REDACTED>}gim;

        print $in;
    ' "$f" || warn_msg "redaction failed for $(basename "$f")"
}

sanitize_config_plist() {
    local src=$1 dst=$2 tmp
    [ -f "$src" ] || return 1
    tmp="$WORK/cfg_tmp.plist"
    cp "$src" "$tmp" || return 1
    for k in \
        PlatformInfo.Generic.SystemSerialNumber \
        PlatformInfo.Generic.MLB \
        PlatformInfo.Generic.SystemUUID \
        PlatformInfo.Generic.ROM \
        PlatformInfo.SMBIOS.SystemSerialNumber \
        PlatformInfo.SMBIOS.BoardSerialNumber \
        PlatformInfo.SMBIOS.PlatformUUID \
        PlatformInfo.DataHub.SystemSerialNumber \
        PlatformInfo.DataHub.SystemUUID \
        NVRAM.Add.4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102.mlb; do
        plutil -remove "$k" "$tmp" >/dev/null 2>&1 || true
    done
    plutil -convert xml1 -o "$dst" "$tmp" 2>/dev/null || cp "$tmp" "$dst"
    rm -f "$tmp"
    redact_file_inplace "$dst"
}

run_or_fixture() {
    local fx_file=$1
    shift
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/$fx_file" ]; then
        cat "$FIXTURE_DIR/$fx_file"
    elif [ -n "$FIXTURE_DIR" ]; then
        return 1
    else
        "$@"
    fi
}

boot_ocrel() {
    local bp p
    bp=$(nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:boot-path 2>/dev/null | cut -f2- || true)
    case "$bp" in *\)*) ;; *) return 0 ;; esac
    p=${bp##*\)}
    p=${p%%\%*}
    p=$(printf '%s' "$p" | tr '\\' '/')
    while [ "${p#/}" != "$p" ]; do p=${p#/}; done
    case "$p" in */*) p=${p%/*} ;; *) return 0 ;; esac
    case "/$p/" in /EFI/*/) ;; *) return 0 ;; esac
    case "/$p/" in */../*|*/./*|*//*) return 0 ;; esac
    printf '%s\n' "$p"
}

booted_part() {
    local bp u d
    bp=$(nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:boot-path 2>/dev/null | cut -f2- || true)
    u=$(printf '%s' "$bp" | grep -oiE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -n 1 || true)
    [ -n "$u" ] || return 1
    for d in $(diskutil list 2>/dev/null | grep -oE 'disk[0-9]+s[0-9]+$' | sort -u); do
        if diskutil info "$d" 2>/dev/null | grep -qi "Partition UUID: *$u"; then
            echo "$d"
            return 0
        fi
    done
    return 1
}

# --- Section 1: System, Boot, Kernel Extensions ---
progress "Collecting system, boot, and kext state..."
OS_VER=$(sw_vers -productVersion 2>/dev/null || echo "unknown")
OS_BUILD=$(sw_vers -buildVersion 2>/dev/null || echo "unknown")
HW_MODEL=$(sysctl -n hw.model 2>/dev/null || echo "unknown")
CPU_BRAND=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "unknown")
ARCH_NAME=$(uname -m 2>/dev/null || echo "unknown")
BOOT_SEC=$(sysctl -n kern.boottime 2>/dev/null | sed -E 's/.*sec = ([0-9]+),.*/\1/' || true)
SCOPE="user"
[ "$(id -u)" -eq 0 ] && SCOPE="root"

KMUTIL_LOADED=$(run_or_fixture "kmutil.txt" bounded 25 kmutil showloaded --list-only 2>&1 || true)
if [ -z "$KMUTIL_LOADED" ] || ! printf '%s\n' "$KMUTIL_LOADED" | grep -q 'com\.'; then
    KMUTIL_KEXTSTAT=$(run_or_fixture "kmutil.txt" bounded 20 kextstat -l 2>&1 || true)
    [ -n "$KMUTIL_KEXTSTAT" ] && KMUTIL_LOADED="$KMUTIL_KEXTSTAT"
fi

{
    echo "=== AirportMtkWlan System & Boot Report ==="
    echo "Timestamp (UTC): $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "Grabber Version: $TOOL_VERSION   Scope: $SCOPE   Mode: $MODE"
    echo "macOS: $OS_VER ($OS_BUILD)   Arch: $ARCH_NAME"
    echo "Model: $HW_MODEL"
    echo "uname: $(uname -a 2>/dev/null || true)"
    echo
    echo "== CPU & Memory"
    sysctl kern.boottime machdep.cpu.vendor machdep.cpu.brand_string machdep.cpu.family \
        machdep.cpu.model machdep.cpu.stepping hw.physicalcpu hw.logicalcpu hw.memsize 2>&1 || true
    echo
    echo "== SIP & Boot Arguments"
    csrutil status 2>&1 || true
    echo "boot-args: $(nvram boot-args 2>/dev/null | cut -f2- || echo '(not set)')"
    echo "csr-active-config: $(nvram 7C436110-AB2A-4BBB-A880-FE41995C9F82:csr-active-config 2>/dev/null | cut -f2- || echo '(not set)')"
    echo "opencore-version: $(nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:opencore-version 2>/dev/null | cut -f2- || echo '(absent)')"
    echo "opencore-boot-path: $(nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:boot-path 2>/dev/null | cut -f2- || echo '(absent)')"
    echo
    echo "== IOMMU / AppleVTD"
    bounded 10 ioreg -r -c AppleVTD -d 1 2>&1 | head -n 40 || true
    echo
    echo "== Loaded Wi-Fi, Network, OpenCore & Support Kexts"
    printf '%s\n' "$KMUTIL_LOADED" | grep -iE 'mtk|airport|itlwm|80211|skywalk|lilu|amfi|restrict|virtualsmc|smc|whatevergreen|bluetool|brcm|usb|ethernet|pci|vtd' || echo "(no matching loaded kexts)"
    echo
    echo "== /Library/Extensions Conflict Check (AuxKC vs OpenCore)"
    ls -la /Library/Extensions 2>&1 | grep -iE 'total|mtk|airport|itlwm|brcm|80211' || echo "(no Wi-Fi kexts in /Library/Extensions)"
    if [ -f /Library/KernelCollections/AuxiliaryKernelExtensions.kc ]; then
        bounded 20 kmutil inspect -a x86_64 -A /Library/KernelCollections/AuxiliaryKernelExtensions.kc 2>&1 | grep -iE 'mtk|airport|itlwm' || echo "(no MediaTek kext in AuxKC)"
    else
        echo "(AuxiliaryKernelExtensions.kc not present)"
    fi
} > "$ROOT_DIR/01-system-boot.txt" 2>&1
redact_file_inplace "$ROOT_DIR/01-system-boot.txt"

# --- Section 2: Hardware PCI / USB / IORegistry Tree ---
progress "Collecting PCI, USB, and IORegistry Wi-Fi tree..."
IOREG_ALL=$(run_or_fixture "ioreg.txt" bounded 25 ioreg -l -w0 2>&1 || true)
IOREG_PCI=$(run_or_fixture "ioreg_pci.txt" bounded 25 ioreg -r -c IOPCIDevice -l -w0 2>&1 || true)
[ -n "$IOREG_PCI" ] || IOREG_PCI="$IOREG_ALL"

{
    echo "=== MediaTek & Network PCI Devices ==="
    printf '%s\n' "$IOREG_PCI" | awk '
        function flush() { if (match_dev) print block "\n" }
        /\+-o / { flush(); block=$0; match_dev=0; next }
        /"vendor-id" = <c3140000>/ { match_dev=1 }
        /"IOName" = "pci14c3,/ { match_dev=1 }
        /"class-code" = <00(80|00)0200>/ { match_dev=1 }
        /"(IOClass|IOName|compatible|vendor-id|device-id|subsystem-vendor-id|subsystem-id|revision-id|class-code|pcidebug|acpi-path|built-in|IOPCIExpressLinkCapabilities|IOPCIExpressLinkStatus|IOPCIExpressCapabilities|Capability Offsets|IOPCIMSIMode|IOPCIMSIMessageControl|IOPowerManagement|IOPCIL1PMCapabilities|IOPCIResourced|IODeviceMemory|assigned-addresses|reg)"/ {
            block = block "\n" $0
        }
        END { flush() }'
    echo
    echo "=== IORegistry Class Counts ==="
    for cls in SimpleMtkWlan AirportItlwm AirportItlwmSkywalkInterface AirportItlwmEthernetInterface IOPCIEDeviceWrapper IO80211Controller IO80211InfraInterface Apple80211; do
        printf '%-34s %s\n' "$cls" "$(ioclasscount "$cls" 2>/dev/null || echo '?')"
    done
    echo
    echo "=== Driver & IO80211 Registry Objects ==="
    for cls in AirportItlwm SimpleMtkWlan IOPCIEDeviceWrapper IO80211Controller IO80211InfraInterface IO80211Interface; do
        echo "-- class: $cls"
        bounded 10 ioreg -r -c "$cls" -l -w0 2>&1 | grep -v '"MtkDebugLog"' | head -n 120 || true
    done
    echo
    echo "=== USB MediaTek / Bluetooth Combo Check ==="
    bounded 15 ioreg -p IOUSB -l -w0 2>&1 | awk '
        /\+-o / { block=$0; keep=0; next }
        /(MediaTek|MTK|MT79|RZ6|0x0e8d|idVendor.*3725|14c3|Bluetooth)/ { keep=1 }
        /"(USB Product Name|USB Vendor Name|idVendor|idProduct|bcdDevice|locationID|sessionID|kUSBVendorString|kUSBProductString)"/ { block = block "\n" $0 }
        /^ *\}$/ { if (keep) print block "\n"; keep=0 }'
    echo
    echo "=== SPPCIDataType (Network/Wireless Cards) ==="
    bounded 20 system_profiler SPPCIDataType 2>&1 | grep -B2 -A12 -iE 'Wi-Fi|Wireless|Network|Ethernet|MediaTek|14c3|Airport' || true
} > "$ROOT_DIR/02-hardware-pci-ioreg.txt" 2>&1
redact_file_inplace "$ROOT_DIR/02-hardware-pci-ioreg.txt"

# --- Section 3: Persistent Driver Ring Buffer (MtkDebugLog) ---
progress "Collecting MtkDebugLog ring buffer..."
{
    echo "=== MtkDebugLog Ring Buffer ==="
    MTK_DBG=$(printf '%s\n' "$IOREG_PCI" | awk '/"MtkDebugLog" = "/{f=1} f{ if (n++ && /^ *"[A-Za-z0-9_-]+" = /) exit; print }')
    if [ -n "$MTK_DBG" ]; then
        printf '%s\n' "$MTK_DBG"
    else
        echo "(MtkDebugLog property not found in IOPCIDevice registry)"
    fi
} > "$ROOT_DIR/03-mtk-debug-log.txt" 2>&1
redact_file_inplace "$ROOT_DIR/03-mtk-debug-log.txt"

# --- Section 4: Network & macOS Wi-Fi Stack State ---
progress "Collecting network interfaces and Wi-Fi stack state..."
HW_PORTS=$(run_or_fixture "networksetup_ports.txt" bounded 15 networksetup -listallhardwareports 2>&1 || true)
WIFI_IFACES=$(printf '%s\n' "$HW_PORTS" | awk '/Hardware Port: Wi-Fi/{getline; if ($1 == "Device:") print $2}')

{
    echo "=== Hardware Ports ==="
    printf '%s\n' "$HW_PORTS"
    echo
    echo "=== Detected Wi-Fi Interface(s): ${WIFI_IFACES:-none} ==="
    for iface in ${WIFI_IFACES:-en0 en1 en2}; do
        echo "-- Interface: $iface"
        run_or_fixture "networksetup_power.txt" networksetup -getairportpower "$iface" 2>&1 || true
        run_or_fixture "networksetup_net.txt" networksetup -getairportnetwork "$iface" 2>&1 || true
        if [ -z "$FIXTURE_DIR" ]; then
            ipconfig getpacket "$iface" 2>&1 || true
        fi
    done
    echo
    echo "=== ifconfig -a ==="
    run_or_fixture "ifconfig.txt" bounded 10 ifconfig -a 2>&1 || true
    echo
    echo "=== scutil --nwi ==="
    if [ -z "$FIXTURE_DIR" ]; then
        bounded 10 scutil --nwi 2>&1 || true
    fi
    echo
    echo "=== system_profiler SPAirPortDataType ==="
    run_or_fixture "airport_sp.txt" bounded 25 system_profiler SPAirPortDataType 2>&1 || true
    echo
    echo "=== wdutil info ==="
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/wdutil.txt" ]; then
        cat "$FIXTURE_DIR/wdutil.txt"
    elif [ "$(id -u)" -eq 0 ] && command -v wdutil >/dev/null 2>&1; then
        bounded 15 wdutil info 2>&1 || true
    else
        echo "(skipped: wdutil info requires administrator privileges; use Full Logs mode)"
    fi
} > "$ROOT_DIR/04-network-wifi-state.txt" 2>&1
redact_file_inplace "$ROOT_DIR/04-network-wifi-state.txt"

# --- Section 5: Kernel Logs (Current Boot + dmesg) ---
progress "Collecting kernel Wi-Fi and driver logs..."
{
    echo "=== Kernel Log Since Boot ==="
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/kernel_log.txt" ]; then
        cat "$FIXTURE_DIR/kernel_log.txt"
    elif [ -n "$FIXTURE_DIR" ]; then
        echo "(no fixture kernel log)"
    else
        PRED_KERNEL='process == "kernel" AND (eventMessage CONTAINS[c] "mtk" OR eventMessage CONTAINS[c] "mwx" OR eventMessage CONTAINS[c] "AirportMtk" OR eventMessage CONTAINS[c] "SimpleMtk" OR eventMessage CONTAINS[c] "AirportItlwm" OR eventMessage CONTAINS[c] "itlwm" OR eventMessage CONTAINS[c] "80211" OR eventMessage CONTAINS[c] "WCL" OR eventMessage CONTAINS[c] "Skywalk" OR sender CONTAINS[c] "Mtk" OR sender CONTAINS[c] "80211" OR sender CONTAINS[c] "Skywalk")'
        if [ -n "$BOOT_SEC" ]; then
            rc=0
            lshow 25 --start "$(date -r "$BOOT_SEC" '+%Y-%m-%d %H:%M:%S')" --style compact --predicate "$PRED_KERNEL" 2>&1 || rc=$?
            if [ "$rc" -eq 124 ] || [ "$rc" -eq 143 ]; then
                echo "(retrying with --last boot due to clock jump / timeout)"
                lshow 20 --last boot --style compact --predicate "$PRED_KERNEL" 2>&1 || true
            fi
        else
            lshow 25 --last 30m --style compact --predicate "$PRED_KERNEL" 2>&1 || true
        fi
    fi
} | squash_repeats | headtail 1500 1500 > "$ROOT_DIR/05-kernel-log-boot.txt" 2>&1

{
    echo
    echo "=== Kernel Ring Buffer (dmesg) ==="
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/dmesg.txt" ]; then
        grep -iE 'mtk|mwx|airport|itlwm|80211|skywalk|wcl|vtd|iommu|pcie|pci14c3' "$FIXTURE_DIR/dmesg.txt" || tail -n 200 "$FIXTURE_DIR/dmesg.txt"
    elif [ "$(id -u)" -eq 0 ]; then
        bounded 15 dmesg 2>&1 | grep -iE 'mtk|mwx|airport|itlwm|80211|skywalk|wcl|vtd|iommu|pcie|pci14c3|firmware' | headtail 400 400 || true
    else
        echo "(not readable as non-root user; run Full Logs mode to include dmesg)"
    fi
} >> "$ROOT_DIR/05-kernel-log-boot.txt" 2>&1
redact_file_inplace "$ROOT_DIR/05-kernel-log-boot.txt"

# --- Section 6: macOS Wi-Fi Daemon & KernelManager Logs ---
progress "Collecting airportd, WiFiAgent, and kernelmanagerd logs..."
{
    echo "=== Wi-Fi Userspace Daemons & Kext Manager (last 30m) ==="
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/wifi_log.txt" ]; then
        cat "$FIXTURE_DIR/wifi_log.txt"
    elif [ -n "$FIXTURE_DIR" ]; then
        echo "(no fixture wifi_log)"
    else
        lshow 25 --last 30m --style compact --predicate \
            'process == "airportd" OR process == "WiFiAgent" OR process == "wifip2pd" OR process == "wifivelocityd" OR subsystem == "com.apple.wifi" OR (process == "kernelmanagerd" AND (eventMessage CONTAINS[c] "mtk" OR eventMessage CONTAINS[c] "airport" OR eventMessage CONTAINS[c] "80211"))' \
            2>&1 | squash_repeats | headtail 1200 1200 || true
    fi
} > "$ROOT_DIR/06-wifi-userspace-logs.txt" 2>&1
redact_file_inplace "$ROOT_DIR/06-wifi-userspace-logs.txt"

# --- Section 7: Previous Boot Kernel Log (Full Mode + Root) ---
if [ "$MODE" = "full" ] && [ -z "$FIXTURE_DIR" ]; then
    progress "Collecting previous-boot kernel logs..."
    {
        if [ "$(id -u)" -eq 0 ] && [ -n "$BOOT_SEC" ]; then
            echo "=== Previous Boot Kernel Log (before $(date -r "$BOOT_SEC" '+%Y-%m-%d %H:%M:%S')) ==="
            lshow 25 --start "$(date -r $((BOOT_SEC - 43200)) '+%Y-%m-%d %H:%M:%S')" \
                     --end "$(date -r "$BOOT_SEC" '+%Y-%m-%d %H:%M:%S')" \
                     --style compact --predicate 'process == "kernel" AND (eventMessage CONTAINS[c] "mtk" OR eventMessage CONTAINS[c] "mwx" OR eventMessage CONTAINS[c] "airport" OR eventMessage CONTAINS[c] "itlwm" OR eventMessage CONTAINS[c] "80211" OR eventMessage CONTAINS[c] "skywalk" OR eventMessage CONTAINS[c] "panic")' 2>&1 \
                | head -n 3000 || true
        else
            echo "(skipped: previous-boot query requires Full Logs with administrator privileges)"
        fi
    } > "$ROOT_DIR/07-previous-boot-kernel-log.txt" 2>&1
    redact_file_inplace "$ROOT_DIR/07-previous-boot-kernel-log.txt"
fi

# --- Section 8: OpenCore EFI Config & Logs ---
progress "Inspecting OpenCore config and kext inventory..."
{
    echo "=== OpenCore EFI Scan ==="
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/config.plist" ]; then
        echo "fixture: config.plist sanitized"
        sanitize_config_plist "$FIXTURE_DIR/config.plist" "$ROOT_DIR/08-efi-opencore/fixture-config.plist.xml" || warn_msg "failed to sanitize fixture config.plist"
    elif [ "$NO_EFI" -eq 1 ]; then
        echo "(skipped: --no-efi passed)"
    else
        # Always check already-mounted EFI/OC folders safely (read-only)
        found_oc=0
        for vol in /Volumes/*; do
            [ -d "$vol" ] || continue
            for cand in "$vol/EFI/OC" "$vol/OC"; do
                [ -f "$cand/config.plist" ] || continue
                found_oc=1
                safe_v=$(printf '%s' "$(basename "$vol")" | tr -c 'A-Za-z0-9._-' '_')
                echo "mounted: $cand (volume=$safe_v)"
                if [ -r "$cand/config.plist" ]; then
                    sanitize_config_plist "$cand/config.plist" "$ROOT_DIR/08-efi-opencore/${safe_v}-config.plist.xml" || true
                else
                    echo "  (config.plist unreadable without admin privileges)"
                fi
                if [ -d "$cand/Kexts" ]; then
                    echo "  Kexts/ listing:"
                    ls -la "$cand/Kexts" 2>/dev/null | sed 's/^/    /'
                    for k in AirportMtkWlan.kext SimpleMtkWlan.kext itlwm.kext; do
                        if [ -d "$cand/Kexts/$k" ]; then
                            ver=$(plutil -extract CFBundleShortVersionString raw -o - "$cand/Kexts/$k/Contents/Info.plist" 2>/dev/null || echo "?")
                            bin="$cand/Kexts/$k/Contents/MacOS/${k%.kext}"
                            sha=$([ -f "$bin" ] && shasum -a 256 "$bin" 2>/dev/null | awk '{print $1}' || echo "?")
                            echo "  -> $k version=$ver sha256=$sha"
                        fi
                    done
                fi
            done
        done
        # If running as root without --no-efi and not in quick mode, check OpenCore boot-path ESP if unmounted
        if [ "$NO_EFI" -eq 0 ] && [ "$MODE" = "full" ] && [ "$(id -u)" -eq 0 ]; then
            bpart=$(booted_part || true)
            if [ -n "$bpart" ]; then
                cur_mp=$(diskutil info "$bpart" 2>/dev/null | awk -F': *' '/Mount Point:/{print $2; exit}')
                if [ -z "$cur_mp" ]; then
                    if diskutil mount "$bpart" >/dev/null 2>&1; then
                        MOUNTED_BY_US="$MOUNTED_BY_US $bpart"
                        cur_mp=$(diskutil info "$bpart" 2>/dev/null | awk -F': *' '/Mount Point:/{print $2; exit}')
                        ocrel=$(boot_ocrel)
                        ocrel=${ocrel:-EFI/OC}
                        if [ -n "$cur_mp" ] && [ -f "$cur_mp/$ocrel/config.plist" ]; then
                            found_oc=1
                            echo "booted-esp: $bpart -> /$ocrel"
                            sanitize_config_plist "$cur_mp/$ocrel/config.plist" "$ROOT_DIR/08-efi-opencore/${bpart}-config.plist.xml" || true
                            if [ -d "$cur_mp/$ocrel/Kexts" ]; then
                                ls -la "$cur_mp/$ocrel/Kexts" 2>/dev/null | sed 's/^/    /'
                                for k in AirportMtkWlan.kext SimpleMtkWlan.kext itlwm.kext; do
                                    if [ -d "$cur_mp/$ocrel/Kexts/$k" ]; then
                                        ver=$(plutil -extract CFBundleShortVersionString raw -o - "$cur_mp/$ocrel/Kexts/$k/Contents/Info.plist" 2>/dev/null || echo "?")
                                        bin="$cur_mp/$ocrel/Kexts/$k/Contents/MacOS/${k%.kext}"
                                        sha=$([ -f "$bin" ] && shasum -a 256 "$bin" 2>/dev/null | awk '{print $1}' || echo "?")
                                        echo "  -> $k version=$ver sha256=$sha"
                                    fi
                                done
                            fi
                            for lf in $(ls -t "$cur_mp"/opencore-*.txt "$cur_mp"/panic-*.txt 2>/dev/null | head -n 4); do
                                safe_lf=$(printf '%s' "$(basename "$lf")" | tr -c 'A-Za-z0-9._-' '_')
                                head -c 262144 "$lf" > "$ROOT_DIR/08-efi-opencore/${bpart}-${safe_lf}" 2>/dev/null && redact_file_inplace "$ROOT_DIR/08-efi-opencore/${bpart}-${safe_lf}" || true
                            done
                        fi
                    fi
                fi
            fi
        fi
        [ "$found_oc" -eq 1 ] || echo "(no mounted OpenCore config.plist readable; mount EFI or run Full Logs mode if needed)"
    fi
} > "$ROOT_DIR/08-efi-opencore/disks-efi-scan.txt" 2>&1
redact_file_inplace "$ROOT_DIR/08-efi-opencore/disks-efi-scan.txt"

# --- Section 9: Panics & Crash Reports ---
progress "Checking recent panic and Wi-Fi daemon crash logs..."
PANIC_COUNT=0
CRASH_COUNT=0
diag_dirs=("/Library/Logs/DiagnosticReports" "/Library/Logs/DiagnosticReports/Retired")
[ -n "$TARGET_HOME" ] && diag_dirs+=("$TARGET_HOME/Library/Logs/DiagnosticReports")
if [ -n "$FIXTURE_DIR" ] && [ -d "$FIXTURE_DIR/DiagnosticReports" ]; then
    diag_dirs=("$FIXTURE_DIR/DiagnosticReports")
fi

collect_recent_into() {
    local prefix=$1 limit=$2
    shift 2
    local recent=() f i count=0 dst
    for f in "$@"; do
        [ -f "$f" ] && [ ! -L "$f" ] || continue
        i=0
        while [ "$i" -lt "${#recent[@]}" ] && [ ! "$f" -nt "${recent[$i]}" ]; do
            i=$((i + 1))
        done
        [ "$i" -lt "$limit" ] || continue
        recent=("${recent[@]:0:$i}" "$f" "${recent[@]:$i}")
        recent=("${recent[@]:0:$limit}")
    done
    for f in ${recent[@]+"${recent[@]}"}; do
        count=$((count + 1))
        dst="$ROOT_DIR/09-crashes-panics/${prefix}-${count}-$(printf '%s' "$(basename "$f")" | tr -c 'A-Za-z0-9._-' '_')"
        head -c 524288 "$f" > "$dst" 2>/dev/null && redact_file_inplace "$dst" || true
    done
    printf '%s' "$count"
}

shopt -s nullglob
panic_candidates=()
crash_candidates=()
for d in "${diag_dirs[@]}"; do
    [ -d "$d" ] || continue
    for f in "$d"/*.panic; do panic_candidates+=("$f"); done
    for f in "$d"/airportd*.ips "$d"/WiFiAgent*.ips "$d"/wifip2pd*.ips "$d"/wifivelocityd*.ips "$d"/AirportMtkWlan*.ips "$d"/airportd*.crash; do
        crash_candidates+=("$f")
    done
done
shopt -u nullglob

PANIC_COUNT=$(collect_recent_into "panic" 3 ${panic_candidates[@]+"${panic_candidates[@]}"})
CRASH_COUNT=$(collect_recent_into "crash" 4 ${crash_candidates[@]+"${crash_candidates[@]}"})

# --- Section 10: Installer / UI Session Log ---
if [ -n "$SESSION_LOG" ] && [ -f "$SESSION_LOG" ] && [ ! -L "$SESSION_LOG" ]; then
    cp "$SESSION_LOG" "$ROOT_DIR/10-installer-session.log" 2>/dev/null || true
    redact_file_inplace "$ROOT_DIR/10-installer-session.log"
fi

# --- Section 0: Summary & Triage Verdict Sheet ---
progress "Writing triage summary..."
KEXT_SUMMARY=$(printf '%s\n' "$KMUTIL_LOADED" | awk '
    tolower($0) ~ /(airportmtkwlan|simplemtkwlan|itlwm)/ {
        for (i = 1; i <= NF; i++) {
            if ($i ~ /^com\.|^org\./) {
                ver = ($(i+1) ~ /^\(/) ? $(i+1) : ""
                out = out (out ? "," : "") $i ver
                break
            }
        }
    }
    END { print (out ? out : "none") }
')

PCI_SUMMARY=$(awk '
    /\+-o / { in_mtk=0; blk=$0 }
    /"vendor-id" = <c3140000>/ || /"IOName" = "pci14c3,/ { in_mtk=1 }
    /"IOName"|"device-id"|"subsystem-id"/ { gsub(/^[[:space:]]+/, ""); blk = blk " " $0 }
    /^$/ { if (in_mtk) { out = out (out ? " ; " : "") blk }; in_mtk=0 }
    END { if (in_mtk) out = out (out ? " ; " : "") blk; print (out ? out : "none") }
' "$ROOT_DIR/02-hardware-pci-ioreg.txt" | tr -s ' ' | cut -c1-160 || true)
[ -n "$PCI_SUMMARY" ] || PCI_SUMMARY="none"
MTK_PCI_COUNT=$(grep -c '"vendor-id" = <c3140000>' "$ROOT_DIR/02-hardware-pci-ioreg.txt" 2>/dev/null || true)
[ -n "$MTK_PCI_COUNT" ] || MTK_PCI_COUNT=0
AUXKC_CONFLICT="none"
if ls /Library/Extensions/AirportMtkWlan.kext /Library/Extensions/SimpleMtkWlan.kext >/dev/null 2>&1; then
    AUXKC_CONFLICT="present (/Library/Extensions)"
fi
OC_VER=$(nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:opencore-version 2>/dev/null | cut -f2- || echo "absent")
BOOT_ARGS_RAW=$(nvram boot-args 2>/dev/null | cut -f2- || echo "none")
[ -n "$BOOT_ARGS_RAW" ] || BOOT_ARGS_RAW="none"
MTK_DBG_LINES=$(wc -l < "$ROOT_DIR/03-mtk-debug-log.txt" 2>/dev/null | tr -d ' ' || echo 0)
WIFI_PWR=$(grep -m1 'Wi-Fi Power' "$ROOT_DIR/04-network-wifi-state.txt" 2>/dev/null | tr -s ' ' || echo "unknown")

{
    echo "=== AirportMtkWlan Diagnostic Summary ==="
    echo "diag: grabber-version $TOOL_VERSION"
    echo "diag: macos $OS_VER ($OS_BUILD) arch $ARCH_NAME"
    echo "diag: model $HW_MODEL cpu $CPU_BRAND"
    echo "diag: scope $SCOPE mode $MODE"
    echo "diag: opencore $OC_VER"
    echo "diag: boot-args $BOOT_ARGS_RAW"
    echo "diag: kext-loaded $KEXT_SUMMARY"
    echo "diag: mtk-pci-count $MTK_PCI_COUNT detail $PCI_SUMMARY"
    echo "diag: auxkc-conflict $AUXKC_CONFLICT"
    echo "diag: wifi-interfaces ${WIFI_IFACES:-absent}"
    echo "diag: wifi-power $WIFI_PWR"
    echo "diag: mtkdebuglog-lines $MTK_DBG_LINES"
    echo "diag: panics-found $PANIC_COUNT crashes-found $CRASH_COUNT"
    echo "diag: redaction complete (keys, SSIDs, BSSID/MAC suffixes, serials, UUIDs, usernames, hostnames, and IPs stripped)"
    echo
    echo "Files in this archive:"
    ls -1 "$ROOT_DIR" | sed 's/^/  - /'
} > "$ROOT_DIR/00-summary.txt" 2>&1
redact_file_inplace "$ROOT_DIR/00-summary.txt"

# Package into compressed archive
progress "Packaging archive..."
COPYFILE_DISABLE=1 tar -czf "$OUT_PATH" -C "$WORK" "$BUNDLE_NAME" || {
    echo "ERROR: tar failed to create $OUT_PATH" >&2
    exit 1
}

if [ "$(id -u)" -eq 0 ] && [ -n "$TARGET_USER" ] && [ -f "$OUT_PATH" ]; then
    chown "$TARGET_USER" "$OUT_PATH" 2>/dev/null || true
    chmod 644 "$OUT_PATH" 2>/dev/null || true
fi

if [ "$QUIET" -eq 0 ]; then
    printf 'OK Archive created: %s\n' "$OUT_PATH"
fi
printf 'OUTPUT %s\n' "$OUT_PATH"
