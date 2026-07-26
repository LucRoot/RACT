"""Workspace provenance verifier and SQLite index for Rootknots."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ract.core.rootknot import GeneratorRef, Rootknot
from ract.core.types import Digest, PlanId, Result, StepId, digest_bytes


@dataclass(frozen=True)
class ProvenanceViolation:
    """A single provenance failure."""

    file: str | None
    predicate: str
    detail: str


class ProvenanceIndex:
    """SQLite-backed index of Rootknots for a workspace."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root)
        self._db_path = self.workspace_root / ".rack" / "rootknots.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS rootknots ("
                "path TEXT PRIMARY KEY,"
                "json TEXT NOT NULL"
                ")"
            )
            conn.commit()
        finally:
            conn.close()

    def save(self, knot: Rootknot, artifact_path: Path) -> None:
        """Persist ``knot`` for ``artifact_path`` in SQLite and as a sidecar."""
        rel_path = self._rel(artifact_path)
        payload = _knot_to_json(knot)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO rootknots (path, json) VALUES (?, ?)",
                (rel_path, payload),
            )
            conn.commit()
        finally:
            conn.close()
        sidecar = artifact_path.parent / f".{artifact_path.name}.rootknot.json"
        sidecar.write_text(payload, encoding="utf-8")
        # module_05: emit at the write site so the event log names every
        # signed artifact the run produced. Verification emits are made
        # by ``verify_workspace`` below.
        try:
            from ract.trace.sink import emit as _emit_event

            _emit_event(
                "rootknot.created",
                {
                    "workspace_path": knot.workspace_path,
                    "plan_id": knot.plan_id.hex(),
                    "step_id_ref": knot.step_id.hex(),
                    "artifact_digest": knot.artifact_digest.hex(),
                    "assumption_digest": knot.assumption_digest.hex(),
                },
            )
        except Exception:  # noqa: BLE001
            pass

    def load(self, artifact_path: Path) -> Rootknot | None:
        """Load the Rootknot for ``artifact_path`` if one exists."""
        rel_path = self._rel(artifact_path)
        conn = sqlite3.connect(str(self._db_path))
        try:
            row = conn.execute(
                "SELECT json FROM rootknots WHERE path = ?", (rel_path,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return _knot_from_json(row[0])

    def all_knots(self) -> dict[str, Rootknot]:
        """Return a mapping from relative artifact path to Rootknot."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute("SELECT path, json FROM rootknots").fetchall()
        finally:
            conn.close()
        return {path: _knot_from_json(payload) for path, payload in rows}

    def _rel(self, artifact_path: Path) -> str:
        try:
            return str(Path(artifact_path).relative_to(self.workspace_root))
        except ValueError:
            return str(artifact_path)


def _knot_to_json(knot: Rootknot) -> str:
    data = {
        "plan_id": knot.plan_id.hex(),
        "step_id": knot.step_id.hex(),
        "assumption_digest": knot.assumption_digest.hex(),
        "generator": {
            "model_name": knot.generator.model_name,
            "model_version": knot.generator.model_version,
            "session_id": knot.generator.session_id.hex(),
            "public_key_id": knot.generator.public_key_id.hex(),
        },
        "parent_digests": [d.hex() for d in knot.parent_digests],
        "workspace_path": knot.workspace_path,
        "artifact_digest": knot.artifact_digest.hex(),
        "created_at_ns": knot.created_at_ns,
        "signature": knot.signature.hex(),
    }
    return json.dumps(data, sort_keys=True, indent=2)


def _knot_from_json(payload: str) -> Rootknot:
    data = json.loads(payload)
    generator = data["generator"]
    return Rootknot(
        plan_id=PlanId(bytes.fromhex(data["plan_id"])),
        step_id=StepId(bytes.fromhex(data["step_id"])),
        assumption_digest=Digest(bytes.fromhex(data["assumption_digest"])),
        generator=GeneratorRef(
            model_name=generator["model_name"],
            model_version=generator["model_version"],
            session_id=bytes.fromhex(generator["session_id"]),
            public_key_id=Digest(bytes.fromhex(generator["public_key_id"])),
        ),
        parent_digests=tuple(Digest(bytes.fromhex(d)) for d in data["parent_digests"]),
        workspace_path=data["workspace_path"],
        artifact_digest=Digest(bytes.fromhex(data["artifact_digest"])),
        created_at_ns=data["created_at_ns"],
        signature=bytes.fromhex(data["signature"]),
    )


def verify_workspace(
    index: ProvenanceIndex,
    active_plans: dict[PlanId, list[StepId]],
    registered_assumptions: dict[Digest, Any],
    generator_pubkey: Callable[[Any], bytes | None],
) -> Result[None, ProvenanceViolation]:
    """Check RK-1 and RK-2 over every indexed artifact.

    Returns the first violation encountered, or ``Result.ok(None)``.
    """
    knots = index.all_knots()
    canonical_cache: dict[Digest, bytes] = {}

    def canonical_digest(knot: Rootknot) -> Digest:
        return digest_bytes(knot.canonical_bytes())

    def resolve_parent(parent_digest: Digest, seen: set[Digest]) -> bool:
        if parent_digest in seen:
            return False
        seen.add(parent_digest)
        for candidate in knots.values():
            if canonical_digest(candidate) == parent_digest:
                return _check_knot(candidate, seen.copy())
        return False

    def _check_knot(knot: Rootknot, seen: set[Digest]) -> bool:
        canonical = knot.canonical_bytes()
        canonical_cache[canonical_digest(knot)] = canonical

        # RK-1.1
        artifact_path = index.workspace_root / knot.workspace_path
        if not artifact_path.exists():
            return False
        actual_digest = digest_bytes(artifact_path.read_bytes())
        if actual_digest != knot.artifact_digest:
            return False

        # RK-1.2
        pubkey = generator_pubkey(knot.generator)
        if pubkey is None or not knot.verify(pubkey):
            return False

        # RK-1.3
        if knot.plan_id not in active_plans:
            return False

        # RK-1.4
        if knot.step_id not in active_plans[knot.plan_id]:
            return False

        # RK-1.5
        if knot.assumption_digest not in registered_assumptions:
            return False

        # RK-1.6
        for parent in knot.parent_digests:
            if not resolve_parent(parent, seen.copy()):
                return False

        # RK-2
        assumption = registered_assumptions.get(knot.assumption_digest)
        if assumption is not None:
            state = getattr(assumption, "state", None)
            if state is not None and state.name == "VIOLATED":
                return False

        return True

    for rel_path, knot in knots.items():
        if not _check_knot(knot, set()):
            violation = _classify_violation(
                index, knot, active_plans, registered_assumptions, generator_pubkey
            )
            return Result.err(violation)
        # module_05: emit per-verified knot so the reporter's rootknot
        # counts derive from the event log.
        try:
            from ract.trace.sink import emit as _emit_event

            _emit_event(
                "rootknot.verified",
                {
                    "workspace_path": rel_path,
                    "artifact_digest": knot.artifact_digest.hex(),
                },
            )
        except Exception:  # noqa: BLE001
            pass

    return Result.ok(None)


def _classify_violation(
    index: ProvenanceIndex,
    knot: Rootknot,
    active_plans: dict[PlanId, list[StepId]],
    registered_assumptions: dict[Digest, Any],
    generator_pubkey: Callable[[Any], bytes | None],
) -> ProvenanceViolation:
    """Return the most specific predicate that fails for ``knot``."""
    artifact_path = index.workspace_root / knot.workspace_path
    if not artifact_path.exists():
        return ProvenanceViolation(
            file=knot.workspace_path, predicate="RK-1.1", detail="artifact missing"
        )
    actual_digest = digest_bytes(artifact_path.read_bytes())
    if actual_digest != knot.artifact_digest:
        return ProvenanceViolation(
            file=knot.workspace_path,
            predicate="RK-1.1",
            detail="artifact digest mismatch",
        )

    pubkey = generator_pubkey(knot.generator)
    if pubkey is None:
        return ProvenanceViolation(
            file=knot.workspace_path,
            predicate="RK-1.2",
            detail="no public key for generator",
        )
    if not knot.verify(pubkey):
        return ProvenanceViolation(
            file=knot.workspace_path,
            predicate="RK-1.2",
            detail="signature does not verify",
        )

    if knot.plan_id not in active_plans:
        return ProvenanceViolation(
            file=knot.workspace_path,
            predicate="RK-1.3",
            detail="plan_id not active",
        )

    if knot.step_id not in active_plans[knot.plan_id]:
        return ProvenanceViolation(
            file=knot.workspace_path,
            predicate="RK-1.4",
            detail="step_id not in plan",
        )

    if knot.assumption_digest not in registered_assumptions:
        return ProvenanceViolation(
            file=knot.workspace_path,
            predicate="RK-1.5",
            detail="assumption not registered",
        )

    assumption = registered_assumptions.get(knot.assumption_digest)
    if assumption is not None:
        state = getattr(assumption, "state", None)
        if state is not None and state.name == "VIOLATED":
            return ProvenanceViolation(
                file=knot.workspace_path,
                predicate="RK-2",
                detail="underlying assumption violated",
            )

    return ProvenanceViolation(
        file=knot.workspace_path,
        predicate="RK-1.6",
        detail="parent digest does not resolve",
    )


# RACT 0.2.0
