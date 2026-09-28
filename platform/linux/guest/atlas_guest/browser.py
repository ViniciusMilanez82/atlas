"""Chromium inside the Linux guest, driven through its local DevTools Protocol.

There is no virtual network card. Every intercepted HTTP request must be fulfilled by the host's
mediator on the current operation's authenticated channel. WebSockets, downloads and bypass requests
cannot fall back to a direct connection. No generated JavaScript/evaluate API is exposed.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from atlas_guest.cdp_pipe import CDPPipe

PROFILE = Path("/home/atlas/browser")
LAUNCHER = "/usr/libexec/atlas-chromium-launch"


class Browser:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self.process: subprocess.Popen[bytes] | None = None
        self.ws: Any = None
        self.session: str | None = None
        self._number = 0
        self._replies: dict[int, dict[str, Any]] = {}
        self._awaited: set[int] = set()
        self._epoch = 0
        self._page_token = uuid.uuid4().hex
        self._nodes: dict[str, int] = {}
        self._pending_network: list[dict[str, Any]] = []
        self._blocked = 0
        self._page_url = "about:blank"
        self._load_finished = False

    def cancel(self) -> dict[str, Any]:
        # Independent of the action lock: cancellation cannot wait behind a page load or a callback.
        with self._state_lock:
            self._epoch += 1
            proc, self.process = self.process, None
            ws, self.ws = self.ws, None
            self.session = None
            self._nodes.clear()
        if ws is not None:
            try:
                ws.close()
            except (OSError, RuntimeError):
                # Process termination below is the independent final cancellation boundary.
                ws = None
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)
        return {"stopped": True, "profile_preserved": True}

    def _start(self, deadline: float) -> None:
        if self.ws is not None and self.process is not None and self.process.poll() is None:
            return
        if os.geteuid() == 0 or not Path("/etc/atlas-guest-image").is_file():
            raise RuntimeError("browser requires the non-root isolated Linux appliance")
        PROFILE.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._state_lock:
            epoch = self._epoch
        guest_read, parent_write = os.pipe()
        parent_read, guest_write = os.pipe()
        try:
            # All argv entries are fixed paths or trusted inherited descriptor numbers, not page input.
            proc = subprocess.Popen(  # noqa: S603
                [LAUNCHER, str(guest_read), str(guest_write)], pass_fds=(guest_read, guest_write),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True,
                env={"PATH": "/usr/bin:/bin", "HOME": "/home/atlas", "LANG": "C.UTF-8"})
        except Exception:
            os.close(parent_read)
            os.close(parent_write)
            raise
        finally:
            os.close(guest_read)
            os.close(guest_write)
        pipe = CDPPipe(parent_read, parent_write)
        with self._state_lock:
            if epoch != self._epoch:
                pipe.close()
                if proc.poll() is None:
                    os.killpg(proc.pid, 9)
                proc.wait(timeout=5)
                raise RuntimeError("browser startup was cancelled")
            self.process, self.ws = proc, pipe
        self._number = 0
        self._replies.clear()
        self._awaited.clear()
        self._pending_network.clear()
        self.session = None
        target = self._call("Target.createTarget", {"url": "about:blank"}, deadline, None)["targetId"]
        self.session = self._call("Target.attachToTarget", {"targetId": target, "flatten": True}, deadline, None)["sessionId"]
        self._call("Page.enable", {}, deadline, None)
        self._call("DOM.enable", {}, deadline, None)
        self._call("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}],
                                    "handleAuthRequests": True}, deadline, None)
        self._call("Browser.setDownloadBehavior", {"behavior": "deny"}, deadline, None, browser_level=True)
        self._page_token = uuid.uuid4().hex
        self._page_url = "about:blank"

    def _send(self, method: str, params: dict[str, Any], *, browser_level: bool = False) -> int:
        self._number += 1
        message: dict[str, Any] = {"id": self._number, "method": method, "params": params}
        if self.session is not None and not browser_level:
            message["sessionId"] = self.session
        if self.ws is None:
            raise RuntimeError("browser was stopped")
        self.ws.send(json.dumps(message))
        return self._number

    def _event(self, packet: dict[str, Any]) -> None:
        if "id" in packet:
            if packet["id"] in self._awaited:
                self._replies[packet["id"]] = packet
            if len(self._replies) > 100:
                raise RuntimeError("browser response queue limit")
            return
        method = packet.get("method")
        data = packet.get("params", {})
        if method == "Fetch.requestPaused":
            self._pending_network.append(data)
            if len(self._pending_network) > 100:
                raise RuntimeError("page exceeded request queue limit")
        elif method == "Fetch.authRequired":
            self._send("Fetch.continueWithAuth", {"requestId": data["requestId"],
                                                 "authChallengeResponse": {"response": "CancelAuth"}})
        elif method == "Page.loadEventFired":
            self._load_finished = True
        elif method == "Page.frameNavigated" and not data.get("frame", {}).get("parentId"):
            self._page_token = uuid.uuid4().hex
            self._nodes.clear()
            self._page_url = str(data.get("frame", {}).get("url", "about:blank"))[:2000]

    def _receive(self, deadline: float) -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("browser operation deadline expired")
        if self.ws is None:
            raise RuntimeError("browser stopped")
        try:
            data = self.ws.recv()
        except TimeoutError:
            return
        if not data:
            raise EOFError("browser closed")
        self._event(json.loads(data))

    def _network(self, fetch: Callable[[dict[str, Any]], dict[str, Any]] | None) -> None:
        pending, self._pending_network = self._pending_network, []
        for event in pending:
            request = event.get("request", {})
            response: dict[str, Any] = {}
            if fetch is not None:
                # No cookies or authentication headers ever leave this initial public-research browser.
                # Authenticated workflows need the separate account-scoped transport, not header forwarding.
                response = fetch({"url": str(request.get("url", ""))[:2001],
                                  "method": str(request.get("method", "")),
                                  "resource_type": str(event.get("resourceType", "")),
                                  "has_body": bool(request.get("postData"))})
            if response.get("allowed") is True:
                self._send("Fetch.fulfillRequest", {"requestId": event["requestId"],
                    "responseCode": response["status"], "body": response["body"],
                    "responseHeaders": response["headers"]})
            else:
                self._blocked += 1
                self._send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "BlockedByClient"})

    def _call(self, method: str, params: dict[str, Any], deadline: float,
              fetch: Callable[[dict[str, Any]], dict[str, Any]] | None, *, browser_level: bool = False) -> dict[str, Any]:
        number = self._send(method, params, browser_level=browser_level)
        self._awaited.add(number)
        try:
            while number not in self._replies:
                self._network(fetch)
                self._receive(deadline)
            packet = self._replies.pop(number)
        finally:
            self._awaited.discard(number)
        if "error" in packet:
            raise RuntimeError("browser rejected the operation: " + str(packet["error"].get("message", ""))[:150])
        return packet.get("result", {})

    def _observe(self, deadline: float, fetch: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        value = self._call("Runtime.evaluate", {"expression":
            "JSON.stringify({title:document.title,url:location.href,text:(document.body?.innerText||'').slice(0,24000),partial:(document.body?.innerText||'').length>24000})",
            "returnByValue": True}, deadline, fetch)
        content = json.loads(value.get("result", {}).get("value", "{}"))
        root = self._call("DOM.getDocument", {"depth": 0}, deadline, fetch)["root"]["nodeId"]
        nodes = self._call("DOM.querySelectorAll", {"nodeId": root,
            "selector": "a[href],button,input:not([type=password]):not([type=hidden]),textarea,select,[role=button]"}, deadline, fetch)["nodeIds"]
        self._nodes.clear()
        items: list[dict[str, Any]] = []
        for index, node in enumerate(nodes[:60]):
            detail = self._call("DOM.describeNode", {"nodeId": node}, deadline, fetch)["node"]
            attributes = detail.get("attributes", [])
            attrs = dict(zip(attributes[0::2], attributes[1::2], strict=True))
            name = str(attrs.get("aria-label", attrs.get("title", attrs.get("placeholder", ""))))[:160]
            try:
                ax = self._call("Accessibility.getPartialAXTree", {"nodeId": node, "fetchRelatives": False}, deadline, fetch)
                if ax.get("nodes"):
                    name = str(ax["nodes"][0].get("name", {}).get("value", name))[:160]
            except RuntimeError:
                pass
            key = str(index + 1)
            self._nodes[key] = detail["backendNodeId"]
            items.append({"id": key, "tag": detail["nodeName"], "name": name,
                          "href": str(attrs.get("href", ""))[:500], "type": str(attrs.get("type", ""))[:30]})
        shot = self._call("Page.captureScreenshot", {"format": "jpeg", "quality": 45,
                                                    "captureBeyondViewport": False}, deadline, fetch).get("data", "")
        if len(shot) > 512 * 1024:
            shot = ""
        return {"title": str(content.get("title", ""))[:300], "url": str(content.get("url", ""))[:2000],
                "text": str(content.get("text", ""))[:24000], "page_token": self._page_token,
                "text_is_partial": content.get("partial", True), "elements": items, "screenshot_jpeg": shot, "blocked_requests": self._blocked,
                "scope": "public research only; no authenticated requests or form submission",
                "trust": "untrusted"}

    def perform(self, op: str, args: dict[str, Any], fetch: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        if op in ("browser.cancel", "browser.reset"):
            return self.cancel()
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("browser is busy; retry after the current operation or cancel")
        try:
            deadline = time.monotonic() + 45
            self._blocked = 0
            self._start(deadline)
            # Unfulfilled background requests from the previous operation never inherit a new authority.
            self._network(None)
            if op == "browser.navigate":
                self._nodes.clear()
                self._page_token = uuid.uuid4().hex
                self._load_finished = False
                self._call("Page.navigate", {"url": args["url"]}, deadline, fetch)
                until = min(deadline - 5, time.monotonic() + 20)
                while not self._load_finished and time.monotonic() < until:
                    self._network(fetch)
                    self._receive(until)
            elif op in ("browser.click", "browser.type"):
                if args["page_token"] != self._page_token or args["element_id"] not in self._nodes:
                    raise RuntimeError("page changed; observe again before interacting")
                node = self._nodes[args["element_id"]]
                self._call("DOM.focus", {"backendNodeId": node}, deadline, fetch)
                if op == "browser.type":
                    self._call("Input.insertText", {"text": args["text"]}, deadline, fetch)
                else:
                    box = self._call("DOM.getBoxModel", {"backendNodeId": node}, deadline, fetch)["model"]["content"]
                    x, y = (box[0] + box[4]) / 2, (box[1] + box[5]) / 2
                    for event in ("mousePressed", "mouseReleased"):
                        self._call("Input.dispatchMouseEvent", {"type": event, "x": x, "y": y,
                                   "button": "left", "clickCount": 1}, deadline, fetch)
                self._page_token = uuid.uuid4().hex
                self._nodes.clear()
            return self._observe(deadline, fetch)
        finally:
            self._lock.release()
