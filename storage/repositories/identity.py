"""Owners and employees (spec 3.1 UX-002, 13.2). employee_id is stable and independent of name."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from shared.actors import Actor
from shared.clock import Clock, to_utc_str
from shared.ids import new_id
from storage import journal
from storage.db import transaction


class IdentityError(ValueError):
    pass


@dataclass(frozen=True)
class Employee:
    id: str
    owner_id: str
    name: str
    locale: str
    timezone: str
    profile_version: int


def create_owner(conn: sqlite3.Connection, clock: Clock, display_name: str) -> str:
    owner_id = new_id()
    with transaction(conn):
        conn.execute(
            "INSERT INTO owners(id, display_name, created_at) VALUES (?,?,?)",
            (owner_id, display_name, to_utc_str(clock.now())),
        )
    return owner_id


def create_employee(
    conn: sqlite3.Connection,
    clock: Clock,
    *,
    owner_id: str,
    name: str,
    locale: str = "pt-BR",
    timezone: str = "America/Sao_Paulo",
) -> Employee:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise IdentityError(f"unknown IANA timezone: {timezone!r}") from exc
    if not name.strip():
        raise IdentityError("employee name is required")
    emp = Employee(new_id(), owner_id, name.strip(), locale, timezone, 1)
    with transaction(conn):
        conn.execute(
            "INSERT INTO employees(id, owner_id, name, locale, timezone, profile_version, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (emp.id, owner_id, emp.name, locale, timezone, 1, to_utc_str(clock.now())),
        )
        journal.append(
            conn,
            clock,
            employee_id=emp.id,
            type="employee.created",
            actor=Actor("owner", owner_id, "local_app"),
            summary=f"employee created with locale {locale} and timezone {timezone}",
        )
    return emp
