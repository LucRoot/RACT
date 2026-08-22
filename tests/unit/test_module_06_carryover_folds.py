"""v0.5.2 hardening module_06 -- carryover folds.

Master spec: ``docs/RACT_v0.5.2_HARDENING_SPEC.md`` §5 module_06.

Fold verdicts (Ox Alpha co-build Q1 MUST-FOLD):

- module_01 Q3 -- ``_knot_from_json`` refuses unknown ``schema``
  literals rather than silently downgrading to the v1 shape.
  Pairs with module_04's ``write_sidecar_header`` primitive so
  UNKNOWN sidecar formats fail loudly at ingest.
- module_04 C-6 -- :func:`bootstrap_ambient_from_env` validates
  ``RACT_RUN_ID`` against ``^RUN-[A-Za-z0-9_-]{1,240}$`` at the
  trust boundary. Poisoned parent env yields an orphan run + a
  WARN, not a path-shape vector into module_05's sidecar path.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# module_01 Q3 fold: unknown sidecar schema refusal
# ---------------------------------------------------------------------------


class TestKnotFromJsonUnknownSchemaRefused:
    def test_unknown_schema_v9_refused(self) -> None:
        import json

        from ract.core.provenance import (
            RootknotUnknownSidecarFormat,
            _knot_from_json,
        )

        # Well-formed enough to reach the schema dispatch; the
        # unknown ``schema`` string is what must trip the refusal.
        payload = json.dumps(
            {
                "schema": "sidecar/v9",
                "plan_id": "00" * 32,
                "step_id": "00" * 32,
                "assumption_digest": "00" * 32,
                "generator": {
                    "model_name": "m",
                    "model_version": "v",
                    "session_id": "00" * 32,
                    "public_key_id": "00" * 32,
                },
                "parent_digests": [],
                "workspace_path": "/tmp/x",
                "artifact_digest": "00" * 32,
                "created_at_ns": 1,
                "signature": "00" * 32,
            }
        )
        with pytest.raises(RootknotUnknownSidecarFormat, match="sidecar/v9"):
            _knot_from_json(payload)

    def test_absent_schema_falls_through_to_v1(self) -> None:
        # A legacy v0.3 v1 payload has NO ``schema`` field; the
        # fall-through path is preserved so v0.5.1 payloads keep
        # loading.
        import json

        from ract.core.provenance import _knot_from_json

        payload = json.dumps(
            {
                "plan_id": "00" * 32,
                "step_id": "00" * 32,
                "assumption_digest": "00" * 32,
                "generator": {
                    "model_name": "m",
                    "model_version": "v",
                    "session_id": "00" * 32,
                    "public_key_id": "00" * 32,
                },
                "parent_digests": [],
                "workspace_path": "/tmp/x",
                "artifact_digest": "00" * 32,
                "created_at_ns": 1,
                "signature": "00" * 32,
            }
        )
        # Legacy path -- must load without raising.
        k = _knot_from_json(payload)
        assert k.schema_version == 1


# ---------------------------------------------------------------------------
# module_04 C-6 fold: RACT_RUN_ID format validation at boundary
# ---------------------------------------------------------------------------


class TestRunIdFormatValidation:
    def test_normalize_accepts_run_uuid(self) -> None:
        from ract.runtime import _normalize_run_id_or_raise

        out = _normalize_run_id_or_raise(
            "RUN-abc123def456-0000-4000-8000-000000000000"
        )
        assert out.startswith("RUN-")

    def test_normalize_accepts_orphan_and_legacy(self) -> None:
        from ract.runtime import _normalize_run_id_or_raise

        assert _normalize_run_id_or_raise("RUN-ORPHAN-abc")
        assert _normalize_run_id_or_raise("RUN-LEGACY-def")

    def test_normalize_strips_whitespace(self) -> None:
        from ract.runtime import _normalize_run_id_or_raise

        assert (
            _normalize_run_id_or_raise("  RUN-abc\n") == "RUN-abc"
        )

    def test_normalize_refuses_path_traversal(self) -> None:
        from ract.runtime import RunIdFormatError, _normalize_run_id_or_raise

        with pytest.raises(RunIdFormatError):
            _normalize_run_id_or_raise("../../../etc/passwd")

    def test_normalize_refuses_slashes(self) -> None:
        from ract.runtime import RunIdFormatError, _normalize_run_id_or_raise

        with pytest.raises(RunIdFormatError):
            _normalize_run_id_or_raise("RUN-abc/../evil")

    def test_normalize_accepts_bare_hex_no_prefix(self) -> None:
        # Many existing callers use bare hex uuid; the boundary
        # check does NOT force a RUN- prefix. It only refuses
        # path-shape and shell-metacharacter values.
        from ract.runtime import _normalize_run_id_or_raise

        assert (
            _normalize_run_id_or_raise("abc123def456")
            == "abc123def456"
        )

    def test_normalize_refuses_shell_metachars(self) -> None:
        from ract.runtime import RunIdFormatError, _normalize_run_id_or_raise

        with pytest.raises(RunIdFormatError):
            _normalize_run_id_or_raise("victim;rm -rf /")

    def test_normalize_refuses_dot_traversal(self) -> None:
        from ract.runtime import RunIdFormatError, _normalize_run_id_or_raise

        with pytest.raises(RunIdFormatError):
            _normalize_run_id_or_raise("..")

    def test_normalize_refuses_empty_after_strip(self) -> None:
        from ract.runtime import RunIdFormatError, _normalize_run_id_or_raise

        with pytest.raises(RunIdFormatError):
            _normalize_run_id_or_raise("   ")

    def test_normalize_refuses_huge_blob(self) -> None:
        from ract.runtime import RunIdFormatError, _normalize_run_id_or_raise

        with pytest.raises(RunIdFormatError):
            _normalize_run_id_or_raise("a" * 5000)

    def test_bootstrap_rejects_poisoned_env_and_orphans(
        self, monkeypatch
    ) -> None:
        """The load-bearing behavior: a poisoned parent env
        does NOT crash the subagent; it falls through to
        orphan-generate. Regression for module_04 C-6 folded via
        module_06.
        """
        from ract.runtime import bootstrap_ambient_from_env

        env = {"RACT_RUN_ID": "../../../etc/passwd"}
        bound = bootstrap_ambient_from_env(env=env, emit_events=False)
        assert bound.startswith("RUN-ORPHAN-"), (
            "poisoned RACT_RUN_ID should have been rejected and "
            "the subagent should have fallen through to orphan "
            "generation; instead it bound: %r" % bound
        )

    def test_bootstrap_accepts_valid_env(self) -> None:
        from ract.runtime import bootstrap_ambient_from_env

        env = {"RACT_RUN_ID": "RUN-abc123"}
        bound = bootstrap_ambient_from_env(env=env, emit_events=False)
        assert bound == "RUN-abc123"


# ---------------------------------------------------------------------------
# Event kind registration
# ---------------------------------------------------------------------------


class TestNewEventKindsRegistered:
    def test_env_rejected_in_legal_kinds(self) -> None:
        from ract.trace.events import LEGAL_EVENT_KINDS

        assert "runtime.run_id.env_rejected" in LEGAL_EVENT_KINDS
