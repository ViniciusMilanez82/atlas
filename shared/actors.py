"""Authenticated actors. Built by the channel layer from authenticated sessions, never from
request bodies (spec 13.4: do not trust an arbitrary actor_id in the payload)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    """Authenticated actor. Constructed by the channel layer, never from request bodies."""

    kind: str  # owner | device | runtime | worker | supervisor | control_plane | system
    id: str
    channel: str = "system"  # local_app | paired_device | internal | system
    strong_auth: bool = False  # e.g. local confirmation with device authentication


SYSTEM = Actor("system", "atlas-core", "system")
