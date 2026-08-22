"""v0.5.2 hardening module_01 -- ``Rootknot.__post_init__`` v4 gate.

Closes deep-audit A F-1 + F-5 (systemic): a
``Rootknot(schema_version=4, workspace_digest=None,
prompt_digest=None, run_id="")`` was a legal construction under
v0.5.1; ``canonical_bytes()`` emitted the v4 fields only when
truthy, so an attacker holding a SessionKey could mint a v4-labelled
attestation that bound nothing. v0.5.2 module_01 promotes the
factory-guard (which was documentation) to a construction-time
invariant on the dataclass itself.

Companion tests:
- ``tests/unit/test_rootknot_downgrade_defense.py`` (M-1)
- ``tests/unit/test_rootknot_forward_compat_reject.py`` (M-2)
- ``tests/unit/test_rootknot_v4_missing_field_verify_fails.py`` (F-2)

Ox Alpha co-build (2026-08-22) Fork 3 gotcha #2: this construction
gate is defense-in-depth; the verifier-side ``_check_rk3`` check is
authoritative because ``copy`` / ``pickle`` restore paths bypass
``__init__`` / ``__post_init__``.
"""

from __future__ import annotations

import pytest

from ract.core.rootknot import (
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
        workspace_path="/tmp/v4-gate",
        artifact_digest=Digest(b"\x00" * 32),
        created_at_ns=0,
        generator_signature=b"",
    )


@pytest.mark.parametrize(
    "kwargs, expected_missing",
    [
        pytest.param(
            {},
            {"workspace_digest", "prompt_digest", "run_id"},
            id="all-fields-empty",
        ),
        pytest.param(
            {"workspace_digest": Digest(b"\xaa" * 32)},
            {"prompt_digest", "run_id"},
            id="only-workspace-digest",
        ),
        pytest.param(
            {
                "workspace_digest": Digest(b"\xaa" * 32),
                "prompt_digest": Digest(b"\xbb" * 32),
            },
            {"run_id"},
            id="workspace-and-prompt-only",
        ),
        pytest.param(
            {
                "workspace_digest": Digest(b"\xaa" * 32),
                "run_id": "run-42",
            },
            {"prompt_digest"},
            id="workspace-and-run-only",
        ),
        pytest.param(
            {
                "prompt_digest": Digest(b"\xbb" * 32),
                "run_id": "run-42",
            },
            {"workspace_digest"},
            id="prompt-and-run-only",
        ),
        pytest.param(
            {
                "workspace_digest": Digest(b"\xaa" * 32),
                "prompt_digest": Digest(b"\xbb" * 32),
                "run_id": "",
            },
            {"run_id"},
            id="run-id-empty-string",
        ),
    ],
)
def test_v4_construction_with_missing_field_raises(kwargs, expected_missing) -> None:
    """v4-label with any missing v4 field must raise at construction."""
    with pytest.raises(RootknotSchemaViolation) as excinfo:
        Rootknot(**_base_kwargs(), schema_version=4, **kwargs)
    assert excinfo.value.schema_version == 4
    assert set(excinfo.value.missing_fields) == expected_missing
    # Reason string names each missing field for CLI diagnostics.
    for field_name in expected_missing:
        assert field_name in excinfo.value.reason


def test_v4_construction_with_all_fields_succeeds() -> None:
    """v4-label with all three v4 fields non-empty is legal."""
    knot = Rootknot(
        **_base_kwargs(),
        schema_version=4,
        workspace_digest=Digest(b"\xaa" * 32),
        prompt_digest=Digest(b"\xbb" * 32),
        run_id="run-ok",
    )
    assert knot.schema_version == 4
    assert knot.workspace_digest == Digest(b"\xaa" * 32)
    assert knot.prompt_digest == Digest(b"\xbb" * 32)
    assert knot.run_id == "run-ok"


def test_v1_v2_v3_constructions_unaffected() -> None:
    """The v4 invariant does NOT apply to v1/v2/v3 labels (backward-compat)."""
    for version in (1, 2, 3):
        knot = Rootknot(**_base_kwargs(), schema_version=version)
        assert knot.schema_version == version
        assert knot.workspace_digest is None
        assert knot.prompt_digest is None
        assert knot.run_id == ""


def test_rootknotschemaviolation_is_valueerror() -> None:
    """Exception is a ``ValueError`` subclass (dataclass convention)."""
    assert issubclass(RootknotSchemaViolation, ValueError)


# RACT 0.5.2
