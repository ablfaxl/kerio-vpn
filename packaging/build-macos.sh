#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD="$ROOT/build/macos"
APP="$ROOT/dist/Kerio VPN.app"

if [ -d /Applications/Xcode.app ]; then
    export DEVELOPER_DIR=/Applications/Xcode.app
fi

if ! xcodebuild -license check >/dev/null 2>&1; then
    echo "Xcode license is not accepted. Run: sudo DEVELOPER_DIR=/Applications/Xcode.app xcodebuild -license accept" >&2
    exit 2
fi

export CLANG_MODULE_CACHE_PATH="$BUILD/clang-cache"
mkdir -p "$BUILD"
xcrun swiftc -O -parse-as-library -Xfrontend -disable-sandbox \
    "$ROOT/macos/Sources/KerioVPNMac/KerioVPNMacApp.swift" \
    -o "$BUILD/KerioVPNMac" -framework SwiftUI -framework AppKit
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BUILD/KerioVPNMac" "$APP/Contents/MacOS/KerioVPNMac"
cp "$ROOT/macos/Info.plist" "$APP/Contents/Info.plist"
xcrun actool "$ROOT/data/macos/Assets.xcassets" \
    --compile "$APP/Contents/Resources" --platform macosx \
    --minimum-deployment-target 13.0 --app-icon AppIcon \
    --output-partial-info-plist "$BUILD/asset-info.plist"
codesign --force --deep --sign - "$APP"
printf 'Built %s\n' "$APP"
