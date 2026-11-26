#!/bin/bash
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/.." && pwd)
BUILD_DIR="$REPO_ROOT/build/installer"
APP_BUNDLE="$BUILD_DIR/AirportMtkWlan Installer.app"
DIST_DIR="$REPO_ROOT/dist"

echo "=== Building AirportMtkWlan Installer ==="
mkdir -p "$BUILD_DIR" "$DIST_DIR"

VERSION="${1:-2.3.1}"
WIFI_ONLY="${WIFI_ONLY:-1}"
if [ "${AWDL:-0}" = "1" ]; then
    WIFI_ONLY=0
fi

SWIFT_FLAGS="-O -target x86_64-apple-macos14.0"
if [ "$WIFI_ONLY" = "1" ]; then
    SWIFT_FLAGS="$SWIFT_FLAGS -DMTK_WIFI_ONLY"
    ZIP_NAME="AirportMtkWlan-WiFi-Installer-v${VERSION}.zip"
    echo "Mode: Wi-Fi Only (Bluetooth untouched, AWDL disabled)"
else
    SWIFT_FLAGS="$SWIFT_FLAGS -DMTK_AWDL_BETA"
    ZIP_NAME="AirportMtkWlan-AWDL-Beta-Installer-v${VERSION}.zip"
    echo "Mode: AWDL Beta (Wi-Fi + Experimental AWDL)"
fi

# 1. Compile Swift executable
echo "[1/4] Compiling native Swift/SwiftUI application..."
swiftc $SWIFT_FLAGS \
    -framework SwiftUI -framework AppKit -framework Foundation \
    "$HERE/Sources/main.swift" \
    "$HERE/Sources/EFIManager.swift" \
    "$HERE/Sources/InstallerApp.swift" \
    -o "$BUILD_DIR/AirportMtkWlan Installer"

# 2. Assemble .app bundle
echo "[2/4] Assembling application bundle..."
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources/kexts/tahoe"
mkdir -p "$APP_BUNDLE/Contents/Resources/kexts/sequoia"

cp "$BUILD_DIR/AirportMtkWlan Installer" "$APP_BUNDLE/Contents/MacOS/"
cp "$HERE/Resources/Info.plist" "$APP_BUNDLE/Contents/"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP_BUNDLE/Contents/Info.plist" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$APP_BUNDLE/Contents/Info.plist" >/dev/null 2>&1 || true
if [ -f "$HERE/Resources/AppIcon.icns" ]; then
    cp "$HERE/Resources/AppIcon.icns" "$APP_BUNDLE/Contents/Resources/"
fi
if [ -f "$HERE/Resources/AppIcon.png" ]; then
    cp "$HERE/Resources/AppIcon.png" "$APP_BUNDLE/Contents/Resources/"
fi
if [ -f "$HERE/../tools/mtk-grab-logs.sh" ]; then
    cp "$HERE/../tools/mtk-grab-logs.sh" "$APP_BUNDLE/Contents/Resources/mtk-grab-logs.sh"
    chmod +x "$APP_BUNDLE/Contents/Resources/mtk-grab-logs.sh"
fi

# 3. Embed pre-built release Wi-Fi drivers into application resources
echo "[3/4] Embedding release Wi-Fi drivers into application resources..."
ditto "$REPO_ROOT/build/Release/tahoe/AirportMtkWlan.kext" "$APP_BUNDLE/Contents/Resources/kexts/tahoe/AirportMtkWlan.kext"
ditto "$REPO_ROOT/build/Release/sequoia/AirportMtkWlan.kext" "$APP_BUNDLE/Contents/Resources/kexts/sequoia/AirportMtkWlan.kext"
ditto "$REPO_ROOT/build/Release/SimpleMtkWlan.kext" "$APP_BUNDLE/Contents/Resources/kexts/SimpleMtkWlan.kext"

# Sign
codesign -s - --force --deep "$APP_BUNDLE" >/dev/null 2>&1 || true

# 4. Package distribution zip
echo "[4/4] Creating distribution archive..."
ditto -c -k --keepParent "$APP_BUNDLE" "$DIST_DIR/$ZIP_NAME"

APP_SIZE=$(du -sh "$APP_BUNDLE" | cut -f1)
ZIP_SIZE=$(ls -lh "$DIST_DIR/$ZIP_NAME" | awk '{print $5}')
echo "=========================================="
echo "Built: $APP_BUNDLE ($APP_SIZE)"
echo "Archive: $DIST_DIR/$ZIP_NAME ($ZIP_SIZE)"
echo "=========================================="
