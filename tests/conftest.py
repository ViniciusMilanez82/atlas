from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from shared.actors import Actor
from shared.clock import ManualClock
from storage.repositories.identity import Employee, create_employee, create_owner
from storage.store import open_store


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tests marked ``macos`` are NOT EXECUTED outside a real Mac; say so explicitly."""
    if sys.platform == "darwin":
        return
    skip = pytest.mark.skip(reason="NAO EXECUTADO (not executed): requires a real macOS host (D-01)")
    for item in items:
        if "macos" in item.keywords:
            item.add_marker(skip)


@dataclass
class World:
    conn: sqlite3.Connection
    clock: ManualClock
    owner_id: str
    employee: Employee
    path: Path

    @property
    def owner(self) -> Actor:
        return Actor("owner", self.owner_id, "local_app", strong_auth=True)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def world(tmp_path: Path, clock: ManualClock) -> Iterator[World]:
    path = tmp_path / "atlas.sqlite"
    conn = open_store(path, clock)
    owner_id = create_owner(conn, clock, "Proprietario Sintetico")
    emp = create_employee(conn, clock, owner_id=owner_id, name="Atlas")
    yield World(conn, clock, owner_id, emp, path)
    conn.close()


# Control-plane fixtures shared by security and recovery suites.
from tests.control_plane import cp, limits  # noqa: E402, F401
