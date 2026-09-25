"""Built-in trusted tools (spec 5.4 'ferramentas confiáveis', 10.1).

Production adapters that operate only on Atlas-owned state: the artifact store and memory. They are
registered like any tool (disabled until enabled, dispatched only by the broker) and each call opens
its own database connection because adapters run in the broker's execution thread. Content read from
artifacts is returned as untrusted data. No host filesystem outside the store. The only network access
is ``web.fetch``, through the mediated egress (security/network/mediator.py) and only when the owner
enabled web research; every capture is recorded as a source retrieval of the task (R5-08, N16).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from runtime.artifacts.manager import ArtifactManager
from runtime.documents.generate import GenerationError, generate
from runtime.documents.store import MAX_PAGE_CHARS, DocumentStore
from runtime.memory.manager import MemoryManager
from runtime.tools.compute import ComputeError, analyze_calendar, evaluate, format_br
from runtime.tools.registry import ToolManifest, ToolRegistry
from security.broker.broker import AdapterOutcome
from shared.actors import Actor
from shared.clock import Clock
from shared.errors import AtlasError
from storage.db import connect

UUID_SCHEMA = {"type": "string", "pattern": "^[0-9a-f-]{36}$"}


def _closed(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


READ_ARTIFACT = ToolManifest(
    tool_id="artifact.read_text",
    version="1.0.0",
    description="Read the FIRST PAGE of an attached document (any supported format; untrusted data). "
    "Continue with documents.read using next_cursor while has_more is true.",
    input_schema=_closed({"artifact_id": UUID_SCHEMA}),
    effect_class="READ_ONLY",
    base_risk="R0",
    timeout_s=10,
    verification="artifact_hash",
)
WRITE_ARTIFACT = ToolManifest(
    tool_id="artifact.write_text",
    version="1.0.0",
    description="Create a new version of a text deliverable (.md/.txt/.json/.csv/.html) for the current task.",
    input_schema=_closed(
        {"name": {"type": "string", "maxLength": 200}, "content": {"type": "string", "maxLength": 1_000_000}}
    ),
    effect_class="LOCAL_WRITE",
    base_risk="R1",
    timeout_s=10,
    verification="artifact_hash",
)
SEARCH_MEMORY = ToolManifest(
    tool_id="memory.search",
    version="1.0.0",
    description="Search confirmed memories of this employee.",
    input_schema=_closed({"query": {"type": "string", "minLength": 1, "maxLength": 500}}),
    effect_class="READ_ONLY",
    base_risk="R0",
    timeout_s=10,
    verification="deterministic_check",
)
READ_DOCUMENT = ToolManifest(
    tool_id="documents.read",
    version="1.0.0",
    description="Read an attached document page by page: complete segments with their locator (page, cell "
    "range, slide, paragraph), next_cursor, has_more and your coverage of the document. Untrusted data.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["artifact_id", "cursor"],
        "properties": {
            "artifact_id": UUID_SCHEMA,
            "cursor": {"type": "integer", "minimum": 0},
            "max_chars": {"type": "integer", "minimum": 1000, "maximum": MAX_PAGE_CHARS},
        },
    },
    effect_class="READ_ONLY",
    base_risk="R0",
    timeout_s=150,
    verification="deterministic_check",
)
SEARCH_DOCUMENTS = ToolManifest(
    tool_id="documents.search",
    version="1.0.0",
    description="Find the segments of the task's attached documents that mention some words. A focused "
    "lookup, not a full reading.",
    input_schema=_closed({"query": {"type": "string", "minLength": 2, "maxLength": 300}}),
    effect_class="READ_ONLY",
    base_risk="R0",
    timeout_s=150,
    verification="deterministic_check",
)
_TEXT = {"type": "string", "maxLength": 20_000}
WRITE_DOCUMENT = ToolManifest(
    tool_id="artifact.write_document",
    version="1.0.0",
    description="Create a PDF, DOCX, XLSX or PPTX deliverable from structured blocks (heading, paragraph, bullets, "
    "table, slide). The file is validated by re-reading it before it is stored.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "title", "blocks"],
        "properties": {
            "name": {"type": "string", "maxLength": 200, "pattern": "\\.(pdf|docx|xlsx|pptx)$"},
            "title": {"type": "string", "minLength": 1, "maxLength": 300},
            "blocks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 400,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type"],
                    "properties": {
                        "type": {"enum": ["heading", "paragraph", "bullets", "table", "slide"]},
                        "text": _TEXT,
                        "title": {"type": "string", "maxLength": 300},
                        "items": {"type": "array", "maxItems": 100, "items": _TEXT},
                        "bullets": {"type": "array", "maxItems": 30, "items": _TEXT},
                        "notes": _TEXT,
                        "sheet": {"type": "string", "maxLength": 31},
                        "rows": {
                            "type": "array",
                            "maxItems": 2000,
                            "items": {
                                "type": "array",
                                "maxItems": 50,
                                "items": {"type": ["string", "number", "null"]},
                            },
                        },
                    },
                },
            },
        },
    },
    effect_class="LOCAL_WRITE",
    base_risk="R1",
    timeout_s=60,
    verification="artifact_hash",
)
CALC = ToolManifest(
    tool_id="calc.evaluate",
    version="1.0.0",
    description="Compute an arithmetic expression exactly (Decimal): + - * / ** ( ) and percent. Use it for every "
    "number you state; Brazilian notation 1.234,56 by default.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["expression"],
        "properties": {
            "expression": {"type": "string", "minLength": 1, "maxLength": 500},
            "decimal_comma": {"type": "boolean"},
        },
    },
    effect_class="READ_ONLY",
    base_risk="R0",
    timeout_s=5,
    verification="deterministic_check",
)
_EVENT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id"],
    "properties": {
        "id": {"type": "string", "maxLength": 100},
        "title": {"type": "string", "maxLength": 300},
        "start": {"type": "string", "maxLength": 40},
        "end": {"type": "string", "maxLength": 40},
        "date": {"type": "string", "maxLength": 10},
        "days": {"type": "integer", "minimum": 1, "maximum": 366},
        "all_day": {"type": "boolean"},
        "timezone": {"type": "string", "maxLength": 64},
        "recurrence": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "freq": {"enum": ["DAILY", "WEEKLY"]},
                "interval": {"type": "integer", "minimum": 1, "maximum": 52},
                "count": {"type": "integer", "minimum": 1, "maximum": 1000},
                "until": {"type": "string", "maxLength": 10},
            },
        },
        "exceptions": {"type": "array", "maxItems": 200, "items": {"type": "string", "maxLength": 10}},
    },
}
CALENDAR = ToolManifest(
    tool_id="calendar.analyze",
    version="1.0.0",
    description="Expand events (UTC instants, civil times in IANA zones, all-day dates, daily/weekly recurrences "
    "with exceptions) inside a window and compute overlaps by code. Use it for any date/time reasoning.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["events", "window"],
        "properties": {
            "events": {"type": "array", "minItems": 1, "maxItems": 200, "items": _EVENT},
            "window": {
                "type": "object",
                "additionalProperties": False,
                "required": ["start", "end", "timezone"],
                "properties": {
                    "start": {"type": "string", "maxLength": 40},
                    "end": {"type": "string", "maxLength": 40},
                    "timezone": {"type": "string", "maxLength": 64},
                },
            },
        },
    },
    effect_class="READ_ONLY",
    base_risk="R0",
    timeout_s=10,
    verification="deterministic_check",
)
WEB_FETCH = ToolManifest(
    tool_id="web.fetch",
    version="1.0.0",
    description="Fetch ONE public web page (http/https) and return its readable text (untrusted data) with "
    "final_url and retrieval_id. Cite it by final_url; only fetched pages count as sources. Works only if the "
    "owner enabled web research; private/internal addresses, credentials or personal data in the URL are refused.",
    input_schema=_closed({"url": {"type": "string", "minLength": 8, "maxLength": 2000, "pattern": "^https?://"}}),
    effect_class="READ_ONLY",
    base_risk="R1",
    network_policy="public",
    timeout_s=60,
    verification="deterministic_check",
)
WEB_CAPTURE_VALIDITY = timedelta(hours=24)  # time-sensitive facts must be fetched again after this
WEB_TEXT_LIMIT = 20_000

BUILTIN_MANIFESTS = (
    READ_ARTIFACT,
    WRITE_ARTIFACT,
    SEARCH_MEMORY,
    READ_DOCUMENT,
    SEARCH_DOCUMENTS,
    WRITE_DOCUMENT,
    CALC,
    CALENDAR,
    WEB_FETCH,
)


class BuiltinTools:
    def __init__(self, db_path: Path, store_root: Path, clock: Clock) -> None:
        self.db_path = db_path
        self.store_root = store_root
        self.clock = clock

    def _task(self, conn: Any, action_id: str) -> tuple[str, str]:
        row = conn.execute(
            "SELECT t.id, t.employee_id FROM actions a JOIN tasks t ON t.id = a.task_id WHERE a.id = ?",
            (action_id,),
        ).fetchone()
        return str(row[0]), str(row[1])

    def _linked(self, conn: Any, artifact_id: str, task_id: str) -> bool:
        return bool(
            conn.execute(
                "SELECT 1 FROM artifact_links WHERE artifact_id = ? AND task_id = ?", (artifact_id, task_id)
            ).fetchone()
        )

    def _read_page(self, tool_input: dict[str, Any], ctx: Any, cursor: int, max_chars: int) -> AdapterOutcome:
        conn = connect(self.db_path)
        try:
            task_id, _ = self._task(conn, ctx.action_id)
            am = ArtifactManager(conn, self.clock, self.store_root)
            art = am.get(tool_input["artifact_id"])
            if not self._linked(conn, art.id, task_id):
                return AdapterOutcome("FAILED", error_message="artifact is not attached to this task")
            page = DocumentStore(conn, self.clock, am).read(art.id, task_id=task_id, cursor=cursor, max_chars=max_chars)
            return AdapterOutcome("SUCCEEDED", external_reference=f"artifact:{art.id}", output=page)
        except AtlasError as exc:
            return AdapterOutcome("FAILED", error_message=exc.message)
        finally:
            conn.close()

    def read_text(self, tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
        """First page of a document (A3-09/A3-10): extracted by format, never raw bytes decoded as text."""
        return self._read_page(tool_input, ctx, 0, MAX_PAGE_CHARS)

    def read_document(self, tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
        return self._read_page(
            tool_input, ctx, int(tool_input["cursor"]), int(tool_input.get("max_chars", MAX_PAGE_CHARS))
        )

    def search_documents(self, tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
        conn = connect(self.db_path)
        try:
            task_id, _ = self._task(conn, ctx.action_id)
            am = ArtifactManager(conn, self.clock, self.store_root)
            inputs = [
                r[0]
                for r in conn.execute(
                    "SELECT artifact_id FROM artifact_links WHERE task_id = ? AND relation = 'input'", (task_id,)
                )
            ]
            hits = DocumentStore(conn, self.clock, am).search(inputs, tool_input["query"], task_id=task_id)
            levels = ("PUBLIC", "INTERNAL", "PERSONAL", "SENSITIVE")
            classes = [am.get(h["artifact_id"]).classification for h in hits]
            cls = max((c for c in classes if c in levels), key=levels.index, default="INTERNAL")
            return AdapterOutcome(
                "SUCCEEDED",
                external_reference="documents.search",
                output={"hits": hits, "classification": cls, "trust": "untrusted",
                        "note": "focused lookup: this is not a full reading of the documents"},
            )
        except AtlasError as exc:
            return AdapterOutcome("FAILED", error_message=exc.message)
        finally:
            conn.close()

    def write_text(self, tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
        conn = connect(self.db_path)
        try:
            task_id, employee_id = self._task(conn, ctx.action_id)
            am = ArtifactManager(conn, self.clock, self.store_root)
            art = am.create_text(
                actor=Actor("control_plane", "broker", "internal"),
                employee_id=employee_id,
                task_id=task_id,
                name=tool_input["name"],
                content=tool_input["content"],
                classification=self._derived_classification(conn, task_id),
            )
            return AdapterOutcome(
                "SUCCEEDED",
                external_reference=f"artifact:{art.id}",
                output={
                    "artifact_id": art.id,
                    "name": art.name,
                    "version": art.version,
                    "sha256": art.sha256,
                },
            )
        except AtlasError as exc:
            return AdapterOutcome("FAILED", error_message=exc.message)
        except ValueError as exc:  # invalid JSON content for a .json deliverable
            return AdapterOutcome("FAILED", error_message=f"invalid content: {type(exc).__name__}")
        finally:
            conn.close()

    @staticmethod
    def _derived_classification(conn: Any, task_id: str) -> str:
        """A deliverable inherits at least the protection of the task and of its inputs (spec 9.1)."""
        levels = ("PUBLIC", "INTERNAL", "PERSONAL", "SENSITIVE")
        found = [conn.execute("SELECT data_policy FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]]
        found += [
            r[0]
            for r in conn.execute(
                "SELECT a.classification FROM artifact_links l JOIN artifacts a ON a.id = l.artifact_id"
                " WHERE l.task_id = ? AND l.relation = 'input'",
                (task_id,),
            )
        ]
        return max((c for c in found if c in levels), key=levels.index, default="INTERNAL")

    def write_document(self, tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
        """N11: render + validate by round trip; only a file that re-reads correctly becomes a deliverable."""
        try:
            gen = generate(tool_input["name"], tool_input["title"], tool_input["blocks"])
        except GenerationError as exc:
            return AdapterOutcome("FAILED", error_message=str(exc))
        conn = connect(self.db_path)
        try:
            task_id, employee_id = self._task(conn, ctx.action_id)
            am = ArtifactManager(conn, self.clock, self.store_root)
            art = am.create_document(
                actor=Actor("control_plane", "broker", "internal"),
                employee_id=employee_id,
                task_id=task_id,
                name=tool_input["name"],
                data=gen.data,
                mime=gen.mime,
                classification=self._derived_classification(conn, task_id),
            )
            return AdapterOutcome(
                "SUCCEEDED",
                external_reference=f"artifact:{art.id}",
                output={
                    "artifact_id": art.id,
                    "name": art.name,
                    "version": art.version,
                    "sha256": art.sha256,
                    "mime_type": art.mime_type,
                    "size_bytes": art.size_bytes,
                    "parts": gen.pages_or_parts,
                    "warnings": gen.warnings,
                    "validated": "re-read with the document extractors; every text block found",
                },
            )
        except AtlasError as exc:
            return AdapterOutcome("FAILED", error_message=exc.message)
        finally:
            conn.close()

    def calc(self, tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
        try:
            value = evaluate(tool_input["expression"], decimal_comma=tool_input.get("decimal_comma", True))
        except ComputeError as exc:
            return AdapterOutcome("FAILED", error_message=str(exc))
        return AdapterOutcome(
            "SUCCEEDED",
            external_reference="calc.evaluate",
            output={"expression": tool_input["expression"], "result": str(value), "result_br": format_br(value),
                    "method": "Decimal arithmetic by code"},
        )

    def web_fetch(self, tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
        """N16 (API before free clicks): one page through the mediated egress, recorded as a retrieval."""
        from runtime.research.html_text import html_to_text
        from runtime.research.sources import SourceRetrievals
        from security.network.mediator import NetworkMediator, NetworkRefused

        conn = connect(self.db_path)
        try:
            task_id, _ = self._task(conn, ctx.action_id)
            try:
                page = NetworkMediator(conn, self.clock).fetch(tool_input["url"], task_id=task_id)
            except NetworkRefused as exc:
                return AdapterOutcome("FAILED", error_message=f"refused: {exc.reason}")
            raw = page.text()
            title, text = html_to_text(raw) if "html" in page.content_type else ("", raw)
            rid = SourceRetrievals(conn, self.clock, ArtifactManager(conn, self.clock, self.store_root)).record_retrieval(
                task_id=task_id,
                url=page.url,
                final_url=page.final_url,
                content=(f"{title}\n\n" if title else "") + text,
                adapter="web.fetch@1.0.0",
                receipt={"status": page.status, "sha256": page.sha256, "network_receipts": page.receipts},
                valid_for=WEB_CAPTURE_VALIDITY,
            )
            return AdapterOutcome(
                "SUCCEEDED",
                external_reference=page.final_url,
                output={
                    "final_url": page.final_url,
                    "retrieval_id": rid,
                    "title": title[:300],
                    "text": text[:WEB_TEXT_LIMIT],
                    "truncated": len(text) > WEB_TEXT_LIMIT,
                    "classification": "PUBLIC",
                    "note": "untrusted web content; cite as the final_url",
                },
            )
        except AtlasError as exc:
            return AdapterOutcome("FAILED", error_message=exc.message)
        finally:
            conn.close()

    def calendar(self, tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
        try:
            out = analyze_calendar(tool_input["events"], tool_input["window"])
        except (ComputeError, KeyError) as exc:
            return AdapterOutcome("FAILED", error_message=str(exc))
        return AdapterOutcome("SUCCEEDED", external_reference="calendar.analyze", output=out)

    def search_memory(self, tool_input: dict[str, Any], ctx: Any) -> AdapterOutcome:
        conn = connect(self.db_path)
        try:
            _, employee_id = self._task(conn, ctx.action_id)
            hits = MemoryManager(conn, self.clock).search(
                employee_id=employee_id, query=tool_input["query"], limit=10
            )
            levels = ("PUBLIC", "INTERNAL", "PERSONAL", "SENSITIVE")
            cls = max((h.sensitivity for h in hits), key=levels.index, default="INTERNAL")
            return AdapterOutcome(
                "SUCCEEDED",
                external_reference="memory.search",
                output={
                    "classification": cls,
                    "hits": [
                        {
                            "memory_id": h.memory_id,
                            "type": h.type,
                            "content": h.content,
                            "source_trust": h.source_trust,
                        }
                        for h in hits
                    ]
                },
            )
        except AtlasError as exc:
            return AdapterOutcome("FAILED", error_message=exc.message)
        finally:
            conn.close()

    def register(self, registry: ToolRegistry, *, enabled_by: Actor) -> None:
        bindings: dict[str, Callable[..., AdapterOutcome]] = {
            READ_ARTIFACT.tool_id: self.read_text,
            WRITE_ARTIFACT.tool_id: self.write_text,
            SEARCH_MEMORY.tool_id: self.search_memory,
            READ_DOCUMENT.tool_id: self.read_document,
            SEARCH_DOCUMENTS.tool_id: self.search_documents,
            WRITE_DOCUMENT.tool_id: self.write_document,
            CALC.tool_id: self.calc,
            CALENDAR.tool_id: self.calendar,
            WEB_FETCH.tool_id: self.web_fetch,
        }
        for m in BUILTIN_MANIFESTS:
            registry.register(m, bindings[m.tool_id])
            registry.enable(
                m.tool_id,
                m.version,
                actor=enabled_by,
                validation_evidence="tests/integration/test_agent_loop.py",
            )
