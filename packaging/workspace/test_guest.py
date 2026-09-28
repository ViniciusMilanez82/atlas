"""Boot the actual ARM appliance without a NIC, and require guest negative tests to pass."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.uname().machine != "aarch64":
        raise SystemExit("Guest test runs in the disposable native arm64 CI environment.")
    args.evidence.mkdir(parents=True, exist_ok=True)
    data = args.evidence / "synthetic-data.raw"
    with data.open("xb") as stream:
        stream.truncate(512 * 1024 * 1024)
    accelerated = os.access("/dev/kvm", os.R_OK | os.W_OK)
    command = ["qemu-system-aarch64", "-machine", "virt", "-cpu", "host" if accelerated else "cortex-a72",
               "-accel", "kvm" if accelerated else "tcg", "-m", "2048", "-smp", "2", "-nographic", "-nic", "none",
               "-no-reboot", "-kernel", str(args.images / "kernel"), "-initrd", str(args.images / "initrd"),
               "-append", "console=ttyAMA0 root=/dev/vda rootfstype=ext4 ro init=/sbin/atlas-init atlas_selftest=1 modules=virtio_pci,virtio_blk,ext4",
               "-drive", f"file={args.images / 'test-rootfs.raw'},format=raw,if=virtio,readonly=on",
               "-drive", f"file={data},format=raw,if=virtio"]
    log = args.evidence / "guest-boot-test.log"
    try:
        with log.open("wb") as stream:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, timeout=600, check=False)
        text = log.read_text(errors="replace")
        results = [line.split("ATLAS_SELFTEST_JSON ", 1)[1] for line in text.splitlines() if "ATLAS_SELFTEST_JSON " in line]
        if result.returncode != 0 or "ATLAS_GUEST_SELFTEST_PASS" not in text or not results:
            print(text[-20000:])
            raise SystemExit("Actual appliance tests did not pass; do not distribute this image.")
        detail = json.loads(results[-1])
        detail.update({"hypervisor": "qemu-kvm" if accelerated else "qemu-tcg", "macOS_virtualization_tested": False,
                       "image_commit": os.environ.get("GITHUB_SHA"), "network_adapter": False})
        (args.evidence / "guest-test-results.json").write_text(json.dumps(detail, indent=2) + "\n")
        print(json.dumps(detail, indent=2))
    finally:
        data.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
