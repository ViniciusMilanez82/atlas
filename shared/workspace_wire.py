"""Small, dependency-free wire contract shared by the host and the Linux appliance.

No shell commands, host paths, credentials or authority objects are accepted on this wire.
The caller's authorization remains in atlas-core; the guest can return only bounded data.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import socket
import struct
import time
from typing import Any

PROTOCOL = "atlas-workspace/1"
PORT = 4050
MAX_FRAME = 1024 * 1024
MAX_CODE = 128 * 1024
MAX_FILE = 256 * 1024
MAX_FILES = 8
MAX_TOTAL_FILES = 512 * 1024
MAX_OUTPUT = 64 * 1024
ID = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")
OPS = frozenset({"ping", "execution.run", "execution.cancel", "browser.observe", "browser.navigate",
                 "browser.click", "browser.type", "browser.cancel", "browser.reset"})


class WorkspaceProtocolError(ValueError):
    pass


def validate_name(name: Any) -> str:
    if (not isinstance(name, str) or not 1 <= len(name) <= 180 or len(name.encode()) > 512
            or not name.isprintable() or name != name.strip() or name in (".", "..")
            or any(c in name for c in ("/", "\\", ":"))):
        raise WorkspaceProtocolError("invalid workspace file name")
    return name


def bounded_bytes(encoded: Any, *, maximum: int = MAX_FILE) -> bytes:
    if not isinstance(encoded, str) or len(encoded) > (maximum + 2) // 3 * 4:
        raise WorkspaceProtocolError("file exceeds transfer limit")
    try:
        value = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise WorkspaceProtocolError("invalid base64 data") from None
    if len(value) > maximum:
        raise WorkspaceProtocolError("file exceeds transfer limit")
    return value


def validate_command(op: Any, args: Any) -> dict[str, Any]:
    if not isinstance(op, str) or op not in OPS or not isinstance(args, dict):
        raise WorkspaceProtocolError("unknown workspace operation")
    required: dict[str, set[str]] = {
        "ping": set(), "execution.run": {"run_id", "code", "files", "timeout_s"},
        "execution.cancel": {"run_id"}, "browser.observe": set(),
        "browser.navigate": {"url"}, "browser.click": {"element_id", "page_token"},
        "browser.type": {"element_id", "page_token", "text"},
        "browser.cancel": set(), "browser.reset": set(),
    }
    if set(args) != required[op]:
        raise WorkspaceProtocolError("workspace operation fields do not match the contract")
    if op.startswith("execution."):
        if not isinstance(args["run_id"], str) or not ID.fullmatch(args["run_id"]):
            raise WorkspaceProtocolError("invalid execution id")
    if op == "execution.run":
        if not isinstance(args["code"], str) or len(args["code"].encode()) > MAX_CODE:
            raise WorkspaceProtocolError("code exceeds the workspace limit")
        if type(args["timeout_s"]) is not int or not 1 <= args["timeout_s"] <= 120:
            raise WorkspaceProtocolError("execution timeout must be 1..120 seconds")
        if not isinstance(args["files"], list) or len(args["files"]) > MAX_FILES:
            raise WorkspaceProtocolError("too many input files")
        seen: set[str] = set()
        total = 0
        for item in args["files"]:
            if not isinstance(item, dict) or set(item) != {"name", "data"}:
                raise WorkspaceProtocolError("invalid input file")
            name = validate_name(item["name"])
            if name in seen or name in ("main.py", "output"):
                raise WorkspaceProtocolError("duplicate or reserved input name")
            seen.add(name)
            total += len(bounded_bytes(item["data"]))
        if total > MAX_TOTAL_FILES:
            raise WorkspaceProtocolError("input transfer exceeds the total limit")
    if op == "browser.navigate":
        url = args["url"]
        if not isinstance(url, str) or not 8 <= len(url) <= 2000 or not url.startswith(("https://", "http://")):
            raise WorkspaceProtocolError("a public http(s) URL is required")
    if op in ("browser.click", "browser.type"):
        if not isinstance(args["element_id"], str) or not re.fullmatch(r"[0-9]{1,8}", args["element_id"]):
            raise WorkspaceProtocolError("invalid observed element id")
        if not isinstance(args["page_token"], str) or not ID.fullmatch(args["page_token"]):
            raise WorkspaceProtocolError("invalid page generation")
    if op == "browser.type" and (not isinstance(args["text"], str) or len(args["text"].encode()) > 8192):
        raise WorkspaceProtocolError("input text exceeds the limit")
    return args


def send(sock: socket.socket, packet: dict[str, Any]) -> None:
    raw = json.dumps(packet, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > MAX_FRAME:
        raise WorkspaceProtocolError("workspace frame exceeds 1 MiB")
    sock.sendall(struct.pack(">I", len(raw)) + raw)


def receive(sock: socket.socket, *, deadline: float) -> dict[str, Any]:
    def exact(count: int) -> bytes:
        out = bytearray()
        while len(out) < count:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("workspace deadline expired")
            sock.settimeout(min(left, 1.0))
            try:
                part = sock.recv(min(count - len(out), 65536))
            except TimeoutError:
                continue
            if not part:
                raise EOFError("workspace connection closed")
            out.extend(part)
        return bytes(out)
    size = struct.unpack(">I", exact(4))[0]
    if not 0 < size <= MAX_FRAME:
        raise WorkspaceProtocolError("invalid workspace frame size")
    def reject_constant(value: str) -> Any:
        raise WorkspaceProtocolError("non-finite numbers are not permitted")
    try:
        result = json.loads(exact(size), parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise WorkspaceProtocolError("workspace frame is not UTF-8 JSON") from None
    if not isinstance(result, dict):
        raise WorkspaceProtocolError("workspace frame must be an object")
    return result
