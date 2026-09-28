"""Bounded host-initiated vsock service. No listener is exposed to the Internet or a LAN."""
from __future__ import annotations

import os
import socket
import threading
import time
from typing import Any

from workspace_wire import PORT, PROTOCOL, WorkspaceProtocolError, receive, send, validate_command

from atlas_guest.browser import Browser
from atlas_guest.execution import ExecutionBox


class Guest:
    def __init__(self) -> None:
        self.box = ExecutionBox()
        self.browser = Browser()
        self.connections = threading.BoundedSemaphore(4)

    def serve(self, peer: socket.socket) -> None:
        with peer:
            if not self.connections.acquire(blocking=False):
                return
            try:
                req = receive(peer, deadline=time.monotonic() + 10)
                rid = req.get("id")
                if req.get("protocol") != PROTOCOL or not isinstance(rid, str) or len(rid) > 80:
                    raise WorkspaceProtocolError("invalid guest protocol")
                op, args = req.get("op"), req.get("args")
                validate_command(op, args)
                def fetch(resource: dict[str, Any]) -> dict[str, Any]:
                    send(peer, {"kind": "network", "id": rid, "request": resource})
                    response = receive(peer, deadline=time.monotonic() + 25)
                    if response.get("id") != rid or response.get("kind") != "network-result":
                        raise WorkspaceProtocolError("uncorrelated network response")
                    value = response.get("response")
                    return value if isinstance(value, dict) else {"allowed": False}
                if op == "ping":
                    value = {"ready": True, "protocol": PROTOCOL, "execution_available": self.box.available(),
                             "guest_uid": os.getuid(), "nic": "none", "host_mounts": "none"}
                elif op == "execution.run":
                    value = self.box.run(args)
                elif op == "execution.cancel":
                    value = self.box.cancel(args["run_id"])
                else:
                    value = self.browser.perform(op, args, fetch)
                send(peer, {"kind": "result", "id": rid, "result": value})
            except Exception as exc:
                try:
                    send(peer, {"kind": "error", "id": locals().get("rid"),
                                "error": type(exc).__name__, "message": str(exc)[:300]})
                except (OSError, ValueError):
                    pass
            finally:
                self.connections.release()


def main() -> None:
    guest = Guest()
    with socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM) as server:
        server.bind((socket.VMADDR_CID_ANY, PORT))
        server.listen(4)
        while True:
            peer, address = server.accept()
            # Only the hypervisor host can control this service. Sandbox code is additionally denied
            # AF_VSOCK by seccomp, so another guest process cannot impersonate the host.
            if address[0] != socket.VMADDR_CID_HOST:
                peer.close()
                continue
            threading.Thread(target=guest.serve, args=(peer,), daemon=True).start()


if __name__ == "__main__":
    main()
