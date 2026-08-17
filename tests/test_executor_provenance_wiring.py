"""Executor provenance wiring: every artifact write is signed + indexed.

Asserts that when an Executor is configured with a ProvenanceIndex + SessionKey,
a write through the executor produces both a SQLite index entry and a sidecar
file carrying a verifiable Rootknot. This is the ADR-0001 contract enforced at
the executor chokepoint (v0.3 Module 5).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ract.core.keys import SessionKey
from ract.core.provenance import ProvenanceIndex
from ract.core.types import digest_bytes
from ract.executor import Executor


def _make_executor(tmp_path: Path) -> tuple[Executor, ProvenanceIndex, SessionKey]:
    index = ProvenanceIndex(tmp_path)
    key = SessionKey.load_or_create(b"\x10" * 16, state_dir=tmp_path / "state")
    router = MagicMock()
    return (
        Executor(
            router=router, project_dir=tmp_path, provenance_index=index, session_key=key
        ),
        index,
        key,
    )


def test_write_artifact_records_rootknot_in_index(tmp_path: Path) -> None:
    executor, index, key = _make_executor(tmp_path)
    executor._write_artifact("src/hello.py", "print('hi')\n")

    artifact = tmp_path / "src" / "hello.py"
    assert artifact.is_file(), "artifact must be written"
    knot = index.load(artifact)
    assert knot is not None, "executor write must index a Rootknot"
    assert knot.verify(key.public_key_bytes()), "indexed rootknot must verify"
    # The recorded digest matches the artifact content.
    assert knot.artifact_digest == digest_bytes(b"print('hi')\n")


def test_write_artifact_emits_sidecar(tmp_path: Path) -> None:
    executor, _index, _key = _make_executor(tmp_path)
    executor._write_artifact("src/hello.py", "print('hi')\n")

    artifact = tmp_path / "src" / "hello.py"
    sidecar = artifact.parent / f".{artifact.name}.rootknot.json"
    assert sidecar.is_file(), "executor write must emit a sidecar"
    import json

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "signature" in payload
    assert payload["workspace_path"].endswith("src/hello.py")


def test_executor_without_provenance_config_writes_without_indexing(
    tmp_path: Path,
) -> None:
    """An executor with no provenance wiring must not create any index/sidecar.

    Guards the default behavior: existing callers (and all pre-v0.3 tests) get
    unchanged semantics — a plain write, no .rack directory created.
    """
    router = MagicMock()
    executor = Executor(router=router, project_dir=tmp_path)
    executor._write_artifact("src/hello.py", "print('hi')\n")
    assert (tmp_path / "src" / "hello.py").is_file()
    assert not (tmp_path / ".rack").exists(), "no .rack index must be created"
    sidecar = tmp_path / "src" / ".hello.py.rootknot.json"
    assert not sidecar.exists(), "no sidecar must be created"


# RACT 0.3.0
