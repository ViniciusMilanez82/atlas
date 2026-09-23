"""Raw SQL builders for tests that need rows before the engines exist. Synthetic data only."""

from __future__ import annotations

import json
import sqlite3

from shared.canonical import canonical_hash
from shared.ids import new_id, new_nonce

NOW = "2026-01-01T00:00:00.000Z"
LATER = "2026-12-31T00:00:00.000Z"


def insert_task(conn: sqlite3.Connection, owner_id: str, employee_id: str, state: str = "READY") -> str:
    tid = new_id()
    conn.execute(
        "INSERT INTO tasks(id, owner_id, employee_id, objective, constraints_json, priority, data_policy,"
        " state, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            tid,
            owner_id,
            employee_id,
            "objetivo sintetico",
            '{"external_writes":true,"purchases":false}',
            "NORMAL",
            "INTERNAL",
            state,
            NOW,
            NOW,
        ),
    )
    return tid


def insert_tool(
    conn: sqlite3.Connection, tool_id: str = "test.echo", effect: str = "EXTERNAL_WRITE", risk: str = "R2"
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO tools(tool_id, version, effect_class, base_risk, manifest_json, manifest_hash,"
        " enabled, registered_at) VALUES (?,?,?,?,?,?,?,?)",
        (tool_id, "1.0.0", effect, risk, "{}", "0" * 64, 1, NOW),
    )


def insert_action(
    conn: sqlite3.Connection, task_id: str, status: str = "PROPOSED", tool_id: str = "test.echo"
) -> str:
    insert_tool(conn, tool_id)
    aid = new_id()
    payload = {"n": aid}
    conn.execute(
        "INSERT INTO actions(id, task_id, tool_id, tool_version, effect_class, risk_class, status, input_json,"
        " input_hash, destination, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            aid,
            task_id,
            tool_id,
            "1.0.0",
            "EXTERNAL_WRITE",
            "R2",
            status,
            json.dumps(payload),
            canonical_hash(payload),
            "owner-verified-channel",
            NOW,
            NOW,
        ),
    )
    return aid


def insert_approval(conn: sqlite3.Connection, task_id: str, action_id: str, status: str = "APPROVED") -> str:
    apid = new_id()
    conn.execute(
        "INSERT INTO approvals(id, task_id, action_id, requested_by, action_type, destination, params_hash,"
        " recurrence, expires_at, max_uses, policy_version, risk_class, status, nonce, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            apid,
            task_id,
            action_id,
            "runtime",
            "test.echo",
            "dest",
            "a" * 64,
            "ONCE",
            LATER,
            1,
            "p1",
            "R3",
            status,
            new_nonce(),
            NOW,
        ),
    )
    return apid


def insert_mandate(conn: sqlite3.Connection, owner_id: str, employee_id: str) -> str:
    mid = new_id()
    conn.execute(
        "INSERT INTO mandates(id, owner_id, employee_id, tool_id, destination_pattern, max_risk, max_uses,"
        " status, expires_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (mid, owner_id, employee_id, "test.echo", "*", "R3", 5, "ACTIVE", LATER, NOW),
    )
    return mid
