#!/bin/bash
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/.." && pwd)
BUILD_DIR="$REPO_ROOT/build/installer"
APP_BUNDLE="$BUILD_DIR/AirportMtkWlan Installer.app"
DIST_DIR="$REPO_ROOT/dist"

echo "=== Building AirportMtkWlan Installer ==="
mkdir -p "$BUILD_DIR" "$DIST_DIR"

# 1. Compile Swift executable
echo "[1/4] Compiling native Swift/SwiftUI application..."
swiftc -O -target x86_64-apple-macos14.0 \
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
if [ -f "$HERE/Resources/AppIcon.icns" ]; then
    cp "$HERE/Resources/AppIcon.icns" "$APP_BUNDLE/Contents/Resources/"
fi

# 3. Embed pre-built release kexts
echo "[3/4] Embedding release drivers into application resources..."
ditto "$REPO_ROOT/build/Release/tahoe/AirportMtkWlan.kext" "$APP_BUNDLE/Contents/Resources/kexts/tahoe/AirportMtkWlan.kext"
ditto "$REPO_ROOT/build/Release/sequoia/AirportMtkWlan.kext" "$APP_BUNDLE/Contents/Resources/kexts/sequoia/AirportMtkWlan.kext"
ditto "$REPO_ROOT/build/Release/SimpleMtkWlan.kext" "$APP_BUNDLE/Contents/Resources/kexts/SimpleMtkWlan.kext"

# Sign
codesign -s - --force --deep "$APP_BUNDLE" >/dev/null 2>&1 || true

# 4. Package distribution zip
echo "[4/4] Creating distribution archive..."
ZIP_NAME="AirportMtkWlan-Installer-v1.5.1.zip"
ditto -c -k --keepParent "$APP_BUNDLE" "$DIST_DIR/$ZIP_NAME"

APP_SIZE=$(du -sh "$APP_BUNDLE" | cut -f1)
ZIP_SIZE=$(ls -lh "$DIST_DIR/$ZIP_NAME" | awk '{print $5}')
echo "=========================================="
echo "Built: $APP_BUNDLE ($APP_SIZE)"
echo "Archive: $DIST_DIR/$ZIP_NAME ($ZIP_SIZE)"
echo "=========================================="
