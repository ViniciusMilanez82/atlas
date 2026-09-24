"""Artifact Manager / Artifact Broker, host side (spec 5.3, 15.1; AT-014 host part).

Files enter and leave Atlas only by explicit import/export. The store is content-addressed
(``objects/<sha256[:2]>/<sha256>``) under one root; database rows carry ``artifact_id``, hash,
size, MIME type, version, origin task and classification - never a path chosen by the LLM.

Import checks: regular file (no symlinks/devices), size limit, real content type sniffed from the
bytes and required to match the extension, archives inspected (no absolute or ``..`` member paths,
no symlink members, bounded member count, bounded total uncompressed size and ratio). Export writes
a new copy, verifies the hash and never overwrites an existing file. Nothing here mounts or scans the
owner's home directory: the caller passes one file the owner chose.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from shared.actors import Actor
from shared.clock import Clock, to_utc_str
from shared.errors import AtlasError, ErrorCode
from shared.ids import new_id
from storage import journal
from storage.db import transaction

MAX_IMPORT_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2_000
MAX_ARCHIVE_UNCOMPRESSED = 500 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100

# extension -> accepted sniffed kinds
EXTENSIONS: dict[str, tuple[str, ...]] = {
    ".txt": ("text",),
    ".md": ("text",),
    ".csv": ("text",),
    ".json": ("json",),
    ".html": ("text",),
    ".pdf": ("pdf",),
    ".png": ("png",),
    ".jpg": ("jpeg",),
    ".jpeg": ("jpeg",),
    ".zip": ("zip",),
    ".docx": ("ooxml",),
    ".xlsx": ("ooxml",),
    ".pptx": ("ooxml",),
}
MIME = {
    "text": "text/plain",
    "json": "application/json",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "zip": "application/zip",
    "ooxml": "application/vnd.openxmlformats",
}
TEXT_MIME = {".md": "text/markdown", ".csv": "text/csv", ".html": "text/html"}
OOXML_MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


@dataclass(frozen=True)
class Artifact:
    id: str
    name: str
    mime_type: str
    sha256: str
    size_bytes: int
    version: int
    task_id: str | None
    classification: str


def sniff(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"PK\x03\x04") or data.startswith(b"PK\x05\x06"):
        return "zip"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    if "\x00" in text:
        return "binary"
    stripped = text.strip()
    if stripped[:1] in ("{", "["):
        try:
            json.loads(stripped)
            return "json"
        except json.JSONDecodeError:
            return "text"
    return "text"


def inspect_archive(path: Path) -> list[str]:
    """Return member names or raise if the archive is unsafe."""
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise AtlasError(ErrorCode.INVALID_INPUT, "corrupt archive") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            raise AtlasError(ErrorCode.INVALID_INPUT, "archive has too many members")
        total = 0
        for info in infos:
            name = PurePosixPath(info.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or (name.parts and ":" in name.parts[0]):
                raise AtlasError(ErrorCode.INVALID_INPUT, "archive member escapes its folder")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise AtlasError(ErrorCode.INVALID_INPUT, "archive contains a symbolic link")
            total += info.file_size
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise AtlasError(ErrorCode.INVALID_INPUT, "archive member compression ratio is suspicious")
        if total > MAX_ARCHIVE_UNCOMPRESSED:
            raise AtlasError(ErrorCode.INVALID_INPUT, "archive expands beyond the allowed size")
        return [i.filename for i in infos]


class ArtifactManager:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, root: Path) -> None:
        self.conn = conn
        self.clock = clock
        self.root = root.resolve()
        (self.root / "objects").mkdir(parents=True, exist_ok=True)
        self.bytes_hashed = 0  # instrumentation for the linear-read guarantee (A3-25)
        self.bytes_read = 0
        self._verified: dict[str, tuple[int, int, int]] = {}  # artifact -> (size, mtime_ns, inode) checked

    # ------------------------------------------------------------------ store

    def _object_path(self, sha: str) -> Path:
        path = (self.root / "objects" / sha[:2] / sha).resolve()
        if self.root not in path.parents:
            raise AtlasError(ErrorCode.INVALID_INPUT, "object path escaped the store")
        return path

    def _put(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self._object_path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        return sha

    def _row(self, artifact_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise AtlasError(ErrorCode.INVALID_INPUT, "unknown artifact")
        return row

    def get(self, artifact_id: str) -> Artifact:
        r = self._row(artifact_id)
        return Artifact(
            r["id"],
            r["name"],
            r["mime_type"],
            r["sha256"],
            r["size_bytes"],
            r["version"],
            r["task_id"],
            r["classification"],
        )

    def read_bytes(self, artifact_id: str) -> bytes:
        """Read and re-verify the hash: a file does not exist because a model wrote its name."""
        r = self._row(artifact_id)
        path = self._object_path(r["sha256"])
        if not path.is_file():
            raise AtlasError(ErrorCode.INVALID_INPUT, "artifact content is missing from the store")
        data = path.read_bytes()
        self.bytes_read += len(data)
        self.bytes_hashed += len(data)
        if hashlib.sha256(data).hexdigest() != r["sha256"]:
            raise AtlasError(ErrorCode.INVALID_INPUT, "artifact content does not match its hash")
        return data

    def read_range(self, artifact_id: str, offset: int, length: int) -> tuple[bytes, int]:
        """Read ``length`` bytes at ``offset`` of an immutable artifact. Returns (chunk, total size).

        The whole object is hashed once per reader and pinned by (size, mtime, inode); later ranges read
        only their bytes, so reading a file in N chunks costs ~2x its size, not N x its size (A3-25).
        Any change of the pinned identity forces a new full verification, so tampering during the read
        is detected instead of being streamed.
        """
        r = self._row(artifact_id)
        path = self._object_path(r["sha256"])
        if not path.is_file():
            raise AtlasError(ErrorCode.INVALID_INPUT, "artifact content is missing from the store")
        st = path.stat()
        pin = (st.st_size, st.st_mtime_ns, st.st_ino)
        if self._verified.get(artifact_id) != pin:
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for block in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(block)
                    self.bytes_hashed += len(block)
            if h.hexdigest() != r["sha256"] or st.st_size != r["size_bytes"]:
                self._verified.pop(artifact_id, None)
                raise AtlasError(ErrorCode.INVALID_INPUT, "artifact content does not match its hash")
            self._verified[artifact_id] = pin
        with path.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read(length)
        self.bytes_read += len(chunk)
        return chunk, int(r["size_bytes"])

    def _insert(
        self,
        *,
        employee_id: str,
        task_id: str | None,
        name: str,
        mime: str,
        data: bytes,
        classification: str,
        relation: str,
        actor: Actor,
        on_insert_in_txn: Callable[[str], None] | None = None,
    ) -> Artifact:
        sha = self._put(data)
        aid = new_id()
        with transaction(self.conn):
            prev = self.conn.execute(
                "SELECT MAX(version) FROM artifacts WHERE employee_id = ? AND name = ? AND task_id IS ?",
                (employee_id, name, task_id),
            ).fetchone()[0]
            version = int(prev or 0) + 1
            self.conn.execute(
                "INSERT INTO artifacts(id, employee_id, task_id, name, mime_type, sha256, size_bytes, storage_ref,"
                " version, classification, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    aid,
                    employee_id,
                    task_id,
                    name,
                    mime,
                    sha,
                    len(data),
                    f"objects/{sha[:2]}/{sha}",
                    version,
                    classification,
                    to_utc_str(self.clock.now()),
                ),
            )
            if task_id:
                self.conn.execute(
                    "INSERT INTO artifact_links(artifact_id, task_id, relation) VALUES (?,?,?)",
                    (aid, task_id, relation),
                )
            journal.append(
                self.conn,
                self.clock,
                employee_id=employee_id,
                task_id=task_id,
                type="artifact.stored",
                actor=actor,
                summary=f"{relation} artifact '{name}' v{version} ({len(data)} bytes)",
            )
            if on_insert_in_txn is not None:  # e.g. the upload receipt, in the same commit (A3-22)
                on_insert_in_txn(aid)
        return self.get(aid)

    # ------------------------------------------------------------------ import / create / export

    def import_file(
        self,
        source: Path,
        *,
        actor: Actor,
        employee_id: str,
        declared_name: str | None = None,
        task_id: str | None = None,
        classification: str = "INTERNAL",
        expected_sha256: str | None = None,
        on_insert_in_txn: Callable[[str], None] | None = None,
    ) -> Artifact:
        """Explicit import of ONE file the owner chose. The original is never modified."""
        if actor.kind != "owner":
            raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner imports files into Atlas")
        st = os.lstat(source)
        if stat.S_ISLNK(st.st_mode):
            raise AtlasError(ErrorCode.INVALID_INPUT, "symbolic links are not imported")
        if not stat.S_ISREG(st.st_mode):
            raise AtlasError(ErrorCode.INVALID_INPUT, "only regular files can be imported")
        if st.st_size > MAX_IMPORT_BYTES:
            raise AtlasError(ErrorCode.INVALID_INPUT, "file exceeds the import size limit")
        name = self._clean_name(declared_name or source.name)
        ext = Path(name).suffix.lower()
        if ext not in EXTENSIONS:
            raise AtlasError(ErrorCode.INVALID_INPUT, f"file type {ext or '(none)'} is not accepted")
        data = source.read_bytes()
        if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
            raise AtlasError(ErrorCode.INVALID_INPUT, "received file does not match the expected hash")
        kind = sniff(data)
        if kind == "zip" and ext in (".docx", ".xlsx", ".pptx"):
            members = inspect_archive(source)
            kind = "ooxml" if "[Content_Types].xml" in members else "zip"
        elif kind == "zip":
            inspect_archive(source)
        if kind not in EXTENSIONS[ext]:
            raise AtlasError(ErrorCode.INVALID_INPUT, f"content is {kind}, which does not match {ext}")
        mime = OOXML_MIME.get(ext) or TEXT_MIME.get(ext) or MIME[kind]
        return self._insert(
            employee_id=employee_id,
            task_id=task_id,
            name=name,
            mime=mime,
            data=data,
            classification=classification,
            relation="input",
            actor=actor,
            on_insert_in_txn=on_insert_in_txn,
        )

    def create_text(
        self,
        *,
        actor: Actor,
        employee_id: str,
        task_id: str,
        name: str,
        content: str,
        classification: str = "INTERNAL",
    ) -> Artifact:
        """Atlas-produced deliverable. Stored as a new version; earlier versions are kept."""
        name = self._clean_name(name)
        ext = Path(name).suffix.lower()
        if ext not in (".md", ".txt", ".json", ".csv", ".html"):
            raise AtlasError(
                ErrorCode.INVALID_INPUT, "text artifacts must be .md, .txt, .json, .csv or .html"
            )
        data = content.encode("utf-8")
        if len(data) > MAX_IMPORT_BYTES:
            raise AtlasError(ErrorCode.INVALID_INPUT, "artifact too large")
        if ext == ".json":
            json.loads(content)  # must be valid JSON
        mime = TEXT_MIME.get(ext, "application/json" if ext == ".json" else "text/plain")
        return self._insert(
            employee_id=employee_id,
            task_id=task_id,
            name=name,
            mime=mime,
            data=data,
            classification=classification,
            relation="output",
            actor=actor,
        )

    def create_document(
        self,
        *,
        actor: Actor,
        employee_id: str,
        task_id: str,
        name: str,
        data: bytes,
        mime: str,
        classification: str = "INTERNAL",
    ) -> Artifact:
        """Atlas-produced binary deliverable (PDF/DOCX/XLSX/PPTX) already validated by round trip (N11)."""
        name = self._clean_name(name)
        ext = Path(name).suffix.lower()
        if ext not in (".pdf", ".docx", ".xlsx", ".pptx"):
            raise AtlasError(ErrorCode.INVALID_INPUT, "documents must be .pdf, .docx, .xlsx or .pptx")
        if len(data) > MAX_IMPORT_BYTES:
            raise AtlasError(ErrorCode.INVALID_INPUT, "artifact too large")
        kind = sniff(data)
        if kind not in EXTENSIONS[ext] and not (ext != ".pdf" and kind == "zip"):
            raise AtlasError(ErrorCode.INVALID_INPUT, f"content is {kind}, which does not match {ext}")
        return self._insert(
            employee_id=employee_id,
            task_id=task_id,
            name=name,
            mime=mime,
            data=data,
            classification=classification,
            relation="output",
            actor=actor,
        )

    def export(self, artifact_id: str, dest_dir: Path, *, actor: Actor, expected_sha256: str) -> Path:
        """Explicit export: a new copy in a folder the owner chose; never overwrites."""
        if actor.kind != "owner":
            raise AtlasError(ErrorCode.UNAUTHORIZED, "only the owner exports files")
        art = self.get(artifact_id)
        if art.sha256 != expected_sha256:
            raise AtlasError(ErrorCode.VERSION_CONFLICT, "artifact changed since it was shown to the owner")
        data = self.read_bytes(artifact_id)
        dest_dir = dest_dir.resolve()
        if not dest_dir.is_dir():
            raise AtlasError(ErrorCode.INVALID_INPUT, "destination folder does not exist")
        target = dest_dir / art.name
        if target.exists() or target.is_symlink():
            stem, ext = target.stem, target.suffix
            target = dest_dir / f"{stem} (atlas v{art.version}){ext}"
            if target.exists():
                raise AtlasError(
                    ErrorCode.VERSION_CONFLICT, "a file with this name already exists; not overwriting"
                )
        with open(target, "xb") as f:  # exclusive create: never overwrite
            f.write(data)
        if hashlib.sha256(target.read_bytes()).hexdigest() != art.sha256:
            target.unlink()
            raise AtlasError(ErrorCode.INVALID_INPUT, "exported copy failed hash verification")
        emp = self._row(artifact_id)["employee_id"]
        with transaction(self.conn):
            journal.append(
                self.conn,
                self.clock,
                employee_id=emp,
                task_id=art.task_id,
                type="artifact.exported",
                actor=actor,
                summary=f"'{art.name}' v{art.version} exported with verified hash",
            )
        return target

    @staticmethod
    def _clean_name(name: str) -> str:
        base = name.replace("\\", "/").split("/")[-1].strip()
        if not base or base in (".", "..") or any(c in base for c in '<>:"|?*\x00'):
            raise AtlasError(ErrorCode.INVALID_INPUT, "invalid file name")
        return base[:200]

    def purge_unreferenced_objects(self) -> int:
        """Remove stored bytes no artifact row references (used after deletions)."""
        live = {r[0] for r in self.conn.execute("SELECT sha256 FROM artifacts")}
        removed = 0
        for sub in (self.root / "objects").iterdir():
            for obj in sub.iterdir():
                if obj.name not in live:
                    obj.unlink()
                    removed += 1
            if sub.is_dir() and not any(sub.iterdir()):
                shutil.rmtree(sub)
        return removed
