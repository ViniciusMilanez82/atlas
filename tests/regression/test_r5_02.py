"""R5-02 (P1; continues A3-18): the owner's full request is the canonical instruction. A model summary is
only a title; conditions (date, cap, exclusion, separate items) survive with their source passage and
govern the next context and the verifier. Explicit, inferred and resent delegations keep the same text.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from runtime.verification.verifier import DeliverableSpec
from tests.regression.r5_harness import R5World, decision

REQUEST = (
    "Compare fornecedores de módulos. Entrega até 15/11/2026. Exclua contratos renováveis. "
    "Não ultrapasse R$ 8.000 e apresente os impostos separadamente."
)
PARAPHRASE = (
    "Quero uma comparação de fornecedores de módulos: prazo final 15/11/2026; teto de R$ 8.000,00, "
    "sem contratos com renovação automática, e discrimine os impostos."
)
SUMMARY = {"intent": "delegate", "reply": "", "objective": "Compare fornecedores de módulos."}


def _conditions(r5: R5World, tid: str) -> dict[str, str]:
    rows = r5.conn.execute(
        "SELECT params_json FROM task_criteria WHERE task_id = ? AND check_kind = 'condition'", (tid,)
    ).fetchall()
    return {json.loads(r[0])["kind"]: json.loads(r[0])["value"] for r in rows}


def _assert_canonical(r5: R5World, tid: str, mid: str, text: str) -> None:
    original = r5.tasks.instructions(tid)[0]
    assert original["kind"] == "ORIGINAL"
    assert original["instruction"] == text  # the owner's words, not the summary
    assert original["source_message_id"] == mid
    assert original["content_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    cond = _conditions(r5, tid)
    assert "15/11/2026" in cond["DATE"]
    assert cond["MONEY_CAP"].startswith("8.000")
    assert "renova" in cond["EXCLUSION"]
    assert "impostos" in cond["SEPARATE"]


@pytest.mark.parametrize("text", [REQUEST, PARAPHRASE])
def test_inferred_delegation_keeps_the_full_request(r5: R5World, text: str) -> None:
    r5.provider.reply = SUMMARY  # the interpreter drops date, cap, exclusion and taxes on purpose
    out = r5.send(text)
    tid = out["task_id"]
    assert r5.tasks.get(tid)["objective"] == "Compare fornecedores de módulos."  # title only
    _assert_canonical(r5, tid, out["message"]["message_id"], text)
    # The next context carries every condition (the ORIGINAL revision is required context).
    r5.provider.reply = decision("ask_owner", question="Algum fornecedor preferido?")
    r5.runner.run(tid, DeliverableSpec())
    sent = r5.provider.calls[-1]
    payload = "\n".join(m.content for m in sent.messages)
    for fragment in ("15/11/2026", "8.000", "renov", "impostos"):
        assert fragment in payload


def test_explicit_and_resent_delegations_preserve_the_same_request(r5: R5World) -> None:
    out = r5.send(REQUEST, intent="delegate")
    _assert_canonical(r5, out["task_id"], out["message"]["message_id"], REQUEST)
    assert not r5.provider.calls  # explicit delegation needs no interpretation

    # Delegating an earlier chat message ("Delegar como tarefa") uses that message verbatim.
    r5.provider.reply = {"intent": "chat", "reply": "Posso ajudar.", "objective": ""}
    chat = r5.send(PARAPHRASE)
    assert chat["intent"] == "chat"
    later = r5.send("", intent="delegate", reply_to_message_id=chat["message"]["message_id"])
    _assert_canonical(r5, later["task_id"], chat["message"]["message_id"], PARAPHRASE)

    # Resending the same request (same client id) returns the same task, nothing duplicated.
    p = {"conversation_id": r5.cid, "client_message_id": "resend-1", "text": REQUEST, "intent": "delegate"}
    first = r5.conv.handle(r5.owner, r5.emp.id, p)
    again = r5.conv.handle(r5.owner, r5.emp.id, dict(p))
    assert again["task_id"] == first["task_id"] and again["duplicate"]
    n = r5.conn.execute("SELECT COUNT(*) FROM tasks WHERE client_request_id = ?", (first["message"]["message_id"],))
    assert n.fetchone()[0] == 1


def test_conditions_govern_the_verifier(r5: R5World) -> None:
    """The conditions are not decoration: a deliverable that ignores them does not complete."""
    r5.provider.reply = SUMMARY
    tid = r5.send(REQUEST)["task_id"]
    ignoring = r5.artifact(
        tid,
        "Comparação de fornecedores de módulos. " * 3
        + "Recomendo o fornecedor B com contrato renovável, total R$ 9.500,00. Os módulos atendem ao pedido.",
    )
    res = r5.verifier.verify_text_artifact(tid, ignoring.id, DeliverableSpec())
    assert not res.passed
    text = " ".join(res.gaps)
    assert "15/11/2026" in text and "teto" in text and "impostos" in text
    respecting = r5.artifact(
        tid,
        "Comparação de fornecedores de módulos com entrega até 15/11/2026. Contratos renováveis foram "
        "excluídos da análise. Fornecedor A: módulos R$ 6.000,00; impostos R$ 900,00; total R$ 6.900,00. "
        "Fornecedor C: módulos R$ 7.000,00; impostos R$ 1.050,00; total R$ 8.050,00 (acima do teto, descartado). "
        "Recomendo o fornecedor A, total R$ 6.900,00, dentro do teto de R$ 8.000,00.",
        name="certo.txt",
    )
    res = r5.verifier.verify_text_artifact(tid, respecting.id, DeliverableSpec())
    cond_gaps = [g for g in res.gaps if "teto" in g or "15/11" in g or "impostos" in g or "excluído" in g]
    assert not cond_gaps, cond_gaps
