"""Classification lineage (R5-01, spec 9.1): derived content inherits at least the protection of what
it came from, by trusted code - the model never chooses a lower class.

* ``classify_text`` is the conservative detector of sensitive personal data in the owner's own words.
* ``task_classification`` is the highest class of everything a task holds: its data policy, every
  instruction revision (a revision without metadata - written before migration 0020 - is re-derived
  from its text and never assumed INTERNAL), owner messages linked to it, step observations and input
  attachments. Notifications, acknowledgements and summaries of the task carry at least this class.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata

from security.egress.guard import highest

SENSITIVE_PATTERN = re.compile(
    r"\b(saude|medic|doenc|diagnost|exame|remedio|cpf|rg\b|passaporte|filh|crianc|endereco|"
    r"conta bancaria|agencia|salario|renda|religi|sexual|biometr)",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def classify_text(text: str) -> str:
    return "SENSITIVE" if SENSITIVE_PATTERN.search(_fold(text)) else "INTERNAL"


def instruction_classification(stored: str | None, text: str, data_policy: str) -> str:
    """Stored class of an instruction revision; a legacy row without one is re-derived conservatively."""
    if stored is not None:
        return stored
    return highest(data_policy, classify_text(text), "INTERNAL")


def task_classification(conn: sqlite3.Connection, task_id: str) -> str:
    row = conn.execute("SELECT data_policy FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return "INTERNAL"
    policy = str(row[0])
    classes = [policy, "INTERNAL"]
    for cls, text in conn.execute(
        "SELECT classification, instruction FROM task_instruction_versions WHERE task_id = ?", (task_id,)
    ):
        classes.append(instruction_classification(cls, text, policy))
    classes += [
        str(r[0])
        for r in conn.execute(
            "SELECT classification FROM messages WHERE task_id = ? AND role = 'owner'"
            " UNION SELECT classification FROM step_observations WHERE task_id = ?"
            " UNION SELECT a.classification FROM artifact_links l JOIN artifacts a ON a.id = l.artifact_id"
            " WHERE l.task_id = ? AND l.relation = 'input'",
            (task_id, task_id, task_id),
        )
    ]
    return highest(*classes)
