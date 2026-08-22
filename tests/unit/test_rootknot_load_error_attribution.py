"""v0.5.2 hardening module_01 SP amendment -- Q4 load-path attribution.

Ox Alpha SP audit Q4 (DEFECT): the original ``verify_workspace``
catch of ``RootknotSchemaViolation`` from ``all_knots()`` returned
``file=None`` -- operator could not locate the offending sidecar.
Broader ``OSError`` / ``JSONDecodeError`` also propagated uncaught,
crashing verify instead of yielding a classified violation.

Fold: ``ProvenanceIndex.all_knots`` wraps per-row failures in
``_KnotLoadError(path=..., cause=...)``. ``verify_workspace``
routes to ``RK-V4-LABEL-MISMATCH`` / ``RK-UNKNOWN-SCHEMA`` for
schema-violation causes, and ``RK-SIDECAR-UNREADABLE`` for other
failures -- all with the offending path.
"""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import pytest

from ract.core.keys import SessionKey
from ract.core.loop import WorkspaceSnapshot
from ract.core.provenance import (
    ProvenanceIndex,
    _KnotLoadError,
    verify_workspace,
)
from ract.core.rootknot import (
    GeneratorRef,
    Rootknot,
    RootknotSchemaViolation,
    make_rootknot,
)
from ract.core.types import Digest, digest_bytes, make_plan_id, make_step_id


def _registry(assumption_digest: Digest) -> dict:
    return {
        assumption_digest: type(
            "A", (), {"state": type("S", (), {"name": "ACTIVE"})()}
        )()
    }


def test_all_knots_wraps_schema_violation_with_path() -> None:
    """``_KnotLoadError`` carries the offending path for triage."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        index = ProvenanceIndex(ws)
        # Inject a malformed v4 sidecar payload directly into the
        # SQLite index -- schema=sidecar/v4 with workspace_digest
        # null -> _knot_from_json builds Rootknot(schema_version=4,
        # workspace_digest=None) -> post_init raises.
        import json
        import sqlite3

        bad_payload = json.dumps(
            {
                "schema": "sidecar/v4",
                "plan_id": "0" * 32,
                "step_id": "0" * 32,
                "assumption_digest": "0" * 64,
                "generator": {
                    "model_name": "t",
                    "model_version": "0",
                    "session_id": "0" * 32,
                    "public_key_id": "0" * 64,
                },
                "parent_digests": [],
                "workspace_path": "bad.txt",
                "artifact_digest": "0" * 64,
                "created_at_ns": 0,
                "generator_signature": "",
                "environment_signature": "",
                "acceptance_suite_digest": "0" * 64,
                "predicate_results": [],
                "manifest_digest": "0" * 64,
                "gate_results": [],
                "schema_version": 4,
                # workspace_digest / prompt_digest / run_id absent
            }
        )
        conn = sqlite3.connect(str(index._db_path))
        try:
            conn.execute(
                "INSERT INTO rootknots (path, json) VALUES (?, ?)",
                ("bad.txt", bad_payload),
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(_KnotLoadError) as excinfo:
            index.all_knots()
        assert excinfo.value.path == "bad.txt"
        assert isinstance(excinfo.value.cause, RootknotSchemaViolation)


def test_verify_workspace_surfaces_offending_path_for_schema_violation() -> None:
    """The load-path violation carries ``file=<path>``, not ``None``."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        artifact = ws / "artifact.txt"
        artifact.write_bytes(b"payload")

        session_key = SessionKey.load_or_create(b"\x80" * 16)
        good = make_rootknot(
            session_key,
            workspace_path="artifact.txt",
            artifact_digest=digest_bytes(b"payload"),
            assumption_digest=digest_bytes(b"assume"),
        )
        index = ProvenanceIndex(ws)
        index.save(good, artifact)

        # Inject a bad row alongside the good one.
        import json
        import sqlite3

        bad_payload = json.dumps(
            {
                "schema": "sidecar/v4",
                "plan_id": "0" * 32,
                "step_id": "0" * 32,
                "assumption_digest": "0" * 64,
                "generator": {
                    "model_name": "t",
                    "model_version": "0",
                    "session_id": "0" * 32,
                    "public_key_id": "0" * 64,
                },
                "parent_digests": [],
                "workspace_path": "malformed.txt",
                "artifact_digest": "0" * 64,
                "created_at_ns": 0,
                "generator_signature": "",
                "environment_signature": "",
                "acceptance_suite_digest": "0" * 64,
                "predicate_results": [],
                "manifest_digest": "0" * 64,
                "gate_results": [],
                "schema_version": 4,
            }
        )
        conn = sqlite3.connect(str(index._db_path))
        try:
            conn.execute(
                "INSERT INTO rootknots (path, json) VALUES (?, ?)",
                ("malformed.txt", bad_payload),
            )
            conn.commit()
        finally:
            conn.close()

        result = verify_workspace(
            index,
            active_plans={good.plan_id: [good.step_id]},
            registered_assumptions=_registry(good.assumption_digest),
            generator_pubkey=lambda _g: session_key.public_key_bytes(),
        )
        assert not result.is_ok()
        violation = result.unwrap_err()
        assert violation.file == "malformed.txt", (
            "Q4 amendment: load-path failures must carry the offending "
            f"path, not file=None. Got file={violation.file!r}"
        )
        assert violation.predicate == "RK-V4-LABEL-MISMATCH"


def test_verify_workspace_routes_non_schema_load_failure_to_unreadable() -> None:
    """Corrupt JSON in the SQLite index yields ``RK-SIDECAR-UNREADABLE``."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        artifact = ws / "artifact.txt"
        artifact.write_bytes(b"payload")
        index = ProvenanceIndex(ws)

        import sqlite3

        conn = sqlite3.connect(str(index._db_path))
        try:
            conn.execute(
                "INSERT INTO rootknots (path, json) VALUES (?, ?)",
                ("corrupt.txt", "{ this is not valid json"),
            )
            conn.commit()
        finally:
            conn.close()

        session_key = SessionKey.load_or_create(b"\x81" * 16)
        result = verify_workspace(
            index,
            active_plans={},
            registered_assumptions={},
            generator_pubkey=lambda _g: session_key.public_key_bytes(),
        )
        assert not result.is_ok()
        violation = result.unwrap_err()
        assert violation.file == "corrupt.txt"
        assert violation.predicate == "RK-SIDECAR-UNREADABLE"


# RACT 0.5.2
