#!/usr/bin/env bash
# Native, offline DEVELOPMENT installer. No pre/postinstall scripts and no policy bypass.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="${1:?usage: build_installer.sh /path/Atlas.app /path/output build-number}"
OUT="${2:?output directory required}"
BUILD="${3:?positive build number required}"
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || { echo "Build on an Apple Silicon Mac." >&2; exit 2; }
[[ -d "$APP" && ! -L "$APP" ]] || { echo "A real Atlas.app is required." >&2; exit 2; }
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
PKG="$OUT/Atlas-Instalador-Alpha-AppleSilicon.pkg"
DMG="$OUT/Atlas-Instalador-Alpha-AppleSilicon.dmg"
[[ ! -e "$PKG" && ! -e "$DMG" ]] || { echo "Refusing to overwrite an existing installer." >&2; exit 2; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
python3 "$ROOT/packaging/macos/prepare_installer.py" --app "$APP" --work "$WORK" --build "$BUILD"
for binary in "$APP/Contents/MacOS/Atlas" "$APP/Contents/MacOS/atlas-keychain-agent" "$APP/Contents/Resources/python/bin/python3"; do
  lipo "$binary" -verify_arch arm64
done
codesign --verify --deep --strict "$APP"
mkdir -p "$WORK/root/Applications" "$WORK/disk"
ditto "$APP" "$WORK/root/Applications/Atlas.app"
pkgbuild --root "$WORK/root" --install-location / --ownership recommended \
  --component-plist "$WORK/components.plist" --identifier com.atlas.digital-employee.dev.installer \
  --version "$(cat "$WORK/package-version.txt")" "$WORK/AtlasComponent.pkg"
productbuild --distribution "$WORK/Distribution.xml" \
  --resources "$ROOT/packaging/macos/installer-resources" --package-path "$WORK" "$PKG"
# The user sees one native Installer package plus a short, offline, Portuguese guide.
cp "$PKG" "$WORK/disk/Instalar Atlas.pkg"
cp "$ROOT/packaging/macos/installer-resources/ReadMe.html" "$WORK/disk/LEIA ANTES.html"
hdiutil create -volname "Atlas - Instalar" -srcfolder "$WORK/disk" -fs HFS+ -format UDZO "$DMG"
hdiutil verify "$DMG"
cp "$WORK/bundle-manifest.json" "$OUT/bundle-manifest.json"
cp "$WORK/Distribution.xml" "$OUT/Distribution.xml"
printf '%s\n' 'DEVELOPMENT ALPHA — no Developer ID signature, no notarization, not complete V1.' > "$OUT/BUILD_STATUS.txt"
(cd "$OUT" && shasum -a 256 "$(basename "$PKG")" "$(basename "$DMG")" > SHA256SUMS.txt)
echo "Built native Alpha installers. Installation itself is offline; no API credential is included."
