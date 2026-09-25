#!/usr/bin/env bash
# Builds a DEVELOPMENT Atlas.app (Apple Silicon): Swift app + Keychain service + embedded Python
# runtime + atlas-core sources + pinned runtime dependencies. Ad-hoc signed only: NOT signed with a
# Developer ID and NOT notarized (M16 requires D-07). The owner does not need Python, Docker or a terminal
# to run it, but Gatekeeper will ask for confirmation on first open because it is not notarized.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$ROOT/dist}"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14%2B20260901-aarch64-apple-darwin-install_only.tar.gz"
PBS_SHA256="3ee3ee547cedfeb7c2b16b2b7156039f7b470bb8f857e226fd3d2eb11db83c76"

swift build -c release --package-path "$ROOT/platform/macos/AtlasKit"
BIN="$(swift build -c release --package-path "$ROOT/platform/macos/AtlasKit" --show-bin-path)"

APP="$OUT/Atlas.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/core-src"
cp "$BIN/AtlasApp" "$APP/Contents/MacOS/Atlas"
cp "$BIN/atlas-keychain-agent" "$APP/Contents/MacOS/atlas-keychain-agent"

TMP="$(mktemp -d)"
curl -fsSL "$PBS_URL" -o "$TMP/python.tgz"
echo "$PBS_SHA256  $TMP/python.tgz" | shasum -a 256 -c -
tar -xzf "$TMP/python.tgz" -C "$APP/Contents/Resources"   # -> Resources/python
"$APP/Contents/Resources/python/bin/python3" -m pip install --quiet --no-deps --only-binary=:all: \
  --target "$APP/Contents/Resources/site-packages" -r "$ROOT/packaging/macos/runtime-requirements.lock"
# N23: SBOM of what really ships (fails if the installed runtime differs from the lock).
"$APP/Contents/Resources/python/bin/python3" "$ROOT/scripts/sbom.py"   --lock "$ROOT/packaging/macos/runtime-requirements.lock" --site "$APP/Contents/Resources/site-packages"   --out "$APP/Contents/Resources/sbom.cdx.json"

for pkg in shared storage security runtime core config; do
  cp -R "$ROOT/$pkg" "$APP/Contents/Resources/core-src/$pkg"
done
find "$APP/Contents/Resources/core-src" -name "__pycache__" -type d -prune -exec rm -rf {} +

VERSION="$(cd "$ROOT" && git describe --always --dirty 2>/dev/null || echo dev)"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Atlas</string>
  <key>CFBundleDisplayName</key><string>Atlas</string>
  <key>CFBundleIdentifier</key><string>com.atlas.digital-employee.dev</string>
  <key>CFBundleExecutable</key><string>Atlas</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>15.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --deep --sign - "$APP"
rm -rf "$TMP"
echo "built $APP ($VERSION, ad-hoc signed, not notarized)"
