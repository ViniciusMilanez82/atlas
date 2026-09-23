"""Vault backend backed by the macOS Keychain through the Supervisor's keychain service (AT-006.3).

atlas-core never links the Security framework itself: it asks the Swift service
(``platform/macos/AtlasKit/Sources/atlas-keychain-agent``) over a private Unix socket, authenticated
with a session token and the peer UID check done by the service. Secrets travel base64-encoded inside
the local frame only; they are never logged here.
"""

from __future__ import annotations

import base64
import os
import socket
import sys
from pathlib import Path

from shared.framing import recv_frame, send_frame


class KeychainAgentError(RuntimeError):
    pass


class KeychainAgentBackend:
    name = "macos-keychain"

    def __init__(self, socket_path: Path, token: str, timeout_s: float = 10.0) -> None:
        if not hasattr(socket, "AF_UNIX"):
            raise KeychainAgentError("Unix domain sockets are unavailable on this platform")
        self._path = str(socket_path)
        self._token = token
        self._timeout = timeout_s

    def _request(self, payload: dict[str, str]) -> dict[str, object]:
        if sys.platform == "win32":
            raise KeychainAgentError("the Keychain service runs only on macOS")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._timeout)
        try:
            sock.connect(self._path)
            send_frame(sock, {"hello": self._token, "protocol": "1.0"})
            if recv_frame(sock).get("hello") != "ok":
                raise KeychainAgentError("keychain service rejected the session")
            send_frame(sock, payload)
            return recv_frame(sock)
        except OSError as exc:
            raise KeychainAgentError(f"keychain service unreachable ({type(exc).__name__})") from None
        finally:
            sock.close()

    def put(self, locator: str, secret: bytes) -> None:
        resp = self._request(
            {"op": "put", "locator": locator, "secret_b64": base64.b64encode(secret).decode()}
        )
        if resp.get("ok") is not True:
            raise KeychainAgentError(f"keychain put failed: {resp.get('error')}")

    def get(self, locator: str) -> bytes | None:
        resp = self._request({"op": "get", "locator": locator})
        if resp.get("ok") is True:
            return base64.b64decode(str(resp["secret_b64"]))
        if resp.get("error") == "not_found":
            return None
        raise KeychainAgentError(f"keychain get failed: {resp.get('error')}")

    def delete(self, locator: str) -> None:
        resp = self._request({"op": "delete", "locator": locator})
        if resp.get("ok") is not True:
            raise KeychainAgentError(f"keychain delete failed: {resp.get('error')}")


def from_environment() -> KeychainAgentBackend | None:
    """Configured by the Supervisor: ATLAS_KEYCHAIN_SOCKET and ATLAS_KEYCHAIN_TOKEN_FILE (0600)."""
    if sys.platform != "darwin":
        return None
    sock = os.environ.get("ATLAS_KEYCHAIN_SOCKET")
    token_file = os.environ.get("ATLAS_KEYCHAIN_TOKEN_FILE")
    if not sock or not token_file:
        return None
    token = Path(token_file).read_text(encoding="utf-8").strip()
    return KeychainAgentBackend(Path(sock), token)
