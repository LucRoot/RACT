"""Executor provenance wiring: every artifact write is signed + indexed.

Asserts that when an Executor is configured with a ProvenanceIndex + SessionKey
AND the six v4 Rootknot deps introduced in v0.5.1 wiring module_02, a write
through the executor produces both a SQLite index entry and a sidecar file
carrying a verifiable Rootknot. This is the ADR-0001 contract enforced at
the executor chokepoint (v0.3 Module 5) with the v0.5.1 module_02 v4 upgrade.

v0.5.1 wiring module_10 (pre-existing test failure fix): module_02's v4
wire-in intentionally refuses to downgrade to v1/v3 when any of the six
v4 deps is missing -- silent downgrade would defeat the wire-in's whole
point (a v4-shipping executor that fires v1 knots leaves the audit unable
to trust the "every knot is v4" invariant). The pre-module_10 shape of
this fixture supplied ``provenance_index`` + ``session_key`` only and
tripped the missing-deps guard, causing the write to skip provenance
entirely. Fix: supply the six v4 deps (matching
:mod:`tests.integration.test_executor_v4_provenance_wire` -- the two
tests now share the same wiring contract).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ract.core.keys import SessionKey
from ract.core.loop import WorkspaceSnapshot
from ract.core.provenance import ProvenanceIndex
from ract.core.types import Digest, digest_bytes
from ract.executor import Executor
from ract.runtime import bind_run_id


class _KeyStub:
    """Minimal signer wrapping a SessionKey for the v4 wire-in."""

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


def _make_executor(tmp_path: Path) -> tuple[Executor, ProvenanceIndex, SessionKey]:
    """Build an Executor with all six v0.5.1 module_02 v4 deps supplied.

    Pre-module_10 shape supplied only ``provenance_index`` + ``session_key``
    and tripped the module_02 v4 missing-deps guard. The upgraded fixture
    supplies the full six-dep surface so ``_record_provenance`` fires
    a v4 Rootknot end-to-end.
    """
    index = ProvenanceIndex(tmp_path)
    key = SessionKey.load_or_create(b"\x10" * 16, state_dir=tmp_path / "state")
    sandbox = _KeyStub(b"\x11" * 16)
    alm = _KeyStub(b"\x12" * 16)
    ws = WorkspaceSnapshot(files={"src/a.py": "x = 1"}, timestamp=0.0)
    suite = _dummy_suite()

    router = MagicMock()
    executor = Executor(
        router=router,
        project_dir=tmp_path,
        provenance_index=index,
        session_key=key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_snapshot_provider=lambda: ws,
        prompt_digest_provider=lambda: suite.prompt_digest,
        acceptance_suite_provider=lambda: suite,
        manifest_digest_provider=lambda: Digest(b"\xaa" * 32),
    )
    return executor, index, key


def test_write_artifact_records_rootknot_in_index(tmp_path: Path) -> None:
    executor, index, key = _make_executor(tmp_path)
    with bind_run_id("rid" + "0" * 29):
        executor._write_artifact("src/hello.py", "print('hi')\n")

    artifact = tmp_path / "src" / "hello.py"
    assert artifact.is_file(), "artifact must be written"
    knot = index.load(artifact)
    assert knot is not None, "executor write must index a Rootknot"
    assert knot.verify(key.public_key_bytes()), "indexed rootknot must verify"
    # The recorded digest matches the artifact content.
    assert knot.artifact_digest == digest_bytes(b"print('hi')\n")
    # v0.5.1 wiring module_02: every executor-written Rootknot is v4.
    assert knot.schema_version == 4, (
        f"expected v4 knot; got schema_version={knot.schema_version}"
    )


def test_write_artifact_emits_sidecar(tmp_path: Path) -> None:
    executor, _index, _key = _make_executor(tmp_path)
    with bind_run_id("rid" + "1" * 29):
        executor._write_artifact("src/hello.py", "print('hi')\n")

    artifact = tmp_path / "src" / "hello.py"
    sidecar = artifact.parent / f".{artifact.name}.rootknot.json"
    assert sidecar.is_file(), "executor write must emit a sidecar"
    import json

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    # v0.5.1 wiring module_02: sidecar/v4 carries three signatures
    # (generator + environment + antilazy) rather than the pre-v4
    # single ``signature`` field.
    assert payload.get("schema") == "sidecar/v4"
    for sig_field in (
        "generator_signature",
        "environment_signature",
        "antilazy_signature",
    ):
        assert sig_field in payload, f"sidecar missing {sig_field!r}"
    assert payload["workspace_path"].endswith("src/hello.py")


def test_executor_without_provenance_config_writes_without_indexing(
    tmp_path: Path,
) -> None:
    """An executor with no provenance wiring must not create any index/sidecar.

    Guards the default behavior: existing callers (and all pre-v0.3 tests) get
    unchanged semantics — a plain write, no .ract directory created.
    """
    router = MagicMock()
    executor = Executor(router=router, project_dir=tmp_path)
    executor._write_artifact("src/hello.py", "print('hi')\n")
    assert (tmp_path / "src" / "hello.py").is_file()
    # v0.5.1 wiring module_10 (Lens A C2): workspace-state canonical
    # directory unified on ``.ract/``. The unwired-executor case must
    # not touch either the modern or legacy directory.
    assert not (tmp_path / ".ract").exists(), "no .ract index must be created"
    assert not (tmp_path / ".rack").exists(), "no legacy .rack index must be created"
    sidecar = tmp_path / "src" / ".hello.py.rootknot.json"
    assert not sidecar.exists(), "no sidecar must be created"


# RACT 0.5.1 -- v0.5.1 wiring module_10 (test_write_artifact_records_rootknot_in_index fix)
