#!/bin/bash
# Automated verification for AirportMtkWlan diagnostic log grabber & redaction.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
GRABBER="$ROOT/tools/mtk-grab-logs.sh"
CMD_WRAPPER="$ROOT/tools/Grab Logs.command"

echo "Checking shell syntax..."
bash -n "$GRABBER"
bash -n "$CMD_WRAPPER"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/mtk-grab-test.XXXXXXXX")"
trap 'rm -rf "$TMP"' EXIT

FX="$TMP/fixture"
mkdir -p "$FX/DiagnosticReports"

cat > "$FX/kmutil.txt" <<'EOF'
  142    0 0xffffff7f95a00000 0x185000   0x185000   com.flxxxxddd.AirportMtkWlan (2.1.2) ABC123 <45 12 8 6 3 1>
  141    2 0xffffff7f95800000 0x92000    0x92000    com.apple.iokit.IO80211FamilyLegacy (1200.13.1) DEF456 <12 8 6 3 1>
EOF

cat > "$FX/ioreg_pci.txt" <<'EOF'
  +-o PXSX@0  <class IOPCIDevice, id 0x100000330, registered, matched, active>
      |   "IOName" = "pci14c3,7961"
      |   "vendor-id" = <c3140000>
      |   "device-id" = <61790000>
      |   "subsystem-id" = <80460000>
      |   "IOPlatformSerialNumber" = "C02SECRET999"
      |   "IOPlatformUUID" = "11112222-3333-4444-5555-666677778888"
      |   "MtkDebugLog" = "[1.000] AirportMtkWlan: init ok
[2.000] AirportMtkWlan: Set key request: len=32 cipher_type=4 flags=0 index=0 key=0123456789abcdef0123456789abcdef rsc=abcdef0102030405 ea=de:ad:be:ef:ca:fe
[3.000] AirportMtkWlan: PSK key check a5
"
      |   "IOPCIEjectable" = Yes
      |   "IOServiceLeakTest" = "DO_NOT_LEAK"
      | +-o CCLogStream  <class CCLogStream, id 0x100000999>
EOF
# Pad trailing ioreg output beyond pipe buffer (>70 KB) to catch SIGPIPE/Broken pipe regressions.
awk 'BEGIN { for (i = 0; i < 1200; i++) printf "      |   \"PadProp%d\" = \"trailing_ioreg_data_%04d\"\n", i, i }' >> "$FX/ioreg_pci.txt"
cp "$FX/ioreg_pci.txt" "$FX/ioreg.txt"

{
    i=1
    while [ "$i" -le 340 ]; do
        printf '2026-11-11 10:00:00.000 Df kernel: [mwx_poll] counter=%d\n' "$i"
        i=$((i + 1))
    done
    echo '2026-11-11 10:01:00.000 Df kernel: [boot] passphrase="SuperSecretPassword123" SSID="MyPrivateHomeWifi"'
} > "$FX/kernel_log.txt"

cat > "$FX/wifi_log.txt" <<'EOF'
2026-11-11 10:02:00.000 Df airportd: associating to nwid='TopSecretCorpNet' BSSID=12:34:56:78:9a:bc bcast=ff:ff:ff:ff:ff:ff zero=00:00:00:00:00:00
EOF

cat > "$FX/dmesg.txt" <<'EOF'
mtk: firmware loaded MT7921
AppleVTD: IOMMU enabled password=Hunter2
EOF

cat > "$FX/networksetup_ports.txt" <<'EOF'
Hardware Port: Wi-Fi
Device: en2
Ethernet Address: cc:47:40:aa:bb:cc
EOF
echo 'Wi-Fi Power (en2): On' > "$FX/networksetup_power.txt"
echo 'Current Wi-Fi Network: SecretCoffeeShop' > "$FX/networksetup_net.txt"

cat > "$FX/ifconfig.txt" <<'EOF'
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
	inet 127.0.0.1 netmask 0xff000000
	inet6 ::1 prefixlen 128
en2: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	ether 12:34:56:ab:cd:ef
	inet6 fe80::1234:56ff:fe78:9abc%en2 prefixlen 64 scopeid 0x8
	inet6 2001:db8::999 prefixlen 64
	inet 192.168.1.42 netmask 0xffffff00 broadcast 192.168.1.255
	inet 169.254.12.99 netmask 0xffff0000
	inet 203.0.113.77 netmask 0xffffff00
EOF

cat > "$FX/airport_sp.txt" <<'EOF'
Wi-Fi:
      Interfaces:
        en2:
          Card Type: Wi-Fi  (0x14C3, 0x7961)
          Firmware Version: itlwm: 2.1.2 fw: MT7921
          MAC Address: 12:34:56:ab:cd:ef
          Country Code: US
          Current Network Information:
            SecretSSID:
              PHY Mode: 802.11ax
              Channel: 36 (5GHz, 80MHz)
              Signal / Noise: -48 dBm / -92 dBm
          Other Local Wi-Fi Networks:
            NeighborNet1:
              PHY Mode: 802.11ax
            NeighborNet2:
              PHY Mode: 802.11ac
        awdl0:
          MAC Address: 02:11:22:33:44:55
EOF

cat > "$FX/wdutil.txt" <<'EOF'
WIFI
    SSID                 : SecretWdutilSSID
    BSSID                : aa:bb:cc:11:22:33
    RSSI                 : -48 dBm
EOF

cat > "$FX/config.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Kernel</key>
	<dict>
		<key>Add</key>
		<array>
			<dict>
				<key>BundlePath</key>
				<string>AirportMtkWlan.kext</string>
				<key>Enabled</key>
				<true/>
			</dict>
		</array>
	</dict>
	<key>PlatformInfo</key>
	<dict>
		<key>Generic</key>
		<dict>
			<key>MLB</key>
			<string>M000SECRETMLB</string>
			<key>ROM</key>
			<data>MTIzNDU2</data>
			<key>SystemSerialNumber</key>
			<string>C02PLIST123</string>
			<key>SystemUUID</key>
			<string>99998888-7777-6666-5555-444433332222</string>
		</dict>
	</dict>
</dict>
</plist>
EOF

cat > "$FX/DiagnosticReports/Kernel-mock.panic" <<'EOF'
{"panicString":"panic(cpu 0): test panic C02CRASH99","crashReporterKey":"crash-key-secret-123","serialNumber":"C02CRASH99"}
EOF

cat > "$FX/DiagnosticReports/.contents.panic" <<'EOF'
panic(cpu 1 caller 0xffffff8000123456): hidden contents panic
Serial Number: SN-PANIC-DUMP-999
EOF

cat > "$FX/DiagnosticReports/panic-full-mock.ips" <<'EOF'
{"incident":"INC-PANIC-SECRET","systemID":"SYSID-SECRET-999","panicString":"panic-full-sentinel"}
EOF

mkdir -p "$FX/PanicReporter/Sub1"
cat > "$FX/PanicReporter/Sub1/Kernel-Panic-mock.ips" <<'EOF'
{"incident":"INC-SUBPANIC-1","machineSerialNumber":"MACH-SN-SECRET-888","panicString":"nested-panic-sentinel"}
EOF

cat > "$FX/DiagnosticReports/airportd-mock.ips" <<'EOF'
{"incident":"INC-SECRET-1","crashReporterKey":"crash-key-secret-123","userID":"secretuser","procName":"airportd"}
EOF

cat > "$FX/DiagnosticReports/kernelmanagerd-mock.ips" <<'EOF'
{"incident":"INC-KM-SECRET-1","deviceID":"DEVID-SECRET-777","procName":"kernelmanagerd"}
EOF

touch -t 202611121149.40 "$FX/DiagnosticReports/Kernel-mock.panic"
touch -t 202611121149.30 "$FX/DiagnosticReports/.contents.panic"
touch -t 202611121149.20 "$FX/DiagnosticReports/panic-full-mock.ips"
touch -t 202611121149.10 "$FX/PanicReporter/Sub1/Kernel-Panic-mock.ips"
touch -t 202611121149.40 "$FX/DiagnosticReports/airportd-mock.ips"
touch -t 202611121149.30 "$FX/DiagnosticReports/kernelmanagerd-mock.ips"

cat > "$FX/last_reboot.txt" <<'EOF'
reboot    ~                         Thu Nov 12 11:48
shutdown  ~                         Thu Nov 12 11:40
EOF

cat > "$FX/nvram_panic.txt" <<'EOF'
aapl,panic-info: Error getting variable - 'aapl,panic-info': (iokit/common) data was not found
wake-failure: %00%00%00%00
EOF

cat > "$FX/shutdown_cause.txt" <<'EOF'
2026-11-12 11:48:02 kernel: (AppleSMC) Previous shutdown cause: -128
EOF

awk 'BEGIN {
    chars = "abcdefghijklmnop"
    for (i = 1; i <= 3200; i++) {
        a = substr(chars, ((i - 1) % 16) + 1, 1)
        b = substr(chars, (int((i - 1) / 16) % 16) + 1, 1)
        c = substr(chars, (int((i - 1) / 256) % 16) + 1, 1)
        printf "2026-11-12 11:05:00 kernel: (IO80211Family) filler-%s%s%s\n", c, b, a
    }
    print "2026-11-12 11:47:59 kernel: panic(cpu 2): PRE-CRASH-SENTINEL-MTK"
}' > "$FX/prev_boot_log.txt"

cat > "$FX/session.log" <<EOF
[19:00:00] Deployed AirportMtkWlan.kext from /Users/${USER:-tester}/Downloads
EOF

OUT_TAR="$TMP/out.tar.gz"
MTK_DIAG_FIXTURE_DIR="$FX" "$GRABBER" \
    --quiet \
    --no-efi \
    --timeout 30 \
    --session-log "$FX/session.log" \
    --out "$OUT_TAR"

[ -f "$OUT_TAR" ] || { echo "FAIL: output tarball missing"; exit 1; }
EXTRACT="$TMP/extracted"
mkdir -p "$EXTRACT"
tar -xzf "$OUT_TAR" -C "$EXTRACT"
BUNDLE="$(find "$EXTRACT" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -n "$BUNDLE" ] || { echo "FAIL: bundle root directory missing in tarball"; exit 1; }

# 1. Verify expected archive files
for rel in \
    00-summary.txt \
    01-system-boot.txt \
    02-hardware-pci-ioreg.txt \
    03-mtk-debug-log.txt \
    04-network-wifi-state.txt \
    05-kernel-log-boot.txt \
    06-wifi-userspace-logs.txt \
    08-efi-opencore/fixture-config.plist.xml \
    09-crashes-panics/00-panic-and-shutdown-check.txt \
    09-crashes-panics/panic-1-Kernel-mock.panic \
    09-crashes-panics/panic-2-.contents.panic \
    09-crashes-panics/panic-3-panic-full-mock.ips \
    09-crashes-panics/panic-4-Kernel-Panic-mock.ips \
    09-crashes-panics/crash-1-airportd-mock.ips \
    09-crashes-panics/crash-2-kernelmanagerd-mock.ips \
    10-installer-session.log; do
    [ -f "$BUNDLE/$rel" ] || { echo "FAIL: missing archive file $rel"; exit 1; }
done

# 2. Assert secrets are strictly redacted across the entire extracted archive
for secret in \
    0123456789abcdef0123456789abcdef \
    abcdef0102030405 \
    de:ad:be:ef:ca:fe \
    SuperSecretPassword123 \
    MyPrivateHomeWifi \
    TopSecretCorpNet \
    12:34:56:78:9a:bc \
    Hunter2 \
    SecretCoffeeShop \
    12:34:56:ab:cd:ef \
    192.168.1.42 \
    169.254.12.99 \
    203.0.113.77 \
    2001:db8::999 \
    SecretSSID \
    NeighborNet1 \
    NeighborNet2 \
    SecretWdutilSSID \
    aa:bb:cc:11:22:33 \
    C02SECRET999 \
    C02PLIST123 \
    M000SECRETMLB \
    99998888-7777-6666-5555-444433332222 \
    MTIzNDU2 \
    crash-key-secret-123 \
    INC-SECRET-1; do
    if grep -rnF "$secret" "$BUNDLE" >/dev/null 2>&1; then
        echo "FAIL: secret leaked in archive: $secret"
        grep -rnF "$secret" "$BUNDLE" || true
        exit 1
    fi
done

# 3. Assert essential telemetry & structure are preserved
grep -q "diag: mtk-pci-count 1" "$BUNDLE/00-summary.txt"
grep -q "diag: kext-loaded com.flxxxxddd.AirportMtkWlan(2.1.2)" "$BUNDLE/00-summary.txt"
grep -q "diag: panics-found 4 crashes-found 2" "$BUNDLE/00-summary.txt"
grep -q "diag: last-shutdown-cause -128" "$BUNDLE/00-summary.txt"
grep -q "Recent Boot & Shutdown History" "$BUNDLE/01-system-boot.txt"
grep -q "Previous shutdown cause: -128" "$BUNDLE/09-crashes-panics/00-panic-and-shutdown-check.txt"
grep -q "PRE-CRASH-SENTINEL-MTK" "$BUNDLE/07-previous-boot-kernel-log.txt"
grep -q "lines omitted" "$BUNDLE/07-previous-boot-kernel-log.txt"
grep -rq "hidden contents panic" "$BUNDLE/09-crashes-panics/"
grep -rq "panic-full-sentinel" "$BUNDLE/09-crashes-panics/"
grep -rq "nested-panic-sentinel" "$BUNDLE/09-crashes-panics/"
grep -rq "kernelmanagerd" "$BUNDLE/09-crashes-panics/"
! grep -rqE "SN-PANIC-DUMP-999|SYSID-SECRET-999|MACH-SN-SECRET-888|DEVID-SECRET-777" "$BUNDLE"
grep -q "pci14c3,7961" "$BUNDLE/02-hardware-pci-ioreg.txt"
grep -q "<KEY_REDACTED>" "$BUNDLE/03-mtk-debug-log.txt"
if grep -qE "IOPCIEjectable|DO_NOT_LEAK|CCLogStream|PadProp|Broken pipe|write error" "$BUNDLE/03-mtk-debug-log.txt"; then
    echo "FAIL: MtkDebugLog extraction leaked sibling ioreg nodes or pipe error"
    cat "$BUNDLE/03-mtk-debug-log.txt"
    exit 1
fi
grep -q "<RFC1918_LAN_IP>" "$BUNDLE/04-network-wifi-state.txt"
grep -q "169.254.<LINK_LOCAL>" "$BUNDLE/04-network-wifi-state.txt"
grep -q "<IPv4_REDACTED>" "$BUNDLE/04-network-wifi-state.txt"
grep -q "127.0.0.1" "$BUNDLE/04-network-wifi-state.txt"
grep -q "NEARBY_NETWORKS_REDACTED count=2" "$BUNDLE/04-network-wifi-state.txt"
grep -q "ff:ff:ff:ff:ff:ff" "$BUNDLE/06-wifi-userspace-logs.txt"
grep -q "similar lines omitted" "$BUNDLE/05-kernel-log-boot.txt"
grep -q "AirportMtkWlan.kext" "$BUNDLE/08-efi-opencore/fixture-config.plist.xml"

# 4. Assert OpenCore/panic log globbing tolerates spaces in mount paths and filenames
SPACE_EFI="$TMP/EFI Partition With Spaces"
mkdir -p "$SPACE_EFI"
printf 'oc-space-ok\n' > "$SPACE_EFI/opencore-2026-11-11 01.txt"
printf 'panic-space-ok\n' > "$SPACE_EFI/panic-2026-11-11 02.txt"
COPIED=0
OUT_SPACE="$TMP/space-efi-out"
mkdir -p "$OUT_SPACE"
find "$SPACE_EFI" -maxdepth 1 -type f \( -name 'opencore-*.txt' -o -name 'panic-*.txt' \) -exec stat -f '%m %N' {} + 2>/dev/null \
    | sort -rn | head -n 4 | cut -d' ' -f2- | while IFS= read -r lf; do
    [ -n "$lf" ] || continue
    safe_lf=$(printf '%s' "$(basename "$lf")" | tr -c 'A-Za-z0-9._-' '_')
    head -c 262144 "$lf" > "$OUT_SPACE/disk0s1-${safe_lf}"
done
grep -q "oc-space-ok" "$OUT_SPACE/disk0s1-opencore-2026-11-11_01.txt_" || grep -q "oc-space-ok" "$OUT_SPACE"/disk0s1-opencore-*
grep -q "panic-space-ok" "$OUT_SPACE"/disk0s1-panic-*

echo "PASS: grab-logs-test verified collection, verdicts, repeat squashing, and secret redaction"
