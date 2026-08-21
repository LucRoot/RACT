"""Executor wire-in runtime assertion for Lens D D2.

SP Q7 amendment (external reviewer PARTIAL verdict):
`test_no_v1_rootknot_in_production.py` is a grep-gate; it asserts
the call site spells ``make_rootknot_v4`` but does NOT verify that
a real run emits a v4 sidecar. This regression drives the actual
code path: construct an ``Executor`` with the six v4 deps, invoke
``_record_provenance``, then read the sidecar off disk and assert
its ``schema == "sidecar/v4"`` with all four v0.5.1 fields
populated.

Reference:
- ``_BUILD/audit_2026-08-21/lens_D_rootknot_signatures.md`` D2.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_02.md`` SP Q7.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import pytest

from ract.core.keys import SessionKey
from ract.core.loop import WorkspaceSnapshot
from ract.core.provenance import ProvenanceIndex
from ract.core.types import Digest
from ract.core.workspace_digest import compute_prompt_digest
from ract.executor.steps import Executor
from ract.runtime import bind_run_id


class _KeyStub:
    def __init__(self, seed: bytes) -> None:
        self._key = SessionKey.load_or_create(seed)

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)

    def public_key_bytes(self) -> bytes:
        return self._key.public_key_bytes()


def _dummy_suite(prompt_text: str = "prod intent"):
    """Return a minimal AcceptanceSuite with a real prompt_digest."""
    from ract.core.compile import IntentCompiler

    compiler = IntentCompiler()
    compiled = compiler.compile(
        prompt_text,
        WorkspaceSnapshot(files={"tests/test_x.py": "def test_x(): pass"}),
    )
    return compiled.visible if hasattr(compiled, "visible") else compiled


@pytest.fixture
def wired_executor(tmp_path: Path):
    """Executor with all six v4 deps supplied."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    # v0.5.1 wiring module_10 (Lens A C2): state dir unified on ``.ract/``.
    (project_dir / ".ract").mkdir()

    session_key = SessionKey.load_or_create(os.urandom(16))
    sandbox = _KeyStub(os.urandom(16))
    alm = _KeyStub(os.urandom(16))
    ws = WorkspaceSnapshot(
        files={"src/a.py": "x = 1"},
        timestamp=0.0,
    )
    suite = _dummy_suite()

    index = ProvenanceIndex(project_dir)
    # Router is unused for _record_provenance; pass a bare object with
    # the minimum surface Executor expects at construction.
    from ract.providers.router import ProviderRouter

    executor = Executor(
        router=ProviderRouter({}),
        project_dir=project_dir,
        provenance_index=index,
        session_key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_snapshot_provider=lambda: ws,
        prompt_digest_provider=lambda: suite.prompt_digest,
        acceptance_suite_provider=lambda: suite,
        manifest_digest_provider=lambda: Digest(b"\xaa" * 32),
    )
    return {
        "executor": executor,
        "project_dir": project_dir,
        "session_key": session_key,
        "sandbox": sandbox,
        "alm": alm,
        "index": index,
    }


def test_wired_executor_emits_v4_sidecar(wired_executor: dict) -> None:
    """A fully-wired Executor writes a sidecar/v4 sidecar on disk."""
    executor = wired_executor["executor"]
    project_dir = wired_executor["project_dir"]

    artifact_path = project_dir / "out.txt"
    artifact_path.write_text("hello", encoding="utf-8")
    with bind_run_id("rid" + "0" * 29):
        executor._record_provenance(artifact_path, "hello")

    sidecar_path = artifact_path.parent / f".{artifact_path.name}.rootknot.json"
    assert sidecar_path.exists(), "no sidecar written -- wire-in failed"
    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert data["schema"] == "sidecar/v4", (
        f"Executor emitted {data.get('schema')!r} instead of sidecar/v4 "
        "-- Lens D D2 wire-in regression."
    )
    assert data["schema_version"] == 4
    # All four v0.5.1 canonical-bytes participants must be present.
    assert data["workspace_digest"] is not None
    assert data["prompt_digest"] is not None
    assert data["run_id"] == "rid" + "0" * 29
    # The reloaded knot verifies under the session key.
    loaded = wired_executor["index"].load(artifact_path)
    assert loaded is not None
    assert loaded.schema_version == 4
    assert loaded.verify(wired_executor["session_key"].public_key_bytes())


def test_install_v4_provenance_deps_setter_enables_v4_emission(
    tmp_path: Path,
) -> None:
    """SP Q2/Q6 amendment: the setter path also delivers v4 sidecars.

    Verifies the two-step wiring flow the harness -> loop plumbing
    follow-up will use: construct Executor without v4 deps, then
    ``install_v4_provenance_deps(...)`` before the first artifact
    write. Both paths (constructor-wired + setter-wired) must produce
    the same v4 sidecar surface.
    """
    from ract.providers.router import ProviderRouter

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    # v0.5.1 wiring module_10 (Lens A C2): state dir unified on ``.ract/``.
    (project_dir / ".ract").mkdir()

    session_key = SessionKey.load_or_create(os.urandom(16))
    sandbox = _KeyStub(os.urandom(16))
    alm = _KeyStub(os.urandom(16))
    ws = WorkspaceSnapshot(files={"src/a.py": "x = 1"}, timestamp=0.0)
    suite = _dummy_suite("setter path intent")
    index = ProvenanceIndex(project_dir)

    executor = Executor(router=ProviderRouter({}), project_dir=project_dir)
    # Pre-setter: guard branch, no sidecar.
    art1 = project_dir / "before.txt"
    art1.write_text("pre-wire", encoding="utf-8")
    executor._record_provenance(art1, "pre-wire")
    assert not (art1.parent / f".{art1.name}.rootknot.json").exists()

    # Install the deps and re-attempt.
    executor.install_v4_provenance_deps(
        session_key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_snapshot_provider=lambda: ws,
        prompt_digest_provider=lambda: suite.prompt_digest,
        acceptance_suite_provider=lambda: suite,
        manifest_digest_provider=lambda: Digest(b"\xbb" * 32),
        provenance_index=index,
    )
    art2 = project_dir / "after.txt"
    art2.write_text("post-wire", encoding="utf-8")
    with bind_run_id("rid-setter-" + "0" * 21):
        executor._record_provenance(art2, "post-wire")

    sidecar = art2.parent / f".{art2.name}.rootknot.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["schema"] == "sidecar/v4"
    assert data["schema_version"] == 4
    assert data["run_id"] == "rid-setter-" + "0" * 21


def test_unwired_executor_skips_provenance(tmp_path: Path) -> None:
    """An Executor without the six v4 deps skips provenance (no v1 fallback)."""
    from ract.providers.router import ProviderRouter

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    # v0.5.1 wiring module_10 (Lens A C2): state dir unified on ``.ract/``.
    (project_dir / ".ract").mkdir()

    session_key = SessionKey.load_or_create(os.urandom(16))
    index = ProvenanceIndex(project_dir)
    # Deliberately omit the six v4 deps.
    executor = Executor(
        router=ProviderRouter({}),
        project_dir=project_dir,
        provenance_index=index,
        session_key=session_key,
    )
    artifact_path = project_dir / "out.txt"
    artifact_path.write_text("hi", encoding="utf-8")
    executor._record_provenance(artifact_path, "hi")

    # No sidecar written; no SQLite row created.
    sidecar_path = artifact_path.parent / f".{artifact_path.name}.rootknot.json"
    assert not sidecar_path.exists(), (
        "Executor emitted a sidecar without v4 deps -- silent v1 downgrade "
        "detected. The wire-in's whole point is that partial deps produce "
        "NO provenance rather than a weaker attestation."
    )
    assert index.load(artifact_path) is None
