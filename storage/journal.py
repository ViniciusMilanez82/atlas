"""Append-only audit journal (spec 17.1, 13.5 events.subscribe).

Events hold decisions and effects, never raw prompts, secrets or cookies. Summaries pass through
the redactor before being written. ``sequence_id`` is monotonic so subscribers can resume.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from shared.actors import Actor
from shared.clock import Clock, to_utc_str
from shared.contracts import validate
from shared.ids import new_id
from shared.redaction import default_redactor
from storage.db import require_transaction


def append(
    conn: sqlite3.Connection,
    clock: Clock,
    *,
    employee_id: str,
    type: str,
    actor: Actor,
    summary: str,
    task_id: str | None = None,
    action_id: str | None = None,
    policy_version: str | None = None,
    model: dict[str, str] | None = None,
    duration_ms: int | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Validate and append one event inside the caller's transaction."""
    require_transaction(conn)
    event: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": new_id(),
        "sequence_id": 1,  # placeholder for validation; the database assigns the real value
        "timestamp": to_utc_str(clock.now()),
        "employee_id": employee_id,
        "task_id": task_id,
        "action_id": action_id,
        "actor": {"kind": actor.kind, "id": actor.id},
        "type": type,
        "policy_version": policy_version,
        "model": model,
        "duration_ms": duration_ms,
        "evidence_refs": evidence_refs or [],
        "summary": default_redactor.redact(summary)[:1000],
    }
    validate("journal_event", event)
    cur = conn.execute(
        "INSERT INTO journal_events(event_id, timestamp, employee_id, task_id, action_id, actor_kind,"
        " actor_id, type, policy_version, model_provider, model_id, duration_ms, evidence_refs_json,"
        " summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event["event_id"],
            event["timestamp"],
            employee_id,
            task_id,
            action_id,
            actor.kind,
            actor.id,
            type,
            policy_version,
            model["provider"] if model else None,
            model["model_id"] if model else None,
            duration_ms,
            json.dumps(event["evidence_refs"]),
            event["summary"],
        ),
    )
    event["sequence_id"] = cur.lastrowid
    return event


def events_after(
    conn: sqlite3.Connection, employee_id: str, after_sequence_id: int, limit: int = 500
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM journal_events WHERE employee_id = ? AND sequence_id > ? ORDER BY sequence_id LIMIT ?",
        (employee_id, after_sequence_id, limit),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "schema_version": "1.0",
                "event_id": r["event_id"],
                "sequence_id": r["sequence_id"],
                "timestamp": r["timestamp"],
                "employee_id": r["employee_id"],
                "task_id": r["task_id"],
                "action_id": r["action_id"],
                "actor": {"kind": r["actor_kind"], "id": r["actor_id"]},
                "type": r["type"],
                "policy_version": r["policy_version"],
                "model": (
                    {"provider": r["model_provider"], "model_id": r["model_id"]}
                    if r["model_provider"]
                    else None
                ),
                "duration_ms": r["duration_ms"],
                "evidence_refs": json.loads(r["evidence_refs_json"]),
                "summary": r["summary"],
            }
        )
    return out
