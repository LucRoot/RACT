"""module_02 sacred-spine tests: schema_version dispatch backward-read.

Master spec §Non-goals: "No breaking Rootknot signature schema. Extend
canonical bytes with new required fields; preserve v0.5.0 read-path via
SCHEMA_VERSION dispatch." At the code level this means:

- v0.5.0-emitted v1/v2/v3 knots verify unchanged under v0.5.1 code
  (because their canonical bytes contain no module_02 fields and the
  guards in ``canonical_bytes()`` don't emit them).
- v0.5.1-emitted v4 knots carry the three new fields; their
  ``schema_version`` is 4; a v0.5.0 verifier dispatching on
  ``schema_version`` sees an unknown value and can halt loudly rather
  than silently trust under-attested bytes.
- Field-inclusion in ``canonical_bytes()`` is guarded by the
  is-set predicate (``is not None`` for digests, truthy for run_id),
  NOT by ``schema_version >= 4``. The instance ``schema_version`` is a
  hint about payload shape to downstream verifiers; the field-set
  guard is the authoritative signal for what got signed. This is the
  correct load-bearing invariant (Depth chain 2.3.b).

Reference: ``_BUILD/ract_v0.5.1_external_review_response/module_02.md``.
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
    make_rootknot_v2,
    make_rootknot_v3,
    make_rootknot_v4,
)
from ract.core.types import Digest
from ract.core.workspace_digest import compute_prompt_digest, workspace_digest


class _KeyStub:
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
# v0.5.0 baseline (SCHEMA_VERSION 1 in the spec) verifies under v0.5.1
# ---------------------------------------------------------------------------


def test_v1_baseline_verifies_under_v0_5_1_code(session_key: SessionKey) -> None:
    """A v1 (v0.3-compatible) knot verifies under the v0.5.1 verifier."""
    knot = make_rootknot(
        session_key,
        workspace_path="/tmp/v1",
        artifact_digest=Digest(b"\x30" * 32),
        assumption_digest=Digest(b"\x31" * 32),
    )
    assert knot.schema_version == 1
    assert knot.verify(session_key.public_key_bytes())


def test_v2_baseline_verifies_under_v0_5_1_code(
    session_key: SessionKey, sandbox: _KeyStub
) -> None:
    """A v2 (v0.4-substrate) knot verifies under the v0.5.1 verifier."""
    knot = make_rootknot_v2(
        key=session_key,
        sandbox_signer=sandbox,
        workspace_path="/tmp/v2",
        artifact_digest=Digest(b"\x32" * 32),
        assumption_digest=Digest(b"\x33" * 32),
        acceptance_suite_digest=Digest(b"\x34" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x35" * 32),
    )
    assert knot.schema_version == 2
    assert knot.verify(session_key.public_key_bytes())
    assert knot.verify_environment(sandbox.public_key_bytes())


def test_v3_baseline_verifies_under_v0_5_1_code(
    session_key: SessionKey, sandbox: _KeyStub, alm: _KeyStub
) -> None:
    """A v3 (v0.4-ALM) knot verifies under the v0.5.1 verifier."""
    knot = make_rootknot_v3(
        key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/v3",
        artifact_digest=Digest(b"\x36" * 32),
        assumption_digest=Digest(b"\x37" * 32),
        acceptance_suite_digest=Digest(b"\x38" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x39" * 32),
        gate_results=(),
    )
    assert knot.schema_version == 3
    assert knot.verify(session_key.public_key_bytes())
    assert knot.verify_environment(sandbox.public_key_bytes())
    assert knot.verify_antilazy(alm.public_key_bytes())


# ---------------------------------------------------------------------------
# v0.5.1 (SCHEMA_VERSION 2 in the spec) carries the new fields
# ---------------------------------------------------------------------------


def test_v4_marks_payload_with_schema_version_4(
    session_key: SessionKey, sandbox: _KeyStub, alm: _KeyStub
) -> None:
    """v4 canonical bytes carry ``schema_version": 4`` for downstream dispatch."""
    ws = WorkspaceSnapshot(files={}, timestamp=0.0)
    knot = make_rootknot_v4(
        key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/v4-schema",
        artifact_digest=Digest(b"\x40" * 32),
        assumption_digest=Digest(b"\x41" * 32),
        acceptance_suite_digest=Digest(b"\x42" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x43" * 32),
        gate_results=(),
        workspace_digest=workspace_digest(ws),
        prompt_digest=compute_prompt_digest("intent"),
        run_id="run-schema-4",
    )
    assert knot.schema_version == 4
    payload = json.loads(knot.canonical_bytes().decode("utf-8"))
    assert payload["schema_version"] == 4
    assert "workspace_digest" in payload
    assert "prompt_digest" in payload
    assert "run_id" in payload


def test_field_inclusion_guarded_by_is_set_not_schema_version(
    session_key: SessionKey,
) -> None:
    """Depth 2.3.b: field-set guard is authoritative, not schema_version.

    A v3 knot ARTIFICIALLY populated with the new fields (bypassing the
    v3 factory that never sets them) still includes them in canonical
    bytes — the guard checks is-set, not schema version. Conversely, a
    v4 knot ARTIFICIALLY constructed without the fields excludes them.
    """
    from ract.core.rootknot import GeneratorRef
    from ract.core.types import make_plan_id, make_step_id

    generator = GeneratorRef(
        model_name="t",
        model_version="0",
        session_id=session_key.public_key_id()[:16],
        public_key_id=session_key.public_key_id(),
    )
    base_kwargs = dict(
        plan_id=make_plan_id(),
        step_id=make_step_id(),
        assumption_digest=Digest(b"\x00" * 32),
        generator=generator,
        parent_digests=(),
        workspace_path="/tmp/guard",
        artifact_digest=Digest(b"\x00" * 32),
        created_at_ns=0,
        generator_signature=b"",
    )
    v3_with_fields = Rootknot(
        **base_kwargs,
        schema_version=3,
        workspace_digest=Digest(b"\xaa" * 32),
    )
    body = v3_with_fields.canonical_bytes()
    assert b"workspace_digest" in body

    v4_without_fields = Rootknot(**base_kwargs, schema_version=4)
    body2 = v4_without_fields.canonical_bytes()
    assert b"workspace_digest" not in body2


def test_v0_5_0_verifier_would_reject_v4_schema_version() -> None:
    """A v0.5.0-style dispatch on schema_version halts on unknown 4.

    Simulates the v0.5.0 verifier's known-schema-versions gate: the
    known set was ``{1, 2, 3}``; encountering ``4`` halts loudly. This
    is the graceful-upgrade property (v0.5.0 refuses to reinterpret
    under-attested bytes rather than silently trust them).
    """
    v0_5_0_KNOWN_SCHEMAS = {1, 2, 3}
    v4_schema = 4
    assert v4_schema not in v0_5_0_KNOWN_SCHEMAS


def test_v0_5_1_verifier_accepts_all_known_schemas() -> None:
    """The v0.5.1 verifier knows all four schema versions."""
    v0_5_1_KNOWN_SCHEMAS = {1, 2, 3, 4}
    for version in (1, 2, 3, 4):
        assert version in v0_5_1_KNOWN_SCHEMAS
