"""Guest wire/pipe/path contracts on host. Generated code never executes here."""
from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUEST = ROOT / "platform/linux/guest/atlas_guest"


def module(name: str):
    spec = importlib.util.spec_from_file_location(f"atlas_guest_test_{name}", GUEST / f"{name}.py")
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    if name == "execution":
        import shared.workspace_wire as wire
        sys.modules.setdefault("workspace_wire", wire)
    spec.loader.exec_module(loaded)
    return loaded


def test_guest_execution_refuses_host_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    guest = module("execution")
    monkeypatch.setattr(guest, "_MARKER", Path("/definitely-missing-atlas-image-marker"))
    assert guest.ExecutionBox.available() is False
    with pytest.raises(RuntimeError, match="no host execution fallback"):
        guest.ExecutionBox().run({"run_id": "valid-id-123", "code": "raise AssertionError('must never run on host')", "files": [], "timeout_s": 1})


def test_sandbox_arguments_are_fixed_no_home_credentials_network_or_host_mounts(tmp_path: Path) -> None:
    args = module("execution").sandbox_argv(tmp_path, 3)
    for requirement in ("--unshare-all", "--cap-drop", "ALL", "--clearenv", "--new-session", "--die-with-parent"):
        assert requirement in args
    assert args.count("--bind") == 1 and args[args.index("--bind") + 1] == str(tmp_path)
    assert "/home/atlas" not in args and "/Users" not in args and "--share-net" not in args
    assert args[-4:] == ["/usr/bin/python3", "-I", "-B", "/work/main.py"]


def test_output_scanner_refuses_symlink_hardlink_directory_and_fifo(tmp_path: Path) -> None:
    guest = module("execution")
    root = tmp_path / "output"
    root.mkdir()
    source = tmp_path / "private"
    source.write_text("never-import")
    (root / "sym.txt").symlink_to(source)
    os.link(source, root / "hard.txt")
    (root / "directory").mkdir()
    os.mkfifo(root / "pipe.txt")
    result, warnings = guest.ExecutionBox._outputs(root)
    assert result == [] and len(warnings) == 4


def test_pipe_does_not_bind_network_and_roundtrips_null_frames() -> None:
    pipe_type = module("cdp_pipe").CDPPipe
    r1, w1 = os.pipe()
    r2, w2 = os.pipe()
    client = pipe_type(r1, w2)
    peer = pipe_type(r2, w1)
    try:
        client.send('{"text":"ação"}')
        assert peer.recv() == '{"text":"ação"}'
        peer.send('{"id":1}')
        peer.send('{"id":2}')
        assert client.recv() == '{"id":1}'
        assert client.recv() == '{"id":2}'
    finally:
        client.close()
        peer.close()


def test_pipe_cancel_unblocks_pending_read() -> None:
    cls = module("cdp_pipe").CDPPipe
    reader, writer = os.pipe()
    out_reader, out_writer = os.pipe()
    pipe = cls(reader, out_writer)
    stopped = threading.Event()
    def read() -> None:
        try:
            pipe.recv()
        except EOFError:
            stopped.set()
    worker = threading.Thread(target=read)
    worker.start()
    time.sleep(.01)
    pipe.close()
    worker.join(1)
    os.close(writer)
    os.close(out_reader)
    assert stopped.is_set() and not worker.is_alive()


def test_pipe_rejects_embedded_null_and_oversized_request() -> None:
    pipe_module = module("cdp_pipe")
    reader, writer = os.pipe()
    pipe = pipe_module.CDPPipe(reader, writer)
    try:
        for data in ("a\0b", "x" * pipe_module.MAX_MESSAGE):
            with pytest.raises(ValueError):
                pipe.send(data)
    finally:
        pipe.close()
