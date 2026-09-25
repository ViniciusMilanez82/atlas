"""N06/N12 (core side of the Memory and Files screens, spec 8.4 and 21.2) over the real IPC protocol."""

from __future__ import annotations

import json
from typing import Any

from tests.conftest import World
from tests.integration.test_alpha2 import ok, send


def test_memory_screen_lists_confirms_corrects_forgets_and_exports(env: Any, world: World) -> None:
    c = env.connect()
    conv = ok(c.call("conversations.current"))["conversation_id"]
    a = send(c, env, conv, "Guarde que prefiro relatórios curtos")["memory_id"]
    b = send(c, env, conv, "Guarde que o CEP do escritório é 01000-000")["memory_id"]
    listed = ok(c.call("memories.list"))["memories"]
    assert {m["memory_id"]: m["status"] for m in listed} == {a: "proposed", b: "proposed"}
    ok(c.call("memories.confirm", memory_id=a))
    item = next(m for m in ok(c.call("memories.list", statuses=["confirmed"]))["memories"])
    assert item["memory_id"] == a and item["source_kind"] == "owner_message" and item["version"] == 1
    ok(c.call("memories.delete", memory_id=b, scope="erase"))
    export = ok(c.call("memories.export"))
    assert export["manifest"]["memories"] == 2
    dumped = json.dumps(export, ensure_ascii=False)
    assert (
        "prefiro relatórios curtos" in dumped and "01000-000" not in dumped
    )  # forgotten content not exported
    assert export["forgotten"][0]["memory_id"] == b


def test_files_screen_lists_inputs_with_analysis_state(env: Any, world: World) -> None:
    import base64

    c = env.connect()
    ref = "0a0a0a0a-0000-4000-8000-000000000001"
    ok(
        c.call(
            "artifacts.upload", upload_ref=ref, offset=0, data_b64=base64.b64encode(b"a;b\n1;2\n").decode()
        )
    )
    ok(c.call("artifacts.import", employee_id=world.employee.id, upload_ref=ref, declared_name="t.csv"))
    files = ok(c.call("artifacts.all"))["artifacts"]
    assert files[0]["name"] == "t.csv" and files[0]["analysis_state"] == "READY_FOR_ANALYSIS"
