"""Workspace provenance verifier and SQLite index for Rootknots.

v0.4 (module_06) lands **Invariant RK-3 (Environmental Attestation)**
alongside the v0.3 RK-1 and RK-2 checks: every v2 sidecar must carry a
valid environment signature (by the sandbox key), an acceptance-suite
digest that is currently registered, a manifest digest that is currently
registered, and non-empty predicate results. v1 sidecars (from v0.3
workspaces) still verify under RK-1 and RK-2 only; RK-3 is skipped for
them with a ``DeprecationWarning`` unless the caller passes
``strict=True``, in which case RK-3 fails and the loop halts with T3.

Sidecar schema dispatch — SUBSTRATE §7.2 and module_06 lateral chain
branches A + C. ``sidecar/v1`` is the v0.3 shape (single ``signature``
field, no schema tag). ``sidecar/v2`` embeds the raw sandbox and
generator pubkeys so offline verification is possible from the sidecar
alone plus stdlib crypto (subsumes the v0.3.1-hardening flagged item on
self-contained sidecars).

Reference sources:

- SUBSTRATE spec §7 (Rootknot preserved; trust direction inverted).
- REBUILD spec §3 (Rootknot Made Real) — v0.3 baseline.
- RFC 8032 for ed25519.
- ``cryptography`` public docs: ``https://cryptography.io/``.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

from ract.core.rootknot import (
    _KNOWN_SCHEMA_VERSIONS,
    GateResult,
    GeneratorRef,
    Rootknot,
)
from ract.core.types import Digest, PlanId, Result, StepId, digest_bytes


# ---------------------------------------------------------------------------
# Violation shape
# ---------------------------------------------------------------------------


class _KnotLoadError(Exception):
    """Internal: a single row in the SQLite index failed reconstruction.

    v0.5.2 module_01 SP amendment (Ox Alpha Q4 -- per-file
    attribution for load-path failures). Carried up from
    :meth:`ProvenanceIndex.all_knots` to :func:`verify_workspace`
    where it is converted to a :class:`ProvenanceViolation` with the
    offending path -- the original try/except lost that triage
    information by refusing with ``file=None``.
    """

    def __init__(self, *, path: str, cause: BaseException) -> None:
        super().__init__(f"knot load failed for {path}: {cause}")
        self.path = path
        self.cause = cause


class RootknotUnknownSidecarFormat(Exception):
    """Sidecar payload declares a ``schema`` this reader does not know.

    v0.5.2 hardening module_06 (module_01 Q3 fold; Ox Alpha co-build
    Q1 MUST-FOLD verdict). Prior to this the reader accepted a
    ``sidecar/v9`` payload by silently downgrading to the v1 shape;
    the module_01 verifier-side ``_check_rk3`` known-versions
    allowlist would then refuse it, but only AFTER the reader had
    already committed to a wrong shape for the fields. Pairing this
    read-side refusal with the write-side ``write_sidecar_header``
    primitive means UNKNOWN sidecar formats fail loudly at ingest,
    with the offending literal in the message.

    Callers that want to soft-accept unknown schemas (a rolling
    upgrade window, deliberate operator override) can catch this
    exception at the boundary and rebuild via a compatibility path.
    Absent-``schema`` legacy v0.3 v1 payloads continue to load
    unchanged.
    """


@dataclass(frozen=True)
class ProvenanceViolation:
    """A single provenance failure.

    ``predicate`` names the invariant sub-clause that failed (e.g.
    ``"RK-1.1"``, ``"RK-2"``, ``"RK-3.1"``). Module_06 adds the RK-3.*
    sub-clauses; RK-1 and RK-2 are unchanged from v0.3.
    """

    file: str | None
    predicate: str
    detail: str


# ---------------------------------------------------------------------------
# ProvenanceIndex
# ---------------------------------------------------------------------------


class ProvenanceIndex:
    """SQLite-backed index of Rootknots for a workspace."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root)
        # v0.5.1 wiring module_10: workspace state directory unified
        # on ``.ract/`` (Lens A C2 closure). The migration shim in
        # ``ract.workspace_state`` renames any pre-module_10 ``.rack/``
        # tree in place on CLI dispatch, so existing rootknots.db
        # remains at the expected relative path after migration.
        from ract.workspace_state import WORKSPACE_STATE_DIR_NAME

        self._db_path = self.workspace_root / WORKSPACE_STATE_DIR_NAME / "rootknots.db"
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

    def save(
        self,
        knot: Rootknot,
        artifact_path: Path,
        *,
        sandbox_pubkey: bytes | None = None,
        alm_pubkey: bytes | None = None,
    ) -> None:
        """Persist ``knot`` for ``artifact_path`` in SQLite and as a sidecar.

        ``sandbox_pubkey`` is the raw 32-byte ed25519 public key that
        signed the ``environment_signature``. Required for v2 knots so
        the sidecar is self-contained; ignored for v1 knots.
        ``alm_pubkey`` is the raw 32-byte ed25519 public key that signed
        the ``antilazy_signature``. Required for v3 knots so a v3 sidecar
        supports offline verify from the sidecar alone (ALM §5).
        """
        rel_path = self._rel(artifact_path)
        payload = _knot_to_json(
            knot, sandbox_pubkey=sandbox_pubkey, alm_pubkey=alm_pubkey
        )
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
                    "schema_version": knot.schema_version,
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

    def load_sidecar_pubkeys(
        self, artifact_path: Path
    ) -> tuple[bytes | None, bytes | None]:
        """Return (sandbox_pubkey, generator_pubkey) embedded in the v2/v3 sidecar.

        Both are ``None`` for v1 sidecars — those workspaces predate the
        embedded-pubkey extension. Callers use these when running RK-3
        without a live ``.ract/sandbox/`` archive.
        """
        sidecar = artifact_path.parent / f".{artifact_path.name}.rootknot.json"
        if not sidecar.is_file():
            return None, None
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None, None
        sk = data.get("sandbox_pubkey_b64")
        gk = data.get("generator_pubkey_b64")
        sk_bytes = base64.b64decode(sk) if sk else None
        gk_bytes = base64.b64decode(gk) if gk else None
        return sk_bytes, gk_bytes

    def load_sidecar_alm_pubkey(self, artifact_path: Path) -> bytes | None:
        """Return the ALM verifier pubkey embedded in a v3 sidecar, or ``None``.

        Returns ``None`` for v1 and v2 sidecars — those workspaces
        predate the anti-lazy attestation. Trust-by-declaration warning:
        the sidecar carries the pubkey the sidecar itself was signed
        under, so a forged sidecar controls the pubkey. AL-1 verification
        MUST cross-check this against an out-of-sidecar source (the
        workspace-level ``keys.jsonl`` written by the ALM verifier
        process, or an operator-supplied resolver). See ADR-0023 and the
        module_05 Second Pass results section for the chain-of-custody
        design.
        """
        sidecar = artifact_path.parent / f".{artifact_path.name}.rootknot.json"
        if not sidecar.is_file():
            return None
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        ak = data.get("alm_pubkey_b64")
        if not ak:
            return None
        try:
            return base64.b64decode(ak)
        except Exception:  # noqa: BLE001
            return None

    def all_knots(self) -> dict[str, Rootknot]:
        """Return a mapping from relative artifact path to Rootknot.

        v0.5.2 module_01 SP amendment (Ox Alpha Q4): per-row
        construction failures are wrapped in :class:`_KnotLoadError`
        carrying the offending ``path``. ``verify_workspace`` catches
        it and emits a :class:`ProvenanceViolation` with the offending
        path -- restoring the triage information the earlier
        ``file=None`` refusal lost.
        """
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute("SELECT path, json FROM rootknots").fetchall()
        finally:
            conn.close()
        knots: dict[str, Rootknot] = {}
        for path, payload in rows:
            try:
                knots[path] = _knot_from_json(payload)
            except Exception as exc:
                raise _KnotLoadError(path=path, cause=exc) from exc
        return knots

    def _rel(self, artifact_path: Path) -> str:
        try:
            return str(Path(artifact_path).relative_to(self.workspace_root))
        except ValueError:
            return str(artifact_path)


# ---------------------------------------------------------------------------
# Sidecar serialisation (schema-dispatched)
# ---------------------------------------------------------------------------


# v0.5.1 wiring module_02 SP Q8 amendment: adjacent Lens D findings
# tracked as TODO markers so a future grep surfaces them:
#   TODO(D6, v0.5.2): route sidecar writer through ``dumps_jcs`` --
#     the sidecar bytes are NOT signed, but a JCS pass closes the
#     non-BMP escape-drift risk between Python minor versions.
#   TODO(D11, v0.5.2): narrow ``except Exception`` in
#     ``executor/steps.py::_record_provenance`` and emit a structured
#     ``rootknot.provenance_recording_failed`` trace event with the
#     narrowed exception class + full_path context.


def _knot_to_json(
    knot: Rootknot,
    *,
    sandbox_pubkey: bytes | None = None,
    alm_pubkey: bytes | None = None,
) -> str:
    """Return the on-disk JSON form of ``knot``.

    v1 (``schema_version == 1``): the v0.3 shape, with the single
    ``signature`` field. v2 (``schema_version == 2``): the v0.4
    substrate shape, with ``schema: sidecar/v2`` plus the renamed
    ``generator_signature`` and the environmental-attestation fields.
    v3 (``schema_version == 3``): the v0.4 ALM shape, with
    ``schema: sidecar/v3`` plus ``antilazy_signature``, ``gate_results``,
    ``reversal_taint``, and the raw ALM verifier pubkey (base64) so
    offline verification of AL-1 is possible from the sidecar alone
    (subject to the chain-of-custody caveat documented in
    ``load_sidecar_alm_pubkey``).

    v4 (``schema_version == 4``, v0.5.1 wiring module_02): extends v3
    with ``workspace_digest``, ``prompt_digest``, ``run_id``, and (when
    set) ``retrieval_attestation``. These four fields ride inside the
    v4 Rootknot's signed canonical bytes; dropping them on the sidecar
    round-trip would rebuild a v3-shaped payload and every ed25519
    verify would fail. Lens D D1.
    """
    if knot.schema_version >= 4:
        data: dict[str, Any] = {
            "schema": "sidecar/v4",
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
            "generator_signature": knot.generator_signature.hex(),
            "environment_signature": knot.environment_signature.hex(),
            "acceptance_suite_digest": knot.acceptance_suite_digest.hex(),
            "predicate_results": [d.hex() for d in knot.predicate_results],
            "manifest_digest": knot.manifest_digest.hex(),
            "antilazy_signature": knot.antilazy_signature.hex(),
            "gate_results": [gr.canonical_dict() for gr in knot.gate_results],
            "reversal_taint": knot.reversal_taint,
            "schema_version": knot.schema_version,
            # v4 canonical-bytes additions -- these MUST be preserved on
            # round-trip so verify() recomputes the same canonical bytes
            # the sender signed. Emit them as ``None`` when unset so
            # the reader can distinguish "absent" from "empty".
            "workspace_digest": (
                knot.workspace_digest.hex()
                if knot.workspace_digest is not None
                else None
            ),
            "prompt_digest": (
                knot.prompt_digest.hex() if knot.prompt_digest is not None else None
            ),
            "run_id": knot.run_id or "",
        }
        if knot.retrieval_attestation is not None:
            data["retrieval_attestation"] = knot.retrieval_attestation.hex()
        if sandbox_pubkey is not None:
            data["sandbox_pubkey_b64"] = base64.b64encode(sandbox_pubkey).decode(
                "ascii"
            )
        if alm_pubkey is not None:
            data["alm_pubkey_b64"] = base64.b64encode(alm_pubkey).decode("ascii")
        return json.dumps(data, sort_keys=True, indent=2)

    if knot.schema_version >= 3:
        data: dict[str, Any] = {
            "schema": "sidecar/v3",
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
            "generator_signature": knot.generator_signature.hex(),
            "environment_signature": knot.environment_signature.hex(),
            "acceptance_suite_digest": knot.acceptance_suite_digest.hex(),
            "predicate_results": [d.hex() for d in knot.predicate_results],
            "manifest_digest": knot.manifest_digest.hex(),
            "antilazy_signature": knot.antilazy_signature.hex(),
            "gate_results": [gr.canonical_dict() for gr in knot.gate_results],
            "reversal_taint": knot.reversal_taint,
            "schema_version": knot.schema_version,
        }
        if sandbox_pubkey is not None:
            data["sandbox_pubkey_b64"] = base64.b64encode(sandbox_pubkey).decode(
                "ascii"
            )
        if alm_pubkey is not None:
            data["alm_pubkey_b64"] = base64.b64encode(alm_pubkey).decode("ascii")
        return json.dumps(data, sort_keys=True, indent=2)

    if knot.schema_version >= 2:
        # Recover the generator pubkey from the digest when we don't have
        # the raw bytes — we don't in the generic case, so callers who
        # want offline verify must supply ``sandbox_pubkey`` and (at the
        # save site) the raw generator pubkey via the trusted key store.
        # Here we embed whatever we can; the generator pubkey is derived
        # by the audit path from the local key store when absent.
        data = {
            "schema": "sidecar/v2",
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
            "generator_signature": knot.generator_signature.hex(),
            "environment_signature": knot.environment_signature.hex(),
            "acceptance_suite_digest": knot.acceptance_suite_digest.hex(),
            "predicate_results": [d.hex() for d in knot.predicate_results],
            "manifest_digest": knot.manifest_digest.hex(),
            "schema_version": knot.schema_version,
        }
        if sandbox_pubkey is not None:
            data["sandbox_pubkey_b64"] = base64.b64encode(sandbox_pubkey).decode(
                "ascii"
            )
        # The generator pubkey isn't stored on the Rootknot value; the audit
        # path resolves it from the local key store via ``public_key_id``.
        # This field is optional — save sites that want offline verify can
        # write it in a follow-up patch to the sidecar.
        return json.dumps(data, sort_keys=True, indent=2)

    # v1 shape (unchanged from v0.3).
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
        "signature": knot.generator_signature.hex(),
    }
    return json.dumps(data, sort_keys=True, indent=2)


def _knot_from_json(payload: str) -> Rootknot:
    """Rebuild a Rootknot from an on-disk sidecar payload.

    Dispatches on the ``schema`` field: ``"sidecar/v4"`` builds a v4
    knot; ``"sidecar/v3"`` builds a v3 knot; ``"sidecar/v2"`` builds a v2
    knot; anything else (including the absent-field v0.3 shape) builds a
    v1 knot. v0.5.1 wiring module_02 (Lens D D1) adds the v4 branch --
    the previous reader silently dropped ``workspace_digest``,
    ``prompt_digest``, ``run_id`` (and ``retrieval_attestation`` on v4
    sidecars) and every v4 verify() failed on the shorter canonical
    bytes.
    """
    data = json.loads(payload)
    generator = data["generator"]
    schema = data.get("schema")
    if schema == "sidecar/v4":
        gate_results_raw = data.get("gate_results", [])
        gate_results: list[GateResult] = []
        for gr in gate_results_raw:
            gate_results.append(
                GateResult(
                    gate_id=str(gr["gate_id"]),
                    passed=bool(gr["passed"]),
                    evidence_digest=Digest(bytes.fromhex(gr["evidence_digest"])),
                    handshake_id=gr.get("handshake_id"),
                )
            )
        workspace_digest_hex = data.get("workspace_digest")
        prompt_digest_hex = data.get("prompt_digest")
        retrieval_hex = data.get("retrieval_attestation")
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
            parent_digests=tuple(
                Digest(bytes.fromhex(d)) for d in data["parent_digests"]
            ),
            workspace_path=data["workspace_path"],
            artifact_digest=Digest(bytes.fromhex(data["artifact_digest"])),
            created_at_ns=data["created_at_ns"],
            generator_signature=bytes.fromhex(data["generator_signature"]),
            environment_signature=bytes.fromhex(data["environment_signature"]),
            acceptance_suite_digest=Digest(
                bytes.fromhex(data["acceptance_suite_digest"])
            ),
            predicate_results=tuple(
                Digest(bytes.fromhex(d)) for d in data.get("predicate_results", [])
            ),
            manifest_digest=Digest(bytes.fromhex(data["manifest_digest"])),
            antilazy_signature=bytes.fromhex(data.get("antilazy_signature", "")),
            gate_results=tuple(gate_results),
            reversal_taint=str(data.get("reversal_taint", "clean")),  # type: ignore[arg-type]
            schema_version=int(data.get("schema_version", 4)),
            retrieval_attestation=(
                Digest(bytes.fromhex(retrieval_hex))
                if retrieval_hex is not None
                else None
            ),
            workspace_digest=(
                Digest(bytes.fromhex(workspace_digest_hex))
                if workspace_digest_hex is not None
                else None
            ),
            prompt_digest=(
                Digest(bytes.fromhex(prompt_digest_hex))
                if prompt_digest_hex is not None
                else None
            ),
            run_id=str(data.get("run_id", "") or ""),
        )
    if schema == "sidecar/v3":
        gate_results_raw = data.get("gate_results", [])
        gate_results: list[GateResult] = []
        for gr in gate_results_raw:
            gate_results.append(
                GateResult(
                    gate_id=str(gr["gate_id"]),
                    passed=bool(gr["passed"]),
                    evidence_digest=Digest(bytes.fromhex(gr["evidence_digest"])),
                    handshake_id=gr.get("handshake_id"),
                )
            )
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
            parent_digests=tuple(
                Digest(bytes.fromhex(d)) for d in data["parent_digests"]
            ),
            workspace_path=data["workspace_path"],
            artifact_digest=Digest(bytes.fromhex(data["artifact_digest"])),
            created_at_ns=data["created_at_ns"],
            generator_signature=bytes.fromhex(data["generator_signature"]),
            environment_signature=bytes.fromhex(data["environment_signature"]),
            acceptance_suite_digest=Digest(
                bytes.fromhex(data["acceptance_suite_digest"])
            ),
            predicate_results=tuple(
                Digest(bytes.fromhex(d)) for d in data.get("predicate_results", [])
            ),
            manifest_digest=Digest(bytes.fromhex(data["manifest_digest"])),
            antilazy_signature=bytes.fromhex(data.get("antilazy_signature", "")),
            gate_results=tuple(gate_results),
            reversal_taint=str(data.get("reversal_taint", "clean")),  # type: ignore[arg-type]
            schema_version=int(data.get("schema_version", 3)),
        )
    if schema == "sidecar/v2":
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
            parent_digests=tuple(
                Digest(bytes.fromhex(d)) for d in data["parent_digests"]
            ),
            workspace_path=data["workspace_path"],
            artifact_digest=Digest(bytes.fromhex(data["artifact_digest"])),
            created_at_ns=data["created_at_ns"],
            generator_signature=bytes.fromhex(data["generator_signature"]),
            environment_signature=bytes.fromhex(data["environment_signature"]),
            acceptance_suite_digest=Digest(
                bytes.fromhex(data["acceptance_suite_digest"])
            ),
            predicate_results=tuple(
                Digest(bytes.fromhex(d)) for d in data.get("predicate_results", [])
            ),
            manifest_digest=Digest(bytes.fromhex(data["manifest_digest"])),
            schema_version=int(data.get("schema_version", 2)),
        )
    # v0.5.2 module_06 (module_01 Q3 fold, Ox Alpha co-build Q1
    # MUST-FOLD verdict): explicit refusal of unknown sidecar
    # schemas. Module_04's ``write_sidecar_header`` established a
    # second schema-versioned ingestion boundary; leaving THIS
    # reader silently downgrading unknown ``schema`` strings to the
    # v1 shape meant the module_01 known-versions allowlist policy
    # was enforced at one boundary and not its pair. A hostile
    # ``sidecar/v9`` payload previously fell through to v1
    # semantics; now it raises :class:`RootknotUnknownSidecarFormat`
    # with the offending literal. The absent-field v0.3 shape is
    # still accepted (schema is None) -- only NAMED-but-UNKNOWN
    # values refuse.
    if schema is not None and schema not in (
        "sidecar/v2",
        "sidecar/v3",
        "sidecar/v4",
    ):
        raise RootknotUnknownSidecarFormat(
            f"unknown sidecar schema {schema!r}; known values are "
            "'sidecar/v2', 'sidecar/v3', 'sidecar/v4' (or absent for "
            "the legacy v0.3 v1 shape)"
        )
    # v1 (v0.3) shape.
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
        generator_signature=bytes.fromhex(data["signature"]),
        schema_version=1,
    )


# ---------------------------------------------------------------------------
# verify_workspace — RK-1 + RK-2 + RK-3
# ---------------------------------------------------------------------------


def verify_workspace(
    index: ProvenanceIndex,
    active_plans: dict[PlanId, list[StepId]],
    registered_assumptions: dict[Digest, Any],
    generator_pubkey: Callable[[Any], bytes | None],
    *,
    sandbox_pubkey: Callable[[Rootknot], bytes | None] | None = None,
    registered_suites: set[Digest] | None = None,
    registered_manifests: set[Digest] | None = None,
    alm_pubkey: Callable[[Rootknot], bytes | None] | None = None,
    approved_gate_exceptions: set[str] | None = None,
    accepted_partial_taint_runs: set[bytes] | None = None,
    strict: bool = False,
    min_acceptable_schema_version: int | None = None,
) -> Result[None, ProvenanceViolation]:
    """Check RK-1, RK-2, RK-3 (v2 sidecars), and AL-1 (v3 sidecars).

    Returns the first violation encountered, or ``Result.ok(None)``.

    RK-3 requires ``sandbox_pubkey`` + ``registered_suites`` +
    ``registered_manifests``. When they are absent, RK-3 is skipped with a
    ``DeprecationWarning`` for v1 knots; for v2 knots it also skips (with a
    ``UserWarning``) unless ``strict=True``, in which case the missing
    context is itself a violation. ``strict=True`` also refuses v1 and v2
    sidecars outright (module_05 raises the ``--strict`` bar to "AL-1
    required").

    AL-1 (v3 sidecars, ALM module_05) requires ``alm_pubkey``. The three
    sub-clauses:

    - AL-1.1: ``knot.antilazy_signature`` verifies under the ALM pubkey
      the resolver returns.
    - AL-1.2: every ``GateResult`` in ``knot.gate_results`` either has
      ``passed=True`` or carries a ``handshake_id`` that appears in
      ``approved_gate_exceptions`` (the operator's approved-handshake
      ids read from ``HandshakeRegistry``).
    - AL-1.3: ``knot.reversal_taint == "clean"`` OR the run identified
      by ``knot.plan_id`` appears in ``accepted_partial_taint_runs``.

    v0.5.2 hardening module_01 additions (deep-audit A closure):

    - **Known-versions allowlist** -- any knot whose
      ``schema_version`` is not in
      :data:`ract.core.rootknot._KNOWN_SCHEMA_VERSIONS` fails with
      ``RK-UNKNOWN-SCHEMA`` (Ox Alpha M-2 -- previously a v9 knot fell
      through the ``schema_version < 3`` gate under v3 semantics).
    - **v4-label-implies-v4-fields** -- a knot labelled
      ``schema_version == 4`` whose ``workspace_digest``,
      ``prompt_digest`` or ``run_id`` are empty fails with
      ``RK-V4-LABEL-MISMATCH`` (F-1/F-2/F-5 -- previously a
      SessionKey-holder could mint a v4-labelled attestation binding
      nothing because ``canonical_bytes()`` emitted the fields only
      when truthy and the verifier never checked). Ox Alpha co-build
      (2026-08-22) confirmed this verifier-side check must stay
      authoritative because deserialisation paths (``copy``/pickle)
      bypass ``Rootknot.__post_init__``.
    - **min_acceptable_schema_version** -- when set, any knot whose
      ``schema_version`` is below the floor fails with
      ``RK-DOWNGRADE-REFUSED`` (Ox Alpha M-1 -- previously the
      verifier had no policy floor, so a v4 knot relabelled as v1 and
      resigned by the same key-holder verified as a weaker
      attestation). Default ``None`` preserves the backward-compat
      contract that v0.5.0 v1/v3 payloads keep verifying; operator
      sets to 4 for strict deployments (see
      ``docs/PROVENANCE.md`` v0.5.2 additions).
    """
    # v0.5.2 module_01: ``Rootknot.__post_init__`` now enforces
    # v4-label-implies-v4-fields + known-versions allowlist at
    # construction time. That means loading a malformed sidecar (e.g.
    # a historic v4-labelled attestation with absent fields) raises
    # :class:`ract.core.rootknot.RootknotSchemaViolation` before we
    # ever get here. Convert that into a first-class
    # :class:`ProvenanceViolation` result so the operator sees the
    # sharp diagnostic instead of an unhandled exception. Ox Alpha
    # co-build (2026-08-22) Fork 3 gotcha #2: the verifier-side
    # ``_check_rk3`` check is still authoritative because
    # ``copy``/pickle restore paths bypass ``__post_init__`` -- this
    # try/except is the belt-and-braces load-path surface.
    # SP amendment (Ox Alpha Q4): ``all_knots`` now wraps per-row
    # failures in :class:`_KnotLoadError` carrying the offending
    # relative path. Restores per-file attribution the original
    # ``file=None`` refusal lost. Broader ``OSError`` / JSON /
    # unicode failures also route to a classified violation with the
    # offending path rather than propagating as unhandled traceback.
    from ract.core.rootknot import RootknotSchemaViolation

    try:
        knots = index.all_knots()
    except _KnotLoadError as exc:
        cause = exc.cause
        if isinstance(cause, RootknotSchemaViolation):
            return Result.err(
                ProvenanceViolation(
                    file=exc.path,
                    predicate=(
                        "RK-V4-LABEL-MISMATCH"
                        if cause.missing_fields
                        else "RK-UNKNOWN-SCHEMA"
                    ),
                    detail=(
                        f"sidecar refused during load: {cause.reason} "
                        "(construction-time invariant enforced by "
                        "Rootknot.__post_init__)"
                    ),
                )
            )
        return Result.err(
            ProvenanceViolation(
                file=exc.path,
                predicate="RK-SIDECAR-UNREADABLE",
                detail=(
                    f"sidecar load failed: {type(cause).__name__}: "
                    f"{cause}. Repair or remove the sidecar to unblock "
                    "verification."
                ),
            )
        )
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

        # RK-3 (v0.4 module_06)
        if not _check_rk3(knot):
            return False
        # AL-1 (v0.4 ALM module_05)
        return _check_al1(knot)

    def _check_rk3(knot: Rootknot) -> bool:
        # v0.5.2 module_01 gate #1: known-versions allowlist. Reject
        # unknown majors BEFORE any semantic dispatch (deep-audit A
        # M-2). Historically ``if knot.schema_version < 3`` funnelled
        # unknown v9 through the v3 branch under drifted semantics;
        # the allowlist closes that door.
        if knot.schema_version not in _KNOWN_SCHEMA_VERSIONS:
            return False
        # v0.5.2 module_01 gate #2: operator-configurable minimum
        # (Ox Alpha M-1). ``None`` = no floor (backward-compat with
        # v0.5.0 dispatch that accepted v1/v2/v3 by design).
        if (
            min_acceptable_schema_version is not None
            and knot.schema_version < min_acceptable_schema_version
        ):
            return False
        # v0.5.2 module_01 gate #3: v4-label-implies-v4-fields
        # (deep-audit A F-1/F-2/F-5). This branch is the
        # verifier-side authoritative check per Ox Alpha co-build --
        # ``Rootknot.__post_init__`` enforces the same invariant at
        # construction, but ``copy``/pickle restore paths bypass
        # ``__init__``, so the verifier is what closes the attack.
        if knot.schema_version == 4:
            # v0.5.2 module_01 SP amendment (Ox Alpha + cross-family Q5):
            # zero-digest sentinel is truthy bytes; explicit sentinel
            # check plugs the bypass.
            from ract.core.rootknot import _ZERO_DIGEST as _ZD

            if not knot.workspace_digest or knot.workspace_digest == _ZD:
                return False
            if not knot.prompt_digest or knot.prompt_digest == _ZD:
                return False
            if not knot.run_id:
                return False
        # v1 sidecars: RK-3 skips (per lateral chain branch A). ``strict``
        # refuses them (per module_06 step 5). Under module_05's stricter
        # bar ``strict`` also refuses v2 sidecars — see ``_check_al1``.
        if knot.schema_version < 2:
            if strict:
                return False
            warnings.warn(
                f"RK-3 skipped for v1 sidecar {knot.workspace_path!r}: "
                "sidecar predates environmental attestation. Re-sign under "
                "v0.4 to lift the bar.",
                DeprecationWarning,
                stacklevel=3,
            )
            return True

        # v2 sidecar: run RK-3.
        # RK-3.1 environment signature verifies under the sandbox pubkey.
        sbx_pk: bytes | None = None
        if sandbox_pubkey is not None:
            sbx_pk = sandbox_pubkey(knot)
        if sbx_pk is None:
            if strict:
                return False
            warnings.warn(
                f"RK-3.1 skipped for v2 sidecar {knot.workspace_path!r}: "
                "no sandbox pubkey resolvable. Pass ``sandbox_pubkey=…`` "
                "to verify_workspace to lift the skip.",
                UserWarning,
                stacklevel=3,
            )
        else:
            if not knot.verify_environment(sbx_pk):
                return False

        # RK-3.2 acceptance suite digest registered.
        if registered_suites is not None:
            if knot.acceptance_suite_digest not in registered_suites:
                return False

        # RK-3.3 required-predicate-results present. We can only check the
        # tuple is non-empty from digests alone; a tighter check requires
        # an out-of-band predicate-result registry.
        if not knot.predicate_results:
            return False

        # RK-3.4 manifest digest registered.
        if registered_manifests is not None:
            if knot.manifest_digest not in registered_manifests:
                return False

        return True

    def _check_al1(knot: Rootknot) -> bool:
        # v1 and v2 sidecars: AL-1 skips (per module_05 lateral chain
        # branch A). ``strict`` refuses v2 outright — the ALM bar rises
        # to "AL-1 required" the same way the substrate bar rose to
        # "RK-3 required" in module_06.
        if knot.schema_version < 3:
            if strict:
                return False
            warnings.warn(
                f"AL-1 skipped for pre-v3 sidecar {knot.workspace_path!r}: "
                "sidecar predates anti-lazy attestation. Re-sign under "
                "v0.4-ALM to lift the bar.",
                DeprecationWarning,
                stacklevel=3,
            )
            return True

        # v3 sidecar: run AL-1.
        # AL-1.1 anti-lazy signature verifies under the ALM pubkey.
        alm_pk: bytes | None = None
        if alm_pubkey is not None:
            alm_pk = alm_pubkey(knot)
        if alm_pk is None:
            if strict:
                return False
            warnings.warn(
                f"AL-1.1 skipped for v3 sidecar {knot.workspace_path!r}: "
                "no ALM pubkey resolvable. Pass ``alm_pubkey=…`` to "
                "verify_workspace to lift the skip.",
                UserWarning,
                stacklevel=3,
            )
        else:
            if not knot.verify_antilazy(alm_pk):
                return False

        # AL-1.2 every GateResult is PASS or has an approved handshake id.
        approved = approved_gate_exceptions or set()
        for gr in knot.gate_results:
            if gr.passed:
                continue
            if gr.handshake_id and gr.handshake_id in approved:
                continue
            return False

        # AL-1.3 reversal_taint is clean or the run is on the accepted-
        # partial list.
        if knot.reversal_taint != "clean":
            accepted = accepted_partial_taint_runs or set()
            if knot.plan_id not in accepted:
                return False

        return True

    for rel_path, knot in knots.items():
        if not _check_knot(knot, set()):
            violation = _classify_violation(
                index,
                knot,
                active_plans,
                registered_assumptions,
                generator_pubkey,
                sandbox_pubkey=sandbox_pubkey,
                registered_suites=registered_suites,
                registered_manifests=registered_manifests,
                alm_pubkey=alm_pubkey,
                approved_gate_exceptions=approved_gate_exceptions,
                accepted_partial_taint_runs=accepted_partial_taint_runs,
                strict=strict,
                min_acceptable_schema_version=min_acceptable_schema_version,
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
                    "schema_version": knot.schema_version,
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
    *,
    sandbox_pubkey: Callable[[Rootknot], bytes | None] | None = None,
    registered_suites: set[Digest] | None = None,
    registered_manifests: set[Digest] | None = None,
    alm_pubkey: Callable[[Rootknot], bytes | None] | None = None,
    approved_gate_exceptions: set[str] | None = None,
    accepted_partial_taint_runs: set[bytes] | None = None,
    strict: bool = False,
    min_acceptable_schema_version: int | None = None,
) -> ProvenanceViolation:
    """Return the most specific predicate that fails for ``knot``."""
    # v0.5.2 module_01: schema-invariant classifications come first so
    # the operator sees the sharpest diagnostic (an unknown-major or
    # downgrade attempt shadows a v3-shape rk3 sub-clause). Deep-audit
    # A M-1 / M-2 / F-1 closure.
    if knot.schema_version not in _KNOWN_SCHEMA_VERSIONS:
        return ProvenanceViolation(
            file=knot.workspace_path,
            predicate="RK-UNKNOWN-SCHEMA",
            detail=(
                f"schema_version={knot.schema_version} not in "
                f"{sorted(_KNOWN_SCHEMA_VERSIONS)}; refusing rather "
                "than reinterpreting under weaker semantics "
                "(deep-audit A M-2). Upgrade the verifier to a build "
                "that knows this major, or re-sign the artifact under "
                "an implemented schema_version."
            ),
        )
    if (
        min_acceptable_schema_version is not None
        and knot.schema_version < min_acceptable_schema_version
    ):
        return ProvenanceViolation(
            file=knot.workspace_path,
            predicate="RK-DOWNGRADE-REFUSED",
            detail=(
                f"schema_version={knot.schema_version} below policy "
                f"floor {min_acceptable_schema_version}; refusing the "
                "weaker attestation (deep-audit A M-1 DOWNGRADE "
                "defence)."
            ),
        )
    if knot.schema_version == 4:
        missing_v4: list[str] = []
        # v0.5.2 module_01 SP amendment (Ox Alpha + cross-family Q5):
        # zero-digest sentinel treated as missing here too so the
        # classifier surfaces the sharp diagnostic.
        from ract.core.rootknot import _ZERO_DIGEST as _ZD

        if not knot.workspace_digest or knot.workspace_digest == _ZD:
            missing_v4.append("workspace_digest")
        if not knot.prompt_digest or knot.prompt_digest == _ZD:
            missing_v4.append("prompt_digest")
        if not knot.run_id:
            missing_v4.append("run_id")
        if missing_v4:
            return ProvenanceViolation(
                file=knot.workspace_path,
                predicate="RK-V4-LABEL-MISMATCH",
                detail=(
                    "v4 schema-label but v4 fields empty: "
                    f"{missing_v4}. The label carries no attestation "
                    "guarantee when the fields it names are absent "
                    "(deep-audit A F-1)."
                ),
            )
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
            detail="generator signature does not verify",
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

    # RK-3 sub-clauses
    if knot.schema_version < 2 and strict:
        return ProvenanceViolation(
            file=knot.workspace_path,
            predicate="RK-3",
            detail=(
                "v1 sidecar refused under --strict; re-sign the artifact "
                "under v0.4 to lift the bar"
            ),
        )

    if knot.schema_version >= 2:
        sbx_pk: bytes | None = None
        if sandbox_pubkey is not None:
            sbx_pk = sandbox_pubkey(knot)
        if sbx_pk is None and strict:
            return ProvenanceViolation(
                file=knot.workspace_path,
                predicate="RK-3.1",
                detail="no sandbox pubkey resolvable under --strict",
            )
        if sbx_pk is not None and not knot.verify_environment(sbx_pk):
            return ProvenanceViolation(
                file=knot.workspace_path,
                predicate="RK-3.1",
                detail="environment signature does not verify",
            )
        if (
            registered_suites is not None
            and knot.acceptance_suite_digest not in registered_suites
        ):
            return ProvenanceViolation(
                file=knot.workspace_path,
                predicate="RK-3.2",
                detail="acceptance_suite_digest not registered",
            )
        if not knot.predicate_results:
            return ProvenanceViolation(
                file=knot.workspace_path,
                predicate="RK-3.3",
                detail="predicate_results is empty",
            )
        if (
            registered_manifests is not None
            and knot.manifest_digest not in registered_manifests
        ):
            return ProvenanceViolation(
                file=knot.workspace_path,
                predicate="RK-3.4",
                detail="manifest_digest not registered",
            )

    # AL-1 sub-clauses (v3 sidecars, ALM module_05)
    if knot.schema_version < 3 and strict:
        return ProvenanceViolation(
            file=knot.workspace_path,
            predicate="AL-1",
            detail=(
                "pre-v3 sidecar refused under --strict; re-sign the "
                "artifact under v0.4-ALM to lift the bar"
            ),
        )

    if knot.schema_version >= 3:
        alm_pk: bytes | None = None
        if alm_pubkey is not None:
            alm_pk = alm_pubkey(knot)
        if alm_pk is None and strict:
            return ProvenanceViolation(
                file=knot.workspace_path,
                predicate="AL-1.1",
                detail="no ALM pubkey resolvable under --strict",
            )
        if alm_pk is not None and not knot.verify_antilazy(alm_pk):
            return ProvenanceViolation(
                file=knot.workspace_path,
                predicate="AL-1.1",
                detail="anti-lazy signature does not verify",
            )
        approved = approved_gate_exceptions or set()
        for gr in knot.gate_results:
            if gr.passed:
                continue
            if gr.handshake_id and gr.handshake_id in approved:
                continue
            return ProvenanceViolation(
                file=knot.workspace_path,
                predicate="AL-1.2",
                detail=(
                    f"gate {gr.gate_id} failed without approved handshake"
                    + (f" (handshake_id={gr.handshake_id})" if gr.handshake_id else "")
                ),
            )
        if knot.reversal_taint != "clean":
            accepted = accepted_partial_taint_runs or set()
            if knot.plan_id not in accepted:
                return ProvenanceViolation(
                    file=knot.workspace_path,
                    predicate="AL-1.3",
                    detail=(
                        f"reversal_taint={knot.reversal_taint!r} without "
                        "operator handshake accepting partial taint"
                    ),
                )

    return ProvenanceViolation(
        file=knot.workspace_path,
        predicate="RK-1.6",
        detail="parent digest does not resolve",
    )


# RACT 0.4.0
