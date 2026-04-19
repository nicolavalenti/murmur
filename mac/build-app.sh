#!/bin/bash
# Builds Murmur.app — a double-clickable macOS app bundle.
#
# What this produces: a folder named Murmur.app with this structure:
#   Murmur.app/Contents/MacOS/Murmur       (the compiled Swift binary)
#   Murmur.app/Contents/Info.plist         (app metadata)
#
# macOS treats any folder ending in .app with this layout as an application.
# Drag it to /Applications and double-click to launch.
#
# The Python backend is NOT bundled. The app expects a working venv at:
#   ~/Projects/murmur/backend/.venv
# (override with MURMUR_BACKEND_DIR env var).

set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="Murmur"
BUILD_DIR="build"
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"

echo "→ Building release binary..."
swift build -c release

echo "→ Assembling $APP_BUNDLE..."
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

cp ".build/release/$APP_NAME" "$APP_BUNDLE/Contents/MacOS/$APP_NAME"
cp "Info.plist" "$APP_BUNDLE/Contents/Info.plist"
cp "AppIcon.icns" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
cp "murmur_menubar.png" "$APP_BUNDLE/Contents/Resources/murmur_menubar.png"
cp "murmur_menubar@2x.png" "$APP_BUNDLE/Contents/Resources/murmur_menubar@2x.png"

# Sign with a persistent local cert so macOS Accessibility permission survives rebuilds.
# One-time setup: open Keychain Access → Certificate Assistant → Create a Certificate
# → Name: "Murmur Dev", Type: Code Signing, Identity: Self Signed Root.
echo "→ Signing..."
if security find-certificate -c "Murmur Dev" ~/Library/Keychains/login.keychain-db &>/dev/null; then
    codesign --force --deep --sign "Murmur Dev" "$APP_BUNDLE"
else
    echo "   (no 'Murmur Dev' cert found — falling back to ad-hoc)"
    codesign --force --deep --sign - "$APP_BUNDLE"
fi

echo ""
echo "✅ Built $APP_BUNDLE"
echo ""
echo "To install:"
echo "  mv $APP_BUNDLE /Applications/"
echo ""
echo "Then double-click Murmur in /Applications (or Spotlight: 'Murmur')."
echo "On first launch macOS will ask for Microphone + Accessibility permission."
echo ""
echo "The menu-bar icon (waveform) shows it's running. Hold ⌃⌥Space to dictate."
