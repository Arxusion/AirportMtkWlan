#!/bin/bash
# One-click macOS Terminal launcher for collecting AirportMtkWlan diagnostic logs.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/mtk-grab-logs.sh"
if [ ! -x "$SCRIPT" ]; then
    echo "Error: mtk-grab-logs.sh not found at $SCRIPT"
    exit 1
fi

echo "============================================================"
echo "  AirportMtkWlan / SimpleMtkWlan Diagnostic Log Grabber"
echo "============================================================"
echo
echo "Personal data (Wi-Fi keys, SSIDs, BSSID/MAC suffixes, serials,"
echo "UUIDs, usernames, and IPs) will be automatically redacted."
echo
printf "Include admin-only logs (dmesg, wdutil, OpenCore EFI)? [Y/n]: "
read -r reply

STAMP=$(date '+%Y%m%d-%H%M%S')
OUT="$HOME/Desktop/AirportMtkWlan-Logs-${STAMP}.tar.gz"

case "$reply" in
    [Nn]*)
        "$SCRIPT" --out "$OUT"
        ;;
    *)
        echo "Enter your macOS password if prompted (or Ctrl+C and re-run without admin):"
        sudo env "MTK_TARGET_USER=$USER" "$SCRIPT" --out "$OUT" || "$SCRIPT" --out "$OUT"
        ;;
esac

if [ -f "$OUT" ]; then
    echo
    echo "Saved redacted diagnostic archive to:"
    echo "  $OUT"
    open -R "$OUT" 2>/dev/null || true
    echo
    printf "Open GitHub Bug Report page in browser to attach it? [Y/n]: "
    read -r open_gh
    case "$open_gh" in
        [Nn]*) ;;
        *) open "https://github.com/Arxusion/AirportMtkWlan/issues/new?template=1-bug.yml" 2>/dev/null || true ;;
    esac
fi
