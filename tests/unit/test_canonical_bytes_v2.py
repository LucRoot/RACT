"""module_02 sacred-spine tests: v4 Rootknot canonical-bytes extensions.

The v0.5.1 module_02 fragment adds three OPT-IN fields to
:class:`ract.core.rootknot.Rootknot`'s signed canonical bytes:
``workspace_digest``, ``prompt_digest``, and ``run_id``. Each rides
inside the payload the three signatures attest over. The three fields
are populated by :func:`ract.core.rootknot.make_rootknot_v4`; a v0.5.0
v3 knot lacking them hashes byte-identically to today (backward-read
invariant).

These tests exercise:

- All three fields appear in the canonical bytes of a v4 knot.
- ``workspace_digest`` is deterministic for identical snapshots.
- ``workspace_digest`` differs when a snapshot file byte changes.
- ``prompt_digest`` differs on any UTF-8 byte-level change.
- ``run_id`` round-trips through canonical bytes as an exact string.
- Backward-compat: v1/v2/v3 knots produce byte-identical canonical
  bytes to the v0.5.0 baseline.

Reference:
- ``_BUILD/ract_v0.5.1_external_review_response/module_02.md`` §Depth
  chain leaves L1-L8.
- ``docs/RACT_v0.5.1_EXTERNAL_REVIEW_RESPONSE_SPEC.md`` §4 module_02.
"""

from __future__ import annotations

import json
import os

import pytest

from ract.core.keys import SessionKey
from ract.core.loop import WorkspaceSnapshot
from ract.core.rootknot import (
    Rootknot,
    make_rootknot,
    make_rootknot_v3,
    make_rootknot_v4,
)
from ract.core.types import Digest
from ract.core.workspace_digest import (
    compute_prompt_digest,
    run_id_hex,
    workspace_digest,
)


class _KeyStub:
    """Minimal signer stub matching the SandboxKey / AlmVerifierKey shape."""

    def __init__(self, seed: bytes) -> None:
        self._key = SessionKey.load_or_create(seed)

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)

    def public_key_bytes(self) -> bytes:
        return self._key.public_key_bytes()


@pytest.fixture
def session_key() -> SessionKey:
    return SessionKey.load_or_create(os.urandom(16))


@pytest.fixture
def sandbox() -> _KeyStub:
    return _KeyStub(os.urandom(16))


@pytest.fixture
def alm() -> _KeyStub:
    return _KeyStub(os.urandom(16))


# ---------------------------------------------------------------------------
# Field-inclusion tests
# ---------------------------------------------------------------------------


def test_v4_canonical_bytes_include_workspace_digest(
    session_key: SessionKey, sandbox: _KeyStub, alm: _KeyStub
) -> None:
    """Leaf L6: v4 canonical bytes contain the workspace_digest hex string."""
    ws = WorkspaceSnapshot(files={"a.py": "print('hi')"}, timestamp=1.0)
    wd = workspace_digest(ws)
    knot = make_rootknot_v4(
        key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/v4",
        artifact_digest=Digest(b"\x01" * 32),
        assumption_digest=Digest(b"\x02" * 32),
        acceptance_suite_digest=Digest(b"\x03" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x04" * 32),
        gate_results=(),
        workspace_digest=wd,
        prompt_digest=compute_prompt_digest("do the thing"),
        run_id="run-abc-123",
    )
    body = knot.canonical_bytes()
    assert b'"workspace_digest":"' + wd.hex().encode() + b'"' in body
    assert b'"run_id":"run-abc-123"' in body
    assert b'"prompt_digest":"' in body
    # Signatures verify over the extended payload.
    assert knot.verify(session_key.public_key_bytes())
    assert knot.verify_environment(sandbox.public_key_bytes())
    assert knot.verify_antilazy(alm.public_key_bytes())


def test_v4_run_id_roundtrips_through_canonical_bytes(
    session_key: SessionKey, sandbox: _KeyStub, alm: _KeyStub
) -> None:
    """Leaf L4: run_id round-trips as an exact string."""
    ws = WorkspaceSnapshot(files={}, timestamp=0.0)
    run_id = run_id_hex()
    knot = make_rootknot_v4(
        key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/roundtrip",
        artifact_digest=Digest(b"\x05" * 32),
        assumption_digest=Digest(b"\x06" * 32),
        acceptance_suite_digest=Digest(b"\x07" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x08" * 32),
        gate_results=(),
        workspace_digest=workspace_digest(ws),
        prompt_digest=compute_prompt_digest("x"),
        run_id=run_id,
    )
    parsed = json.loads(knot.canonical_bytes().decode("utf-8"))
    assert parsed["run_id"] == run_id


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------


def test_workspace_digest_deterministic_for_identical_snapshot() -> None:
    """Leaf L1: same snapshot → same digest across calls."""
    ws = WorkspaceSnapshot(
        files={"src/a.py": "x = 1\n", "src/b.py": "y = 2\n"},
        timestamp=1234.5,
        metadata={"pytest_returncode": 0},
    )
    assert workspace_digest(ws) == workspace_digest(ws)


def test_workspace_digest_differs_on_single_byte_flip() -> None:
    """Leaf L2: single byte-flip in file content → different digest."""
    ws1 = WorkspaceSnapshot(files={"a.py": "x = 1\n"}, timestamp=0.0)
    ws2 = WorkspaceSnapshot(files={"a.py": "x = 2\n"}, timestamp=0.0)
    assert workspace_digest(ws1) != workspace_digest(ws2)


def test_workspace_digest_differs_on_metadata_change() -> None:
    """Metadata change also propagates to workspace_digest."""
    ws1 = WorkspaceSnapshot(files={"a.py": "x"}, timestamp=0.0, metadata={"k": 1})
    ws2 = WorkspaceSnapshot(files={"a.py": "x"}, timestamp=0.0, metadata={"k": 2})
    assert workspace_digest(ws1) != workspace_digest(ws2)


def test_workspace_digest_stable_across_files_dict_insertion_order() -> None:
    """Insertion order into ``files`` dict must not perturb the digest."""
    ws1 = WorkspaceSnapshot(files={"a.py": "1", "b.py": "2"}, timestamp=0.0)
    ws2 = WorkspaceSnapshot(files={"b.py": "2", "a.py": "1"}, timestamp=0.0)
    assert workspace_digest(ws1) == workspace_digest(ws2)


def test_compute_prompt_digest_case_sensitive() -> None:
    """Leaf L3: UTF-8 byte-level sensitivity."""
    assert compute_prompt_digest("hello") != compute_prompt_digest("Hello")


def test_compute_prompt_digest_deterministic() -> None:
    """Same text → same digest."""
    text = "compile a suite for adding two integers"
    assert compute_prompt_digest(text) == compute_prompt_digest(text)


def test_compute_prompt_digest_unicode_stable() -> None:
    """Non-ASCII text hashes stably under UTF-8."""
    d1 = compute_prompt_digest("build the naïve implementation")
    d2 = compute_prompt_digest("build the naïve implementation")
    assert d1 == d2
    assert d1 != compute_prompt_digest("build the naive implementation")


# ---------------------------------------------------------------------------
# Backward-compat tests
# ---------------------------------------------------------------------------


def test_v1_knot_canonical_bytes_unchanged_by_module_02(
    session_key: SessionKey,
) -> None:
    """Leaf L5: v1 knot without new fields hashes identically to v0.5.0."""
    knot = make_rootknot(
        session_key,
        workspace_path="/tmp/v1-baseline",
        artifact_digest=Digest(b"\x0a" * 32),
        assumption_digest=Digest(b"\x0b" * 32),
    )
    body = knot.canonical_bytes()
    # None of the module_02 keys leak into a v1 knot.
    assert b"workspace_digest" not in body
    assert b"prompt_digest" not in body
    assert b"run_id" not in body
    assert knot.verify(session_key.public_key_bytes())


def test_v3_knot_canonical_bytes_unchanged_by_module_02(
    session_key: SessionKey, sandbox: _KeyStub, alm: _KeyStub
) -> None:
    """Leaf L5 extended: v3 knot without new fields hashes identically."""
    knot = make_rootknot_v3(
        key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/v3-baseline",
        artifact_digest=Digest(b"\x0c" * 32),
        assumption_digest=Digest(b"\x0d" * 32),
        acceptance_suite_digest=Digest(b"\x0e" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x0f" * 32),
        gate_results=(),
    )
    body = knot.canonical_bytes()
    assert b"workspace_digest" not in body
    assert b"prompt_digest" not in body
    assert b"run_id" not in body
    assert knot.verify(session_key.public_key_bytes())
    assert knot.verify_environment(sandbox.public_key_bytes())
    assert knot.verify_antilazy(alm.public_key_bytes())


def test_v4_construction_rejects_none_fields(
    session_key: SessionKey, sandbox: _KeyStub, alm: _KeyStub
) -> None:
    """make_rootknot_v4 raises on any missing required v0.5.1 field."""
    common = dict(
        key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/reject",
        artifact_digest=Digest(b"\x11" * 32),
        assumption_digest=Digest(b"\x12" * 32),
        acceptance_suite_digest=Digest(b"\x13" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x14" * 32),
        gate_results=(),
    )
    with pytest.raises(ValueError, match="workspace_digest"):
        make_rootknot_v4(
            **common,
            workspace_digest=None,  # type: ignore[arg-type]
            prompt_digest=compute_prompt_digest("x"),
            run_id="r1",
        )
    with pytest.raises(ValueError, match="prompt_digest"):
        make_rootknot_v4(
            **common,
            workspace_digest=Digest(b"\x00" * 32),
            prompt_digest=None,  # type: ignore[arg-type]
            run_id="r1",
        )
    with pytest.raises(ValueError, match="run_id"):
        make_rootknot_v4(
            **common,
            workspace_digest=Digest(b"\x00" * 32),
            prompt_digest=compute_prompt_digest("x"),
            run_id="",
        )


def test_v4_field_changes_signature(
    session_key: SessionKey, sandbox: _KeyStub, alm: _KeyStub
) -> None:
    """A v4 knot with different workspace_digest values has different signed bytes."""
    ws1 = WorkspaceSnapshot(files={"a.py": "x = 1"}, timestamp=0.0)
    ws2 = WorkspaceSnapshot(files={"a.py": "x = 2"}, timestamp=0.0)
    common = dict(
        key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/differ",
        artifact_digest=Digest(b"\x21" * 32),
        assumption_digest=Digest(b"\x22" * 32),
        acceptance_suite_digest=Digest(b"\x23" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x24" * 32),
        gate_results=(),
        prompt_digest=compute_prompt_digest("intent"),
        run_id="run-x",
    )
    a = make_rootknot_v4(**common, workspace_digest=workspace_digest(ws1))
    b = make_rootknot_v4(**common, workspace_digest=workspace_digest(ws2))
    assert a.canonical_bytes() != b.canonical_bytes()
    assert a.generator_signature != b.generator_signature


def test_v4_sign_preserves_new_fields(session_key: SessionKey) -> None:
    """Rootknot.sign() must preserve workspace_digest, prompt_digest, run_id."""
    from ract.core.types import make_plan_id, make_step_id
    from ract.core.rootknot import GeneratorRef

    generator = GeneratorRef(
        model_name="test",
        model_version="0",
        session_id=session_key.public_key_id()[:16],
        public_key_id=session_key.public_key_id(),
    )
    wd = Digest(b"\xaa" * 32)
    pd = Digest(b"\xbb" * 32)
    knot = Rootknot(
        plan_id=make_plan_id(),
        step_id=make_step_id(),
        assumption_digest=Digest(b"\x00" * 32),
        generator=generator,
        parent_digests=(),
        workspace_path="/tmp/preserve",
        artifact_digest=Digest(b"\x00" * 32),
        created_at_ns=0,
        generator_signature=b"",
        workspace_digest=wd,
        prompt_digest=pd,
        run_id="preserve-me",
    )
    signed = knot.sign(session_key)
    assert signed.workspace_digest == wd
    assert signed.prompt_digest == pd
    assert signed.run_id == "preserve-me"
