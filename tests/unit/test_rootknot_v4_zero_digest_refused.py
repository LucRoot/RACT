"""v0.5.2 hardening module_01 SP amendment -- zero-digest bypass.

Both Ox Alpha and nemotron_ultra flagged Q5 as a real gap: the
original ``if not self.workspace_digest`` treated
``Digest(b"\x00" * 32)`` as "set" because a zero-filled bytes
subclass is truthy. Semantically the sentinel binds nothing, so it
violated the deep-audit A F-1 intent even though it slipped past
the initial patch.

Fold: post_init AND verifier AND CLI ``_check_knot`` refuse
``workspace_digest == _ZERO_DIGEST`` and ``prompt_digest ==
_ZERO_DIGEST`` alongside ``None``.
"""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import pytest

from ract.core.keys import SessionKey
from ract.core.loop import WorkspaceSnapshot
from ract.core.provenance import ProvenanceIndex, verify_workspace
from ract.core.rootknot import (
    _ZERO_DIGEST,
    GeneratorRef,
    Rootknot,
    RootknotSchemaViolation,
    make_rootknot_v4,
)
from ract.core.types import Digest, digest_bytes, make_plan_id, make_step_id
from ract.core.workspace_digest import compute_prompt_digest, workspace_digest
from ract.security.keys import SandboxKey


class _AlmSigner:
    def __init__(self, seed: bytes) -> None:
        self._key = SessionKey.load_or_create(seed)

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)

    def public_key_bytes(self) -> bytes:
        return self._key.public_key_bytes()


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
        workspace_path="/tmp/zero",
        artifact_digest=Digest(b"\x00" * 32),
        created_at_ns=0,
        generator_signature=b"",
    )


@pytest.mark.parametrize(
    "workspace_digest_v, prompt_digest_v, expected_missing",
    [
        pytest.param(
            _ZERO_DIGEST,
            Digest(b"\xbb" * 32),
            {"workspace_digest"},
            id="zero-workspace-digest",
        ),
        pytest.param(
            Digest(b"\xaa" * 32),
            _ZERO_DIGEST,
            {"prompt_digest"},
            id="zero-prompt-digest",
        ),
        pytest.param(
            _ZERO_DIGEST,
            _ZERO_DIGEST,
            {"workspace_digest", "prompt_digest"},
            id="both-zero",
        ),
    ],
)
def test_zero_digest_refused_at_construction(
    workspace_digest_v, prompt_digest_v, expected_missing
) -> None:
    """Zero-digest sentinel is treated as missing at post_init."""
    with pytest.raises(RootknotSchemaViolation) as excinfo:
        Rootknot(
            **_base_kwargs(),
            schema_version=4,
            workspace_digest=workspace_digest_v,
            prompt_digest=prompt_digest_v,
            run_id="run-zero-test",
        )
    assert set(excinfo.value.missing_fields) == expected_missing


def test_zero_digest_refused_at_verify_via_deserialization_bypass() -> None:
    """A smuggled v4 knot (post_init bypass) with zero digests must fail verify."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        artifact = ws / "artifact.txt"
        artifact.write_bytes(b"payload")

        session_key = SessionKey.load_or_create(b"\x70" * 16)
        sandbox_key = SandboxKey.generate(b"\x71" * 16, workspace_root=ws)
        alm = _AlmSigner(b"\x72" * 16)

        knot = make_rootknot_v4(
            key=session_key,
            sandbox_signer=sandbox_key,
            alm_signer=alm,
            workspace_path="artifact.txt",
            artifact_digest=digest_bytes(b"payload"),
            assumption_digest=digest_bytes(b"assume"),
            acceptance_suite_digest=digest_bytes(b"suite"),
            predicate_results=(digest_bytes(b"pred-1"),),
            manifest_digest=digest_bytes(b"manifest"),
            gate_results=(),
            workspace_digest=workspace_digest(
                WorkspaceSnapshot(files={}, timestamp=0.0)
            ),
            prompt_digest=compute_prompt_digest("intent"),
            run_id="run-zero-verify",
        )
        # Simulate copy.copy bypass: overwrite workspace_digest to
        # the zero sentinel. post_init did not fire; verifier must
        # catch.
        smuggled = copy.copy(knot)
        object.__setattr__(smuggled, "workspace_digest", _ZERO_DIGEST)

        index = ProvenanceIndex(ws)
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
            sandbox_pubkey=lambda _k: sandbox_key.public,
            registered_suites={digest_bytes(b"suite")},
            registered_manifests={digest_bytes(b"manifest")},
            alm_pubkey=lambda _k: alm.public_key_bytes(),
        )
        assert not result.is_ok()
        violation = result.unwrap_err()
        assert violation.predicate == "RK-V4-LABEL-MISMATCH"
        assert "workspace_digest" in violation.detail


# RACT 0.5.2
