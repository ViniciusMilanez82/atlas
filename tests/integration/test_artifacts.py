"""AT-014 host part / spec 5.3, 15.1: explicit import/export, confinement, content checks, versions."""

from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

import pytest

from runtime.artifacts.manager import MAX_IMPORT_BYTES, ArtifactManager
from shared.actors import Actor
from shared.errors import AtlasError
from tests.conftest import World

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def am(world: World, tmp_path: Path) -> ArtifactManager:
    return ArtifactManager(world.conn, world.clock, tmp_path / "store")


def write(tmp: Path, name: str, data: bytes) -> Path:
    p = tmp / name
    p.write_bytes(data)
    return p


def test_import_records_hash_and_never_touches_original(
    am: ArtifactManager, world: World, tmp_path: Path
) -> None:
    src = write(tmp_path, "proposta.md", b"# Proposta A\nValor: 100")
    before = src.read_bytes()
    art = am.import_file(src, actor=world.owner, employee_id=world.employee.id)
    assert art.mime_type == "text/markdown" and art.version == 1 and len(art.sha256) == 64
    assert src.read_bytes() == before
    assert am.read_bytes(art.id) == before


def test_extension_must_match_real_content(am: ArtifactManager, world: World, tmp_path: Path) -> None:
    fake_pdf = write(tmp_path, "contrato.pdf", b"isto nao e um pdf")
    with pytest.raises(AtlasError, match="does not match"):
        am.import_file(fake_pdf, actor=world.owner, employee_id=world.employee.id)
    real = write(tmp_path, "contrato2.pdf", PDF)
    assert (
        am.import_file(real, actor=world.owner, employee_id=world.employee.id).mime_type == "application/pdf"
    )


def test_unknown_types_and_size_limit(am: ArtifactManager, world: World, tmp_path: Path) -> None:
    with pytest.raises(AtlasError, match="not accepted"):
        am.import_file(write(tmp_path, "run.exe", b"MZ..."), actor=world.owner, employee_id=world.employee.id)
    big = tmp_path / "big.txt"
    with open(big, "wb") as f:
        f.truncate(MAX_IMPORT_BYTES + 1)
    with pytest.raises(AtlasError, match="size limit"):
        am.import_file(big, actor=world.owner, employee_id=world.employee.id)


@pytest.mark.skipif(
    sys.platform == "win32" and not os.environ.get("CI"),
    reason="symlink creation needs privileges on Windows",
)
def test_symlinks_are_not_imported(am: ArtifactManager, world: World, tmp_path: Path) -> None:
    target = write(tmp_path, "secret.txt", b"host sentinel")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(AtlasError, match="symbolic"):
        am.import_file(link, actor=world.owner, employee_id=world.employee.id)


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("members", "match"),
    [
        ({"../../etc/passwd": b"x"}, "escapes"),
        ({"/abs/path.txt": b"x"}, "escapes"),
        ({"bomb.txt": b"0" * 5_000_000}, "ratio"),
    ],
)
def test_unsafe_archives_rejected(
    am: ArtifactManager, world: World, tmp_path: Path, members: dict[str, bytes], match: str
) -> None:
    with pytest.raises(AtlasError, match=match):
        am.import_file(
            write(tmp_path, "pacote.zip", zip_bytes(members)),
            actor=world.owner,
            employee_id=world.employee.id,
        )


def test_docx_needs_ooxml_structure(am: ArtifactManager, world: World, tmp_path: Path) -> None:
    plain_zip = write(tmp_path, "falso.docx", zip_bytes({"a.txt": b"x"}))
    with pytest.raises(AtlasError, match="does not match"):
        am.import_file(plain_zip, actor=world.owner, employee_id=world.employee.id)
    docx = write(
        tmp_path, "real.docx", zip_bytes({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w/>"})
    )
    assert (
        "wordprocessingml" in am.import_file(docx, actor=world.owner, employee_id=world.employee.id).mime_type
    )


def test_only_owner_imports_and_exports(am: ArtifactManager, world: World, tmp_path: Path) -> None:
    src = write(tmp_path, "a.txt", b"texto")
    with pytest.raises(AtlasError):
        am.import_file(src, actor=Actor("runtime", "rt"), employee_id=world.employee.id)
    art = am.import_file(src, actor=world.owner, employee_id=world.employee.id)
    with pytest.raises(AtlasError):
        am.export(art.id, tmp_path, actor=Actor("runtime", "rt"), expected_sha256=art.sha256)


def test_versions_and_export_never_overwrite(am: ArtifactManager, world: World, tmp_path: Path) -> None:
    from storage.db import transaction
    from tests.helpers import insert_task

    with transaction(world.conn):
        tid = insert_task(world.conn, world.owner_id, world.employee.id)
    v1 = am.create_text(
        actor=Actor("runtime", "rt"),
        employee_id=world.employee.id,
        task_id=tid,
        name="relatorio.md",
        content="# v1",
    )
    v2 = am.create_text(
        actor=Actor("runtime", "rt"),
        employee_id=world.employee.id,
        task_id=tid,
        name="relatorio.md",
        content="# v2",
    )
    assert (v1.version, v2.version) == (1, 2)
    out = tmp_path / "out"
    out.mkdir()
    (out / "relatorio.md").write_text("arquivo do proprietario", encoding="utf-8")
    exported = am.export(v2.id, out, actor=world.owner, expected_sha256=v2.sha256)
    assert (out / "relatorio.md").read_text(encoding="utf-8") == "arquivo do proprietario"
    assert exported.name == "relatorio (atlas v2).md" and exported.read_text(encoding="utf-8") == "# v2"
    with pytest.raises(AtlasError, match="changed"):
        am.export(v2.id, out, actor=world.owner, expected_sha256=v1.sha256)


def test_tampered_store_is_detected(am: ArtifactManager, world: World, tmp_path: Path) -> None:
    art = am.import_file(
        write(tmp_path, "a.txt", b"original"), actor=world.owner, employee_id=world.employee.id
    )
    obj = am.root / "objects" / art.sha256[:2] / art.sha256
    obj.write_bytes(b"tampered")
    with pytest.raises(AtlasError, match="hash"):
        am.read_bytes(art.id)


def test_names_cannot_escape(am: ArtifactManager, world: World, tmp_path: Path) -> None:
    src = write(tmp_path, "a.txt", b"x")
    art = am.import_file(
        src, actor=world.owner, employee_id=world.employee.id, declared_name="../../evil.txt"
    )
    assert art.name == "evil.txt"
    with pytest.raises(AtlasError):
        am.import_file(src, actor=world.owner, employee_id=world.employee.id, declared_name="..")
