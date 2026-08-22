"""v0.5.2 hardening module_01 -- unknown schema_version refused.

Closes Ox Alpha M-2 (MED-HIGH): the v0.5.1 verifier's
``if knot.schema_version < 3`` funnel accepted any unknown major
(5, 9, 42) under drifted v3 semantics. That is a check-dodging
primitive once v4 carries stricter invariants than v3 -- an attacker
labels a weak knot with an unimplemented high version and falls
back to the weakest implemented semantics.

The v0.5.2 fix keeps a known-versions allowlist
(:data:`ract.core.rootknot._KNOWN_SCHEMA_VERSIONS` = ``{1,2,3,4}``)
and refuses anything else with ``RK-UNKNOWN-SCHEMA`` at verify time
AND ``RootknotSchemaViolation`` at construction time. Ox Alpha
co-build (2026-08-22) Fork 2: fail-closed at both edges; v0.5 tool
reading a v0.6 sidecar refuses with a loud, actionable reason
(operator upgrades) rather than silently mis-verifying under
guessed semantics.
"""

from __future__ import annotations

import tempfile

import pytest

from ract.core.rootknot import (
    _KNOWN_SCHEMA_VERSIONS,
    GeneratorRef,
    Rootknot,
    RootknotSchemaViolation,
)
from ract.core.types import Digest, make_plan_id, make_step_id


def _base_kwargs() -> dict:
    generator = GeneratorRef(
        model_name="t",
        model_version="0",
        session_id=b"\x00" * 16,
        public_key_id=Digest(b"\x00" * 32),
    )
    return dict(
        plan_id=make_plan_id(),
        step_id=make_step_id(),
        assumption_digest=Digest(b"\x00" * 32),
        generator=generator,
        parent_digests=(),
        workspace_path="/tmp/unknown",
        artifact_digest=Digest(b"\x00" * 32),
        created_at_ns=0,
        generator_signature=b"",
    )


@pytest.mark.parametrize("unknown_version", [0, 5, 6, 7, 9, 42, 100])
def test_unknown_schema_version_construction_raises(unknown_version: int) -> None:
    """``__post_init__`` refuses unknown-major constructions."""
    with pytest.raises(RootknotSchemaViolation) as excinfo:
        Rootknot(**_base_kwargs(), schema_version=unknown_version)
    assert excinfo.value.schema_version == unknown_version
    assert excinfo.value.missing_fields == []
    assert "unknown schema_version" in excinfo.value.reason
    assert "1, 2, 3, 4" in excinfo.value.reason or "1,2,3,4" in excinfo.value.reason


def test_known_schema_versions_allowlist_shape() -> None:
    """The allowlist is exactly ``{1, 2, 3, 4}`` (the four v0.5.1-known majors)."""
    assert _KNOWN_SCHEMA_VERSIONS == frozenset({1, 2, 3, 4})


def test_verifier_side_refuses_unknown_via_construction_bypass() -> None:
    """A knot pickled/restored bypasses ``__post_init__``; verify still refuses.

    Simulates the Ox Alpha Fork 3 gotcha #2 concern: deserialisation
    paths bypass ``__init__``. The verifier-side allowlist check in
    :func:`ract.core.provenance._classify_violation` must remain
    authoritative regardless.
    """
    import copy
    from pathlib import Path as _P

    from ract.core.keys import SessionKey
    from ract.core.provenance import ProvenanceIndex, verify_workspace
    from ract.core.rootknot import make_rootknot
    from ract.core.types import digest_bytes

    session_key = SessionKey.load_or_create(b"\x40" * 16)
    with tempfile.TemporaryDirectory() as tmp:
        ws = _P(tmp)
        artifact = ws / "artifact.txt"
        artifact.write_bytes(b"payload")
        v1 = make_rootknot(
            session_key,
            workspace_path="artifact.txt",
            artifact_digest=digest_bytes(b"payload"),
            assumption_digest=digest_bytes(b"assume"),
        )
        # Bypass post_init by copying the frozen dataclass then
        # object.__setattr__ to a bogus schema_version. This mirrors
        # what a pickle round-trip or an attacker-crafted deserialiser
        # could produce, exercising the verifier-side allowlist.
        smuggled = copy.copy(v1)
        object.__setattr__(smuggled, "schema_version", 9)

        # Rewire the index to hold the smuggled knot without going
        # through save() (which itself would re-serialise cleanly).
        index = ProvenanceIndex(ws)
        # Direct in-memory install: monkey-patch all_knots for this
        # test so we exercise the verifier's allowlist check.
        index.all_knots = lambda: {"artifact.txt": smuggled}  # type: ignore[method-assign]

        result = verify_workspace(
            index,
            active_plans={smuggled.plan_id: [smuggled.step_id]},
            registered_assumptions={
                smuggled.assumption_digest: type(
                    "A", (), {"state": type("S", (), {"name": "ACTIVE"})()}
                )()
            },
            generator_pubkey=lambda _g: session_key.public_key_bytes(),
        )
        assert not result.is_ok()
        violation = result.unwrap_err()
        assert violation.predicate == "RK-UNKNOWN-SCHEMA"
        assert "schema_version=9" in violation.detail


# RACT 0.5.2
