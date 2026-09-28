#!/usr/bin/env bash
# Controlled image build ONLY on a disposable native arm64 GitHub runner.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted && $(uname -m) == aarch64 && $EUID == 0 ]] || { echo 'Run only in disposable arm64 build CI as root.' >&2; exit 2; }
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:?output directory}"
[[ "$OUT" == "$RUNNER_TEMP"/* && ! -e "$OUT" ]] || { echo 'Refusing existing/unscoped build output.' >&2; exit 2; }
mkdir -p "$OUT"
WORK="$(mktemp -d "$RUNNER_TEMP/atlas-image.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
ROOT="$WORK/root"
mkdir -p "$ROOT"
ARCHIVE=alpine-minirootfs-3.24.2-aarch64.tar.gz
BASE=https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/aarch64
curl --proto '=https' --tlsv1.2 -fsSL "$BASE/$ARCHIVE" -o "$WORK/$ARCHIVE"
curl --proto '=https' --tlsv1.2 -fsSL "$BASE/$ARCHIVE.sha256" -o "$WORK/$ARCHIVE.sha256"
(cd "$WORK" && sha256sum -c "$ARCHIVE.sha256")
cp "$WORK/$ARCHIVE.sha256" "$OUT/alpine-source.sha256"
# The initial build records the vendor checksum; distributed images are pinned to the resulting
# manifest and source checksum. A recorded lock in the repository must match on subsequent builds.
cmp "$OUT/alpine-source.sha256" "$REPO/packaging/workspace/alpine-source.sha256"
tar -xzf "$WORK/$ARCHIVE" -C "$ROOT" --numeric-owner
cp /etc/resolv.conf "$ROOT/etc/resolv.conf"
printf '%s\n' 'https://dl-cdn.alpinelinux.org/alpine/v3.24/main' 'https://dl-cdn.alpinelinux.org/alpine/v3.24/community' > "$ROOT/etc/apk/repositories"
# apk verifies repository/package signatures against the vendor keys in the root filesystem.
chroot "$ROOT" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root /sbin/apk add --no-cache linux-virt mkinitfs python3 chromium bubblewrap libseccomp e2fsprogs e2fsprogs-extra util-linux build-base libseccomp-dev
mkdir -p "$ROOT/usr/lib/atlas" "$ROOT/usr/libexec"
cp -R "$REPO/platform/linux/guest/atlas_guest" "$ROOT/usr/lib/atlas/"
find "$ROOT/usr/lib/atlas" -type d -name __pycache__ -prune -exec rm -rf {} +
cp "$REPO/shared/workspace_wire.py" "$ROOT/usr/lib/atlas/workspace_wire.py"
cp "$REPO/platform/linux/guest/entry.py" "$ROOT/usr/lib/atlas/entry.py"
cp "$REPO/platform/linux/guest/exec_guard.c" "$ROOT/tmp/exec_guard.c"
chroot "$ROOT" /usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/cc -O2 -Wall -Wextra -Werror /tmp/exec_guard.c -lseccomp -o /usr/libexec/atlas-exec-guard
cp "$REPO/platform/linux/guest/chromium_launcher.c" "$ROOT/tmp/chromium_launcher.c"
chroot "$ROOT" /usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/cc -O2 -Wall -Wextra -Werror /tmp/chromium_launcher.c -o /usr/libexec/atlas-chromium-launch
rm "$ROOT/tmp/exec_guard.c" "$ROOT/tmp/chromium_launcher.c"
chroot "$ROOT" /sbin/apk del build-base libseccomp-dev
chroot "$ROOT" /usr/sbin/adduser -D -u 1000 -h /home/atlas -s /bin/sh atlas
cp "$REPO/platform/linux/guest/atlas-init" "$ROOT/sbin/atlas-init"
chmod 755 "$ROOT/sbin/atlas-init" "$ROOT/usr/libexec/atlas-exec-guard"
echo 'atlas-workspace/1' > "$ROOT/etc/atlas-guest-image"
# No DNS/internet configuration is carried into the running guest.
: > "$ROOT/etc/resolv.conf"
printf 'features="base virtio ext4"\n' > "$ROOT/etc/mkinitfs/mkinitfs.conf"
KVER="$(find "$ROOT/lib/modules" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | head -1)"
chroot "$ROOT" /sbin/mkinitfs -c /etc/mkinitfs/mkinitfs.conf -o /boot/initramfs-atlas "$KVER"
cp "$ROOT/boot/initramfs-atlas" "$OUT/initrd"
python3 - "$ROOT/boot/vmlinuz-virt" "$OUT/kernel" <<'PY'
import gzip,sys
from pathlib import Path
raw=Path(sys.argv[1]).read_bytes()
Path(sys.argv[2]).write_bytes(gzip.decompress(raw) if raw[:2]==b'\x1f\x8b' else raw)
PY
chroot "$ROOT" /sbin/apk info -v | sort > "$OUT/apk-packages.lock"
cp "$ROOT/lib/apk/db/installed" "$OUT/apk-installed-metadata.txt"
# Keep only the kernel modules in the appliance; boot artifacts are supplied separately by the host.
rm -rf "$ROOT/boot" "$ROOT/var/cache/apk" "$ROOT/root/.cache"
mkdir -p "$ROOT/boot" "$ROOT/tmp" "$ROOT/run" "$ROOT/var" "$ROOT/dev" "$ROOT/proc" "$ROOT/sys"
truncate -s 1536M "$OUT/rootfs.raw"
mkfs.ext4 -q -F -L ATLASROOT -d "$ROOT" "$OUT/rootfs.raw"
python3 - "$OUT" <<'PY'
import hashlib,json,os,sys
from pathlib import Path
p=Path(sys.argv[1])
def sha(file):
 h=hashlib.sha256()
 with file.open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
m={'protocol':'atlas-workspace/1','architecture':'aarch64','source_commit':os.environ.get('GITHUB_SHA'),
   'alpine':'3.24.2','files':{n:sha(p/n) for n in ['kernel','initrd','rootfs.raw']},
   'package_inventory_sha256':sha(p/'apk-packages.lock'),'production_signed':False}
(p/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
PY
# Test appliance includes a test-only program; the released root does NOT include it.
cp "$REPO/platform/linux/guest/selftest.py" "$ROOT/usr/lib/atlas/selftest.py"
truncate -s 1536M "$OUT/test-rootfs.raw"
mkfs.ext4 -q -F -L ATLASTEST -d "$ROOT" "$OUT/test-rootfs.raw"
chown -R "${SUDO_UID:-1001}:${SUDO_GID:-1001}" "$OUT"
echo "Guest built. SHA-256 rootfs: $(sha256sum "$OUT/rootfs.raw" | cut -d' ' -f1)"
