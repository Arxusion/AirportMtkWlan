#!/bin/bash
# AirportMtkWlan / SimpleMtkWlan Comprehensive Diagnostic Log Grabber
# Collects hardware, boot, OpenCore, IORegistry, MtkDebugLog, kernel, Wi-Fi
# daemon, and crash logs into a single privacy-redacted .tar.gz archive.

set -u
set -o pipefail
umask 077

TOOL_VERSION="2.3.0"
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH

SCRIPT_NAME=$(basename "$0")
MODE="full"
NO_EFI=0
QUIET=0
LAST_3_BOOTS=0
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
  --last-3-boots          Specifically extract multi-boot logs across current + last 2 boots
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
        --last-3-boots)
            LAST_3_BOOTS=1; shift ;;
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

# Drain stdin after hitting byte cap so upstream generators never hit SIGPIPE under pipefail.
cap_bytes() {
    local max_b=${1:-2097152}
    awk -v lim="$max_b" '
        BEGIN { total = 0; capped = 0 }
        {
            if (total < lim) {
                print
                total += length($0) + 1
            } else {
                capped++
            }
        }
        END {
            if (capped > 0) {
                printf "... (%d lines truncated after %d-byte log cap)\n", capped, lim
            }
        }'
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
        $in =~ s{("(?:crashReporterKey|deviceIdentifierForVendor|sessionID|userID|incident|bootSessionUUID|sleepWakeUUID|systemID|machineSerialNumber|deviceID|hostUUID|serial[A-Za-z]*)"\s*:\s*)"[^"]*"}{$1"<ID_REDACTED>"}gi;
        $in =~ s{((?:^|\n)\s*Serial\s+Number\s*:\s*)[^\r\n]+}{$1<ID_REDACTED>}gi;

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
    echo "== Recent Boot & Shutdown History"
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/last_reboot.txt" ]; then
        cat "$FIXTURE_DIR/last_reboot.txt"
    elif [ -n "$FIXTURE_DIR" ]; then
        echo "(no fixture reboot history)"
    else
        bounded 10 sh -c 'last reboot shutdown 2>&1 | head -n 25' || true
    fi
    echo
    echo "== SIP & Boot Arguments"
    csrutil status 2>&1 || true
    echo "boot-args: $(nvram boot-args 2>/dev/null | cut -f2- || echo '(not set)')"
    echo "csr-active-config: $(nvram 7C436110-AB2A-4BBB-A880-FE41995C9F82:csr-active-config 2>/dev/null | cut -f2- || echo '(not set)')"
    echo "opencore-version: $(nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:opencore-version 2>/dev/null | cut -f2- || echo '(absent)')"
    echo "opencore-boot-path: $(nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:boot-path 2>/dev/null | cut -f2- || echo '(absent)')"
    echo "mtk-wifi-band: $(nvram 7C436110-AB2A-4BBB-A880-FE41995C9F82:mtk-wifi-band 2>/dev/null | cut -f2- || echo '(not set)')"
    echo "mtk-wifi-cc: $(nvram 7C436110-AB2A-4BBB-A880-FE41995C9F82:mtk-wifi-cc 2>/dev/null | cut -f2- || echo '(not set)')"
    echo "nmx-wifi-band: $(nvram 7C436110-AB2A-4BBB-A880-FE41995C9F82:nmx-wifi-band 2>/dev/null | cut -f2- || echo '(not set)')"
    echo "nmx-wifi-cc: $(nvram 7C436110-AB2A-4BBB-A880-FE41995C9F82:nmx-wifi-cc 2>/dev/null | cut -f2- || echo '(not set)')"
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
    for cls in AirportItlwm SimpleMtkWlan IOPCIEDeviceWrapper IO80211Controller IO80211InfraInterface IO80211Interface IO80211AWDLPeerManager; do
        echo "-- class: $cls"
        bounded 10 ioreg -r -c "$cls" -l -w0 2>&1 | grep -v '"MtkDebugLog"' | head -n 160 || true
    done
    echo
    echo "=== MTK Wi-Fi Telemetry & Country Properties ==="
    printf '%s\n' "$IOREG_PCI" | grep -E '"(MTKWiFi|MTKSleep|MTKWake|MtkThroughput|IOClass|CFBundleVersion)' || echo "(no MTK telemetry properties found)"
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
    # Drain stdin without exiting early to prevent SIGPIPE/Broken pipe from printf.
    MTK_DBG=$(printf '%s\n' "$IOREG_PCI" | awk '
        !done && /"MtkDebugLog" = "/ {
            f = 1
            print
            if (/"MtkDebugLog" = "([^"\\]|\\.)*"$/) {
                f = 0
                done = 1
            }
            next
        }
        f {
            if (/^[| ]*(\+-o |\}|"[A-Za-z0-9_.-]+" = )/) {
                f = 0
                done = 1
                next
            }
            print
            if (/^[[:space:]]*"$/) {
                f = 0
                done = 1
            }
        }
    ')
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
                    for k in AirportMtkWlan.kext SimpleMtkWlan.kext itlwm.kext AirportMtkBtPatcher.kext AirportMtkBtFw.kext SimpleMtkBtPatcher.kext SimpleMtkBtFw.kext; do
                        if [ -d "$cand/Kexts/$k" ]; then
                            ver=$(plutil -extract CFBundleShortVersionString raw -o - "$cand/Kexts/$k/Contents/Info.plist" 2>/dev/null || echo "?")
                            bin="$cand/Kexts/$k/Contents/MacOS/${k%.kext}"
                            sha=$([ -f "$bin" ] && shasum -a 256 "$bin" 2>/dev/null | awk '{print $1}' || echo "?")
                            echo "  -> $k version=$ver sha256=$sha"
                        fi
                    done
                fi
                find "$vol" -maxdepth 2 -type f \( -name 'opencore-*.txt' -o -name 'boot*.log' -o -name 'panic-*.txt' \) -exec stat -f '%m %N' {} + 2>/dev/null \
                    | sort -rn | head -n 4 | cut -d' ' -f2- | while IFS= read -r lf; do
                    [ -n "$lf" ] || continue
                    safe_lf=$(printf '%s' "$(basename "$lf")" | tr -c 'A-Za-z0-9._-' '_')
                    head -c 262144 "$lf" > "$ROOT_DIR/08-efi-opencore/${safe_v}-${safe_lf}" 2>/dev/null && redact_file_inplace "$ROOT_DIR/08-efi-opencore/${safe_v}-${safe_lf}" || true
                done
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
                                for k in AirportMtkWlan.kext SimpleMtkWlan.kext itlwm.kext AirportMtkBtPatcher.kext AirportMtkBtFw.kext SimpleMtkBtPatcher.kext SimpleMtkBtFw.kext; do
                                    if [ -d "$cur_mp/$ocrel/Kexts/$k" ]; then
                                        ver=$(plutil -extract CFBundleShortVersionString raw -o - "$cur_mp/$ocrel/Kexts/$k/Contents/Info.plist" 2>/dev/null || echo "?")
                                        bin="$cur_mp/$ocrel/Kexts/$k/Contents/MacOS/${k%.kext}"
                                        sha=$([ -f "$bin" ] && shasum -a 256 "$bin" 2>/dev/null | awk '{print $1}' || echo "?")
                                        echo "  -> $k version=$ver sha256=$sha"
                                    fi
                                done
                            fi
                            find "$cur_mp" -maxdepth 1 -type f \( -name 'opencore-*.txt' -o -name 'panic-*.txt' \) -exec stat -f '%m %N' {} + 2>/dev/null \
                                | sort -rn | head -n 4 | cut -d' ' -f2- | while IFS= read -r lf; do
                                [ -n "$lf" ] || continue
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
mkdir -p "$ROOT_DIR/09-crashes-panics"
diag_dirs=(
    "/Library/Logs/DiagnosticReports"
    "/Library/Logs/DiagnosticReports/Retired"
    "/private/var/db/PanicReporter"
)
if [ -n "$TARGET_HOME" ]; then
    diag_dirs+=(
        "$TARGET_HOME/Library/Logs/DiagnosticReports"
        "$TARGET_HOME/Library/Logs/DiagnosticReports/Retired"
    )
fi
if [ -n "$FIXTURE_DIR" ] && [ -d "$FIXTURE_DIR/DiagnosticReports" ]; then
    diag_dirs=("$FIXTURE_DIR/DiagnosticReports")
    [ -d "$FIXTURE_DIR/PanicReporter" ] && diag_dirs+=("$FIXTURE_DIR/PanicReporter")
fi

collect_recent_into() {
    local prefix=$1 limit=$2
    shift 2
    local recent=() seen=() f i dup existing count=0 dst
    for f in "$@"; do
        [ -f "$f" ] && [ ! -L "$f" ] || continue
        dup=0
        for existing in ${seen[@]+"${seen[@]}"}; do
            if [ "$existing" = "$f" ]; then
                dup=1
                break
            fi
        done
        [ "$dup" -eq 0 ] || continue
        seen+=("$f")
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

add_panic_matches_in_dir() {
    local dir=$1
    for f in "$dir"/.contents.panic "$dir"/*.panic "$dir"/*.contents.panic "$dir"/panic*.ips "$dir"/*Panic*.ips "$dir"/Kernel-*.ips; do
        panic_candidates+=("$f")
    done
}

shopt -s nullglob
panic_candidates=()
crash_candidates=()
for d in "${diag_dirs[@]}"; do
    [ -d "$d" ] || continue
    add_panic_matches_in_dir "$d"
    for sub in "$d"/*; do
        [ -d "$sub" ] && [ ! -L "$sub" ] || continue
        add_panic_matches_in_dir "$sub"
    done
    for f in "$d"/airportd*.ips "$d"/WiFiAgent*.ips "$d"/wifip2pd*.ips "$d"/wifivelocityd*.ips "$d"/AirportMtkWlan*.ips "$d"/SimpleMtkWlan*.ips "$d"/kernelmanagerd*.ips "$d"/wifid*.ips "$d"/airportd*.crash "$d"/kernelmanagerd*.crash "$d"/SimpleMtkWlan*.crash; do
        crash_candidates+=("$f")
    done
done
shopt -u nullglob

if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/panic.log" ]; then
    panic_candidates+=("$FIXTURE_DIR/panic.log")
elif [ -z "$FIXTURE_DIR" ] && [ -f "/private/var/log/panic.log" ]; then
    panic_candidates+=("/private/var/log/panic.log")
fi

PANIC_COUNT=$(collect_recent_into "panic" 5 ${panic_candidates[@]+"${panic_candidates[@]}"})
CRASH_COUNT=$(collect_recent_into "crash" 6 ${crash_candidates[@]+"${crash_candidates[@]}"})

PANIC_CHECK_FILE="$ROOT_DIR/09-crashes-panics/00-panic-and-shutdown-check.txt"
{
    echo "=== Panic, Kernel & Wi-Fi Diagnostic Reports Inventory ==="
    for d in "${diag_dirs[@]}"; do
        echo "-- $d --"
        if [ -d "$d" ]; then
            matches=$(find "$d" -maxdepth 2 -type f \( -iname '*panic*' -o -iname '*kernel*' -o -iname '*airport*' -o -iname '*wifi*' -o -iname '*mtk*' -o -iname '*itlwm*' -o -iname '*shutdown*' \) -exec ls -ld {} + 2>/dev/null || true)
            if [ -n "$matches" ]; then
                printf '%s\n' "$matches"
            else
                echo "(no matching panic/kernel/wifi/shutdown files)"
            fi
        else
            echo "(not present)"
        fi
    done
    echo
    echo "=== NVRAM Panic & Wake-Failure Indicators ==="
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/nvram_panic.txt" ]; then
        cat "$FIXTURE_DIR/nvram_panic.txt"
    elif [ -n "$FIXTURE_DIR" ]; then
        echo "(no fixture nvram_panic)"
    else
        for k in aapl,panic-info panic-info 7C436110-AB2A-4BBB-A880-FE41995C9F82:wake-failure; do
            printf '%s: ' "$k"
            nvram "$k" 2>&1 | head -c 4096 || true
            echo
        done
        nvram -p 2>/dev/null | awk 'tolower($0) ~ /panic|wake-failure/ { print $1, substr($0, length($1)+1, 200) }' || echo "(nvram -p unreadable)"
    fi
} > "$PANIC_CHECK_FILE" 2>&1
redact_file_inplace "$PANIC_CHECK_FILE"

# --- Section 5: Kernel Logs (Current Boot + dmesg) ---
progress "Collecting kernel Wi-Fi and driver logs..."
{
    echo "=== Kernel Log Since Boot ==="
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/kernel_log.txt" ]; then
        cat "$FIXTURE_DIR/kernel_log.txt"
    elif [ -n "$FIXTURE_DIR" ]; then
        echo "(no fixture kernel log)"
    else
        PRED_KERNEL='process == "kernel" AND (eventMessage CONTAINS[c] "mtk" OR eventMessage CONTAINS[c] "mwx" OR eventMessage CONTAINS[c] "AirportMtk" OR eventMessage CONTAINS[c] "SimpleMtk" OR eventMessage CONTAINS[c] "AirportItlwm" OR eventMessage CONTAINS[c] "itlwm" OR eventMessage CONTAINS[c] "80211" OR eventMessage CONTAINS[c] "WCL" OR eventMessage CONTAINS[c] "Skywalk" OR eventMessage CONTAINS[c] "shutdown cause" OR eventMessage CONTAINS[c] "panic" OR sender CONTAINS[c] "Mtk" OR sender CONTAINS[c] "80211" OR sender CONTAINS[c] "Skywalk")'
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
} | cap_bytes 2097152 | squash_repeats | headtail 1500 1500 > "$ROOT_DIR/05-kernel-log-boot.txt" 2>&1

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

# --- Shutdown Cause Verdict (needs Section 5 or bounded fallback) ---
{
    echo
    echo "=== Previous Shutdown Cause (boot log) ==="
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/shutdown_cause.txt" ]; then
        cat "$FIXTURE_DIR/shutdown_cause.txt"
    elif [ -n "$FIXTURE_DIR" ]; then
        echo "(no fixture shutdown_cause)"
    else
        boot_sc=$(grep -i 'shutdown cause:' "$ROOT_DIR/05-kernel-log-boot.txt" 2>/dev/null | tail -n 5 || true)
        if [ -n "$boot_sc" ]; then
            printf '%s\n' "$boot_sc"
        elif [ -n "$BOOT_SEC" ]; then
            lshow 10 --start "$(date -r "$BOOT_SEC" '+%Y-%m-%d %H:%M:%S')" \
                     --end "$(date -r $((BOOT_SEC + 300)) '+%Y-%m-%d %H:%M:%S')" \
                     --style compact --predicate 'process == "kernel" AND (eventMessage CONTAINS[c] "Previous shutdown cause" OR eventMessage CONTAINS[c] "shutdown cause")' 2>&1 || true
        else
            lshow 10 --last 30m --style compact --predicate 'process == "kernel" AND (eventMessage CONTAINS[c] "Previous shutdown cause" OR eventMessage CONTAINS[c] "shutdown cause")' 2>&1 || true
        fi
    fi
} >> "$PANIC_CHECK_FILE" 2>&1
redact_file_inplace "$PANIC_CHECK_FILE"
LOCAL_HOST=$(scutil --get LocalHostName 2>/dev/null || true)
if [ -n "$LOCAL_HOST" ] && [ "${#LOCAL_HOST}" -ge 3 ]; then
    LOCAL_HOST_ENV="$LOCAL_HOST" /usr/bin/perl -i -pe 'my $h = $ENV{LOCAL_HOST_ENV}; s/\Q$h\E/<HOST>/gi if defined $h && length($h) >= 3;' "$PANIC_CHECK_FILE" 2>/dev/null || true
fi
LAST_SHUTDOWN_CAUSE=$(grep -i 'Previous shutdown cause:' "$PANIC_CHECK_FILE" 2>/dev/null | tail -n 1 | sed -E 's/.*[Pp]revious shutdown cause:[[:space:]]*//' | tr -s ' ' | cut -c1-40 || true)
[ -n "$LAST_SHUTDOWN_CAUSE" ] || LAST_SHUTDOWN_CAUSE="unknown"



# --- Section 6: macOS Wi-Fi Daemon & KernelManager Logs ---
progress "Collecting airportd, WiFiAgent, and kernelmanagerd logs..."
{
    if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/wifi_log.txt" ]; then
        echo "=== Wi-Fi Userspace Daemons & Kext Manager (last 30m) ==="
        cat "$FIXTURE_DIR/wifi_log.txt"
        if [ -f "$FIXTURE_DIR/wifi_error_log.txt" ]; then
            echo
            echo "=== Kext Manager & Wi-Fi Errors/Lifecycle (last 2h) ==="
            cat "$FIXTURE_DIR/wifi_error_log.txt"
        fi
    elif [ -n "$FIXTURE_DIR" ]; then
        echo "=== Wi-Fi Userspace Daemons & Kext Manager (last 30m) ==="
        echo "(no fixture wifi_log)"
    else
        echo "=== Kext Manager & Wi-Fi Errors/Lifecycle (last 1h) ==="
        lshow 15 --last 1h --style compact --predicate \
            '((process == "kernelmanagerd" OR process == "kextd") AND (messageType == error OR messageType == fault OR eventMessage CONTAINS[c] "mtk" OR eventMessage CONTAINS[c] "airport" OR eventMessage CONTAINS[c] "itlwm" OR eventMessage CONTAINS[c] "80211")) OR ((process == "airportd" OR process == "WiFiAgent" OR process == "wifip2pd" OR process == "wifivelocityd") AND (messageType == error OR messageType == fault OR eventMessage CONTAINS[c] "mtk" OR eventMessage CONTAINS[c] "assoc" OR eventMessage CONTAINS[c] "power"))' \
            2>&1 | awk '!/INTERFACE ADDED EVENT/' | cap_bytes 2097152 | squash_repeats | headtail 600 1200 || true
        echo
        echo "=== Wi-Fi Userspace Daemons (last 30m, de-spammed) ==="
        lshow 20 --last 30m --style compact --predicate \
            'process == "airportd" OR process == "WiFiAgent" OR process == "wifip2pd" OR process == "wifivelocityd" OR subsystem == "com.apple.wifi" OR (process == "kernelmanagerd" AND (eventMessage CONTAINS[c] "mtk" OR eventMessage CONTAINS[c] "airport" OR eventMessage CONTAINS[c] "80211"))' \
            2>&1 | awk '!/(\[GET INTF NAME\]|APPLE80211_M_RSSI_CHANGED|Per-MLO link stats|Incoming QoS|INTERFACE ADDED EVENT)/' | cap_bytes 2097152 | squash_repeats | headtail 800 1600 || true
    fi
} > "$ROOT_DIR/06-wifi-userspace-logs.txt" 2>&1
redact_file_inplace "$ROOT_DIR/06-wifi-userspace-logs.txt"

# --- Section 7: Previous Boot & Last 3 Boots Kernel Logs ---
if [ "$MODE" = "full" ] || [ "$LAST_3_BOOTS" -eq 1 ] || { [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/prev_boot_log.txt" ]; }; then
    progress "Collecting multi-boot kernel logs (last 3 boots)..."
    
    BOOT_LOGS_DIR="$ROOT_DIR/07-last-3-boot-logs"
    mkdir -p "$BOOT_LOGS_DIR/boot-0-current" "$BOOT_LOGS_DIR/boot-1-previous" "$BOOT_LOGS_DIR/boot-2-prior"

    if [ -f "$ROOT_DIR/05-kernel-log-boot.txt" ]; then
        cp "$ROOT_DIR/05-kernel-log-boot.txt" "$BOOT_LOGS_DIR/boot-0-current/01-kernel-driver-telemetry.txt"
    fi

    PRED_MULTI_BOOT='(process == "kernel" AND (eventMessage CONTAINS[c] "mtk" OR eventMessage CONTAINS[c] "mwx" OR eventMessage CONTAINS[c] "AirportMtk" OR eventMessage CONTAINS[c] "AirportMtkBt" OR eventMessage CONTAINS[c] "SimpleMtk" OR eventMessage CONTAINS[c] "AirportItlwm" OR eventMessage CONTAINS[c] "itlwm" OR eventMessage CONTAINS[c] "WCL" OR eventMessage CONTAINS[c] "panic" OR eventMessage CONTAINS[c] "shutdown cause" OR eventMessage CONTAINS[c] "outside of kext range" OR eventMessage CONTAINS[c] "Debugger" OR eventMessage CONTAINS[c] "backtrace" OR sender CONTAINS[c] "Mtk" OR sender CONTAINS[c] "AirportMtkBt")) OR (process == "kernelmanagerd" AND (eventMessage CONTAINS[c] "mtk" OR eventMessage CONTAINS[c] "airport" OR eventMessage CONTAINS[c] "fail" OR eventMessage CONTAINS[c] "error" OR eventMessage CONTAINS[c] "load" OR eventMessage CONTAINS[c] "IOVersatile" OR eventMessage CONTAINS[c] "dependencies"))'

    # Detect exact historical boot sessions across reboots
    detect_boot_epochs() {
        if [ -n "$FIXTURE_DIR" ]; then
            return
        fi
        if command -v /usr/bin/python3 >/dev/null 2>&1; then
            /usr/bin/python3 -c '
import subprocess, os, re, datetime, glob

now_ts = int(datetime.datetime.now().timestamp())
boots = []

# 1. sysctl kern.boottime (Current Boot)
try:
    out = subprocess.check_output(["sysctl", "-n", "kern.boottime"]).decode()
    m = re.search(r"sec = (\d+)", out)
    if m:
        b0 = int(m.group(1))
        if b0 <= now_ts + 60:
            boots.append(b0)
except Exception:
    pass

# 2. /var/log/fsck_apfs.log (Universal APFS boot mount records)
if os.path.exists("/var/log/fsck_apfs.log"):
    try:
        with open("/var/log/fsck_apfs.log") as f:
            for line in f:
                m = re.search(r"fsck_apfs started at (.* \d{4})", line)
                if m:
                    try:
                        dt = datetime.datetime.strptime(m.group(1).strip(), "%a %b %d %H:%M:%S %Y")
                        ts = int(dt.timestamp())
                        if ts <= now_ts + 60:
                            boots.append(ts)
                    except Exception:
                        pass
    except Exception:
        pass

# 3. OpenCore log files across /Volumes
for p in glob.glob("/Volumes/*/opencore-*.txt") + glob.glob("/Volumes/opencore-*.txt"):
    fn = os.path.basename(p)
    m = re.search(r"opencore-(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})\.txt", fn)
    if m:
        try:
            dt = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                   int(m.group(4)), int(m.group(5)), int(m.group(6)))
            ts = int(dt.timestamp())
            if ts <= now_ts + 60:
                boots.append(ts)
        except Exception:
            pass

boots = sorted(list(set(boots)))
distinct_starts = []
for ts in reversed(boots):
    if not distinct_starts or abs(distinct_starts[-1] - ts) > 900:
        distinct_starts.append(ts)

for i in range(min(3, len(distinct_starts))):
    s_ts = distinct_starts[i]
    e_ts = now_ts if i == 0 else distinct_starts[i - 1] - 5
    s_dt = datetime.datetime.fromtimestamp(s_ts)
    e_dt = datetime.datetime.fromtimestamp(e_ts)
    s_str = s_dt.strftime("%Y-%m-%d %H:%M:%S")
    e_str = e_dt.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{i}|{s_ts}|{e_ts}|{s_str}|{e_str}")
' 2>/dev/null || true
        fi
    }

    # Match OpenCore log within window
    find_oc_for_epoch() {
        local target_ts=$1
        local best_f="" best_d=999999
        for f in /Volumes/*/opencore-*.txt /Volumes/opencore-*.txt; do
            [ -f "$f" ] || continue
            fn=$(basename "$f")
            if [[ "$fn" =~ opencore-([0-9]{4})-([0-9]{2})-([0-9]{2})-([0-9]{2})([0-9]{2})([0-9]{2})\.txt ]]; then
                f_ts=$(date -j -f "%Y-%m-%d %H%M%S" "${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}${BASH_REMATCH[5]}${BASH_REMATCH[6]}" "+%s" 2>/dev/null || echo 0)
                diff=$(( target_ts > f_ts ? target_ts - f_ts : f_ts - target_ts ))
                if [ "$diff" -lt "$best_d" ] && [ "$diff" -lt 1800 ]; then
                    best_d=$diff
                    best_f="$f"
                fi
            fi
        done
        printf '%s' "$best_f"
    }

    # Match panics or shutdown stalls within window
    find_panics_for_window() {
        local s_ts=$1 e_ts=$2 out_f=$3
        for d in "/Library/Logs/DiagnosticReports" "/Library/Logs/DiagnosticReports/Retired" "$TARGET_HOME/Library/Logs/DiagnosticReports"; do
            [ -d "$d" ] || continue
            for pf in "$d"/*panic* "$d"/Kernel* "$d"/shutdown_stall*; do
                [ -f "$pf" ] || continue
                m_ts=$(stat -f "%m" "$pf" 2>/dev/null || echo 0)
                if [ "$m_ts" -ge "$s_ts" ] && [ "$m_ts" -le "$((e_ts + 120))" ]; then
                    echo "=== $(basename "$pf") ===" >> "$out_f"
                    head -n 250 "$pf" 2>/dev/null | squash_repeats >> "$out_f"
                    echo >> "$out_f"
                fi
            done
        done
    }

    BOOT_EPOCHS=$(detect_boot_epochs)
    
    # Defaults in case epochs detection is not available
    B0_START=$BOOT_SEC; B0_END=$(date +%s); B0_START_FMT=$(date -r "$BOOT_SEC" '+%Y-%m-%d %H:%M:%S'); B0_END_FMT=$(date '+%Y-%m-%d %H:%M:%S')
    B1_START=$((BOOT_SEC - 7200)); B1_END=$BOOT_SEC; B1_START_FMT=$(date -r "$B1_START" '+%Y-%m-%d %H:%M:%S'); B1_END_FMT=$(date -r "$B1_END" '+%Y-%m-%d %H:%M:%S')
    B2_START=$((BOOT_SEC - 21600)); B2_END=$((BOOT_SEC - 7200)); B2_START_FMT=$(date -r "$B2_START" '+%Y-%m-%d %H:%M:%S'); B2_END_FMT=$(date -r "$B2_END" '+%Y-%m-%d %H:%M:%S')

    while IFS='|' read -r b_idx b_sts b_ets b_sstr b_estr; do
        case "$b_idx" in
            0) B0_START=$b_sts; B0_END=$b_ets; B0_START_FMT=$b_sstr; B0_END_FMT=$b_estr ;;
            1) B1_START=$b_sts; B1_END=$b_ets; B1_START_FMT=$b_sstr; B1_END_FMT=$b_estr ;;
            2) B2_START=$b_sts; B2_END=$b_ets; B2_START_FMT=$b_sstr; B2_END_FMT=$b_estr ;;
        esac
    done <<< "$BOOT_EPOCHS"

    # --- Boot 0 (Current Boot) ---
    {
        echo "=== Boot 0 (Current Session) Summary ==="
        echo "Boot Time:      $B0_START_FMT (epoch $B0_START)"
        echo "Snapshot Time:  $B0_END_FMT"
        echo "Uptime:         $(( B0_END - B0_START )) seconds"
        echo "Kernel Version: $(uname -v 2>/dev/null || echo '?')"
        echo "macOS Version:  $(sw_vers -productVersion 2>/dev/null || echo '?') (Build $(sw_vers -buildVersion 2>/dev/null || echo '?'))"
    } > "$BOOT_LOGS_DIR/boot-0-current/00-boot-summary.txt"
    find_panics_for_window "$B0_START" "$B0_END" "$BOOT_LOGS_DIR/boot-0-current/02-crashes-panics.txt"
    b0_oc=$(find_oc_for_epoch "$B0_START")
    if [ -n "$b0_oc" ] && [ -r "$b0_oc" ]; then
        head -c 262144 "$b0_oc" > "$BOOT_LOGS_DIR/boot-0-current/03-opencore-boot.txt"
        redact_file_inplace "$BOOT_LOGS_DIR/boot-0-current/03-opencore-boot.txt"
    fi

    # --- Boot 1 (Previous Boot) ---
    {
        echo "=== Boot 1 (Previous Session) Summary ==="
        echo "Boot Time:     $B1_START_FMT (epoch $B1_START)"
        echo "Session End:   $B1_END_FMT"
        echo "Duration:      $(( B1_END - B1_START )) seconds"
    } > "$BOOT_LOGS_DIR/boot-1-previous/00-boot-summary.txt"

    {
        if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/prev_boot_log.txt" ]; then
            echo "=== Previous Boot Kernel Log (fixture, tail-preserved) ==="
            cat "$FIXTURE_DIR/prev_boot_log.txt" | squash_repeats | headtail 800 2200
        elif [ -z "$FIXTURE_DIR" ] && [ -n "$B1_START" ]; then
            echo "=== Previous Boot Focused Driver, Panic & Shutdown Cause ($B1_START_FMT to $B1_END_FMT) ==="
            lshow 20 --start "$B1_START_FMT" --end "$B1_END_FMT" \
                     --style compact --predicate "$PRED_MULTI_BOOT" 2>&1 \
                | cap_bytes 2097152 | squash_repeats | headtail 800 1500 || true
            echo
            echo "=== Previous Boot Wi-Fi Stack Kernel Log Tail ($B1_START_FMT to $B1_END_FMT) ==="
            lshow 25 --start "$B1_START_FMT" --end "$B1_END_FMT" \
                     --style compact --predicate 'process == "kernel" AND (eventMessage CONTAINS[c] "mtk" OR eventMessage CONTAINS[c] "mwx" OR eventMessage CONTAINS[c] "airport" OR eventMessage CONTAINS[c] "itlwm" OR eventMessage CONTAINS[c] "80211" OR eventMessage CONTAINS[c] "skywalk" OR eventMessage CONTAINS[c] "panic" OR eventMessage CONTAINS[c] "shutdown cause" OR eventMessage CONTAINS[c] "outside of kext range")' 2>&1 \
                | cap_bytes 2097152 | squash_repeats | headtail 800 2200 || true
        else
            echo "(skipped: boottime not available)"
        fi
    } > "$ROOT_DIR/07-previous-boot-kernel-log.txt" 2>&1
    redact_file_inplace "$ROOT_DIR/07-previous-boot-kernel-log.txt"
    cp "$ROOT_DIR/07-previous-boot-kernel-log.txt" "$BOOT_LOGS_DIR/boot-1-previous/01-kernel-driver-tail.txt"

    find_panics_for_window "$B1_START" "$B1_END" "$BOOT_LOGS_DIR/boot-1-previous/02-crashes-panics.txt"
    b1_oc=$(find_oc_for_epoch "$B1_START")
    if [ -n "$b1_oc" ] && [ -r "$b1_oc" ]; then
        head -c 262144 "$b1_oc" > "$BOOT_LOGS_DIR/boot-1-previous/03-opencore-boot.txt"
        redact_file_inplace "$BOOT_LOGS_DIR/boot-1-previous/03-opencore-boot.txt"
    fi

    # --- Boot 2 (Prior Boot) ---
    {
        echo "=== Boot 2 (Prior Session, 2 Boots Ago) Summary ==="
        echo "Boot Time:     $B2_START_FMT (epoch $B2_START)"
        echo "Session End:   $B2_END_FMT"
        echo "Duration:      $(( B2_END - B2_START )) seconds"
    } > "$BOOT_LOGS_DIR/boot-2-prior/00-boot-summary.txt"

    {
        if [ -n "$FIXTURE_DIR" ] && [ -f "$FIXTURE_DIR/prev_boot_log.txt" ]; then
            echo "=== Prior Boot Kernel Log (fixture mock) ==="
            head -n 50 "$FIXTURE_DIR/prev_boot_log.txt" | squash_repeats
        elif [ -z "$FIXTURE_DIR" ] && [ -n "$B2_START" ]; then
            echo "=== Prior Boot (2 boots ago) Focused Driver & Kernel Log ($B2_START_FMT to $B2_END_FMT) ==="
            lshow 20 --start "$B2_START_FMT" --end "$B2_END_FMT" \
                     --style compact --predicate "$PRED_MULTI_BOOT" 2>&1 \
                | cap_bytes 2097152 | squash_repeats | headtail 800 1500 || true
        else
            echo "(skipped: boottime not available)"
        fi
    } > "$ROOT_DIR/07b-prior-boot-kernel-log.txt" 2>&1
    redact_file_inplace "$ROOT_DIR/07b-prior-boot-kernel-log.txt"
    cp "$ROOT_DIR/07b-prior-boot-kernel-log.txt" "$BOOT_LOGS_DIR/boot-2-prior/01-kernel-driver-tail.txt"

    find_panics_for_window "$B2_START" "$B2_END" "$BOOT_LOGS_DIR/boot-2-prior/02-crashes-panics.txt"
    b2_oc=$(find_oc_for_epoch "$B2_START")
    if [ -n "$b2_oc" ] && [ -r "$b2_oc" ]; then
        head -c 262144 "$b2_oc" > "$BOOT_LOGS_DIR/boot-2-prior/03-opencore-boot.txt"
        redact_file_inplace "$BOOT_LOGS_DIR/boot-2-prior/03-opencore-boot.txt"
    fi
fi

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
MTK_COUNTRY=$(grep -E '"MTKWiFiCountry(|Source)" = ' "$ROOT_DIR/02-hardware-pci-ioreg.txt" 2>/dev/null | tr '\n' ';' | tr -s ' ' | sed 's/;$//' || true)
[ -n "$MTK_COUNTRY" ] || MTK_COUNTRY="unset"
MTK_HEALTH=$(grep -E '"MTKWiFi(DMAStalls|FullResets|SEREvents|RxDeafResets|MCUTimeouts|AutoResetEnabled)" = ' "$ROOT_DIR/02-hardware-pci-ioreg.txt" 2>/dev/null | tr '\n' ';' | tr -s ' ' | sed 's/;$//' || true)
[ -n "$MTK_HEALTH" ] || MTK_HEALTH="unavailable"

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
    echo "diag: mtk-country $MTK_COUNTRY"
    echo "diag: mtk-health $MTK_HEALTH"
    echo "diag: mtkdebuglog-lines $MTK_DBG_LINES"
    echo "diag: panics-found $PANIC_COUNT crashes-found $CRASH_COUNT"
    echo "diag: last-shutdown-cause $LAST_SHUTDOWN_CAUSE"
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
