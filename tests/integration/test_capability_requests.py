"""N18 / spec 16.5: a missing capability becomes a concrete request the owner decides; approving it neither
buys anything nor authorizes sending sensitive data. Scripted FAKE model; real IPC for the decision."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.conftest import World
from tests.integration.test_agent_loop import SPEC, build, decision
from tests.integration.test_alpha2 import ok

REQUEST = {
    "problem": "Preciso de cotações atuais de frete para 3 cidades",
    "missing_capability": "consulta de frete em tempo real",
    "provider": "FreteAPI (sandbox)",
    "evidence": "a documentação pública descreve cotação por CEP de origem e destino",
    "price": {
        "amount": "49,90",
        "currency": "BRL",
        "recurrence": "monthly",
        "source": "página de preços consultada",
    },
    "data_shared": ["INTERNAL"],
    "alternatives": ["pedir as cotações por e-mail às transportadoras", "usar tabela pública desatualizada"],
    "risk": "cobrança recorrente; dados de CEP enviados ao fornecedor",
    "test_plan": "uma cotação de teste com CEPs sintéticos",
}


def _run_until_request(world: World, tmp_path: Path) -> tuple[Any, str]:
    def policy(turn: int, prompt: str) -> str:
        if turn == 1:
            return json.dumps(
                {
                    **json.loads(decision("ask_owner")),
                    "decision": "request_capability",
                    "question": "",
                    "capability_json": json.dumps(REQUEST),
                }
            )
        return decision("ask_owner", question="ok?")

    s = build(world, tmp_path, policy)
    tid = s.tasks.create(
        world.owner, employee_id=world.employee.id, objective="Cotar frete", criteria=[("x", True)]
    )
    out = s.runner.run(tid, SPEC)
    assert out.state == "WAITING_USER"
    return s, tid


def test_request_is_concrete_and_waits_for_the_owner(world: World, tmp_path: Path) -> None:
    _, tid = _run_until_request(world, tmp_path)
    q = world.conn.execute(
        "SELECT kind, content FROM notification_outbox WHERE task_id = ?", (tid,)
    ).fetchone()
    assert q[0] == "question"
    for piece in ("49,90 BRL", "renovação mensal", "INTERNAL", "e-mail às transportadoras", "não autoriza"):
        assert piece in q[1]
    assert world.conn.execute("SELECT COUNT(*) FROM actions WHERE task_id = ?", (tid,)).fetchone()[0] == 0


def test_incomplete_request_is_rejected_before_anything(world: World, tmp_path: Path) -> None:
    bad = {k: v for k, v in REQUEST.items() if k != "price"}

    def policy(turn: int, prompt: str) -> str:
        return json.dumps(
            {
                **json.loads(decision("ask_owner")),
                "decision": "request_capability",
                "question": "",
                "capability_json": json.dumps(bad),
            }
        )

    s = build(world, tmp_path, policy)
    tid = s.tasks.create(
        world.owner, employee_id=world.employee.id, objective="Cotar frete", criteria=[("x", True)]
    )
    s.runner.run(tid, SPEC)
    assert world.conn.execute("SELECT COUNT(*) FROM capability_requests").fetchone()[0] == 0
    assert any("capability request incomplete" in p for p in s.model.prompts)


def test_owner_decision_resumes_without_buying_or_widening_egress(
    env: Any, world: World, tmp_path: Path
) -> None:
    _, tid = _run_until_request(world, tmp_path)
    c = env.connect()
    pending = ok(c.call("capabilities.list"))["requests"]
    assert len(pending) == 1 and pending[0]["task_id"] == tid
    out = ok(
        c.call(
            "capabilities.decide", request_id=pending[0]["request_id"], decision="REJECT", note="use o e-mail"
        )
    )
    assert out["status"] == "REJECTED"
    task = ok(c.call("tasks.get", task_id=tid))["task"]
    assert task["state"] == "READY" and task["instruction_revision"] == out["instruction_revision"]
    last = world.conn.execute(
        "SELECT instruction FROM task_instruction_versions WHERE task_id = ? ORDER BY revision DESC", (tid,)
    ).fetchone()[0]
    assert "RECUSOU" in last and "use o e-mail" in last
    again = c.call("capabilities.decide", request_id=pending[0]["request_id"], decision="APPROVE")
    assert again["error"]["data"]["atlas_code"] == "VERSION_CONFLICT"  # decided once
    cfg = world.conn.execute("SELECT config_json FROM settings ORDER BY revision DESC LIMIT 1").fetchone()
    assert cfg is None or "sensitive_consents" not in cfg[0]  # nothing about data disclosure changed
