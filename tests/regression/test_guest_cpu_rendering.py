"""CPU compositor configuration. Real render/screenshot remains a mandatory guest boot test."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_guest_browser_uses_cpu_rendering_without_weakening_sandbox() -> None:
    launcher = (ROOT / "platform/linux/guest/chromium_launcher.c").read_text()
    assert '"--disable-gpu"' in launcher
    assert '"--disable-software-rasterizer"' in launcher
    assert '"--remote-debugging-pipe"' in launcher
    assert "getuid() == 0" in launcher
    for forbidden in ("--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu-sandbox",
                      "--remote-debugging-port", "--single-process"):
        assert forbidden not in launcher
