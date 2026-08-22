"""Sidecar file header primitive -- v0.5.2 hardening module_04.

Closes DA-B F-3.2 (loop-state sidecar lacked ``schema_version`` +
``run_id`` binding; rename of ``repair_attempts_remaining`` silently
restored default budget; cross-run resume bleed possible).

Every RACT-owned sidecar file declares its own header:

- ``schema_version`` (int) -- from the sidecar_type's known-versions
  allowlist. Refused if outside allowlist (mirrors module_01's
  Rootknot v4 ``_KNOWN_SCHEMA_VERSIONS`` policy).
- ``run_id`` (str) -- the 32-hex ambient value at write time. Refused
  by the reader if the caller passes ``expected_run_id`` and the two
  do not match.
- ``sidecar_type`` (str) -- short discriminant tag; the sidecar's
  purpose. Enables per-type schema allowlists.
- ``created_at`` (str, ISO-8601 UTC) -- provenance timestamp.
- ``ract_version`` (str) -- the ``ract.__version__`` in effect at
  write time. Diagnostic only; not a load-bearing gate (allowlist is
  the gate).

Two on-disk shapes are supported:

- **JSONL sidecars:** the first line of the file is the header
  record (``{"kind": "sidecar_header", ...}``). All subsequent lines
  are the sidecar's own records.
- **Plain-JSON sidecars:** the header is nested under a top-level
  ``"sidecar_header"`` key. The rest of the top-level payload is the
  sidecar's own body.

**Backward-compat.** v0.5.1 sidecars have NO header. In non-strict
mode (default for v0.5.2 per Ox Alpha co-build Fork 3), the reader
stamps a synthetic ``RUN-LEGACY-{sha256(file_path)[:16]}`` +
``schema_version=3`` (the last pre-header schema), logs a WARN, and
emits a ``sidecar.header.legacy_fallback`` trace event so the
migration is auditable. Strict mode refuses.

**Refusal exceptions:**

- :class:`SidecarHeaderMissing` -- no header where one was required.
- :class:`SidecarRunIdMismatch` -- header run_id differs from the
  verifier's ``expected_run_id``.
- :class:`SidecarUnknownSchema` -- ``schema_version`` not in the
  sidecar_type's allowlist.
- :class:`SidecarDowngradeRefused` -- ``schema_version`` below the
  caller's ``min_schema_version`` floor (mirrors module_01's
  ``--min-schema`` CLI flag policy).

All refusals raise a subclass of :class:`SidecarHeaderError` so
callers can catch the family in one ``except`` clause.

References:
- :mod:`ract.core.rootknot` -- ``_KNOWN_SCHEMA_VERSIONS`` allowlist
  pattern (v0.5.2 module_01).
- :mod:`ract.security.sandbox_env` -- ``RACT_INTERNAL_ENV_KEYS`` peer
  discipline (v0.5.2 module_04).
- ``_BUILD/audit_2026-08-22b/DA_B_runtime_trace_memory.md`` F-3.2.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

_LOG = logging.getLogger("ract.sidecar_header")


# ---------------------------------------------------------------------------
# Sidecar type registry -- per-type schema allowlist
# ---------------------------------------------------------------------------


# Per-sidecar-type allowed schema versions. New sidecar_types register
# via :func:`register_sidecar_type` (or by inline extension in tests).
# A sidecar written with a version outside its type's allowlist is
# refused by the reader with :class:`SidecarUnknownSchema` -- this
# closes the "forward-compat trojan" vector where an attacker labels
# a payload with an unknown future version to bypass the current
# validator.
_KNOWN_SIDECAR_SCHEMAS: dict[str, frozenset[int]] = {
    # loop_state.json (LoopController._current_persist_payload).
    # Starts at schema_version=4 in v0.5.2 (was headerless, treated
    # as v3 by the legacy-fallback path).
    "loop_state": frozenset({4}),
    # Placeholder for future sidecar types; test fixtures register
    # ad-hoc types via ``register_sidecar_type``.
}


def snapshot_registry() -> dict[str, frozenset[int]]:
    """Return a shallow-copy snapshot of the registry.

    v0.5.2 module_04 SP amendment (cross-family Q6 DEFECT verdict):
    ``_KNOWN_SIDECAR_SCHEMAS`` is a module-level mutable dict. Test
    fixtures adding ad-hoc types via :func:`register_sidecar_type`
    would previously bleed across test files (pytest ordering
    breakage). Tests now snapshot before mutation + restore in a
    teardown via :func:`restore_registry`.

    Production callers do not need to snapshot -- the registry is
    RACT-owned + populated at import.
    """
    return dict(_KNOWN_SIDECAR_SCHEMAS)


def restore_registry(snapshot: dict[str, frozenset[int]]) -> None:
    """Restore the registry to a prior snapshot.

    Companion to :func:`snapshot_registry`. Test fixtures call
    ``snapshot -> mutate -> restore`` to keep registrations
    hermetic across test files.
    """
    _KNOWN_SIDECAR_SCHEMAS.clear()
    _KNOWN_SIDECAR_SCHEMAS.update(snapshot)


def register_sidecar_type(sidecar_type: str, known_versions: frozenset[int]) -> None:
    """Register a sidecar_type + its allowed schema versions.

    Used by test fixtures and by future modules adding new sidecar
    kinds. The registration is a strict overwrite -- adding a new
    version to an existing type means passing the FULL union of the
    old + new versions in ``known_versions``.
    """
    if not isinstance(sidecar_type, str) or not sidecar_type:
        raise ValueError(
            f"sidecar_type must be a non-empty str; got {sidecar_type!r}"
        )
    if not isinstance(known_versions, frozenset):
        raise TypeError(
            f"known_versions must be frozenset[int]; got "
            f"{type(known_versions).__name__}"
        )
    if not known_versions:
        raise ValueError("known_versions must be non-empty")
    for v in known_versions:
        if not isinstance(v, int) or v < 1:
            raise ValueError(
                f"schema versions must be positive ints; got {v!r}"
            )
    _KNOWN_SIDECAR_SCHEMAS[sidecar_type] = known_versions


def known_versions_for(sidecar_type: str) -> frozenset[int]:
    """Return the allowed schema versions for a sidecar_type.

    Raises :class:`KeyError` when the type is not registered.
    """
    if sidecar_type not in _KNOWN_SIDECAR_SCHEMAS:
        raise KeyError(
            f"sidecar_type {sidecar_type!r} is not registered; call "
            f"register_sidecar_type() first"
        )
    return _KNOWN_SIDECAR_SCHEMAS[sidecar_type]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SidecarHeaderError(Exception):
    """Base class for every sidecar-header refusal.

    Callers catch this to handle any header-related refusal without
    naming the specific subclass. Subclasses carry the specific
    reason.
    """


class SidecarHeaderMissing(SidecarHeaderError):
    """Sidecar file has no header record where one was required.

    Raised by :func:`read_sidecar_header` in strict mode when the
    first line / top-level key is absent, or when the header record
    is malformed (non-dict, missing required fields).
    """


class SidecarRunIdMismatch(SidecarHeaderError):
    """Sidecar header ``run_id`` differs from the verifier's
    ``expected_run_id``.

    Carries ``header_run_id``, ``expected_run_id``, and ``path`` as
    attributes so the caller's error surface can name the specific
    file + values.
    """

    def __init__(
        self, *, path: Path, header_run_id: str, expected_run_id: str
    ) -> None:
        super().__init__(
            f"sidecar {path!s}: header run_id={header_run_id!r} does not "
            f"match expected run_id={expected_run_id!r}"
        )
        self.path = path
        self.header_run_id = header_run_id
        self.expected_run_id = expected_run_id


class SidecarSchemaError(SidecarHeaderError):
    """Base for every schema-version refusal (write-time or read-time).

    v0.5.2 module_04 SP amendment (cross-family Q3 DEFECT verdict):
    callers catch this to handle any schema-version refusal without
    having to distinguish write vs read failure paths.
    """


class SidecarUnknownSchemaAtWrite(SidecarSchemaError):
    """schema_version outside allowlist at BUILD/WRITE time -- no
    filesystem path exists yet.

    Attributes: ``sidecar_type``, ``header_schema_version``,
    ``known_versions``.
    """

    def __init__(
        self,
        *,
        sidecar_type: str,
        header_schema_version: Any,
        known_versions: frozenset[int],
    ) -> None:
        super().__init__(
            f"schema_version={header_schema_version!r} not in known "
            f"versions for sidecar_type={sidecar_type!r}: "
            f"{sorted(known_versions)}"
        )
        self.sidecar_type = sidecar_type
        self.header_schema_version = header_schema_version
        self.known_versions = known_versions


class SidecarUnknownSchemaAtRead(SidecarSchemaError):
    """schema_version outside allowlist at READ time -- real path
    exists.

    Attributes: ``path``, ``sidecar_type``, ``header_schema_version``,
    ``known_versions``.
    """

    def __init__(
        self,
        *,
        path: Path,
        sidecar_type: str,
        header_schema_version: Any,
        known_versions: frozenset[int],
    ) -> None:
        super().__init__(
            f"sidecar {path!s}: schema_version={header_schema_version!r} "
            f"not in known versions for sidecar_type={sidecar_type!r}: "
            f"{sorted(known_versions)}"
        )
        self.path = path
        self.sidecar_type = sidecar_type
        self.header_schema_version = header_schema_version
        self.known_versions = known_versions


# Backward-compat alias: SidecarUnknownSchema resolves to the READ-time
# subclass so pre-amendment except-clauses continue to work when the
# refusal was at read-time (the common case).
SidecarUnknownSchema = SidecarUnknownSchemaAtRead


class SidecarDowngradeRefused(SidecarHeaderError):
    """Sidecar header ``schema_version`` is below the caller's
    ``min_schema_version`` floor.

    Attributes: ``path``, ``header_schema_version``,
    ``min_schema_version``.
    """

    def __init__(
        self,
        *,
        path: Path,
        header_schema_version: int,
        min_schema_version: int,
    ) -> None:
        super().__init__(
            f"sidecar {path!s}: schema_version={header_schema_version} "
            f"below min_schema_version={min_schema_version} floor"
        )
        self.path = path
        self.header_schema_version = header_schema_version
        self.min_schema_version = min_schema_version


# ---------------------------------------------------------------------------
# SidecarHeader dataclass
# ---------------------------------------------------------------------------


HEADER_KIND: str = "sidecar_header"


@dataclass(frozen=True)
class SidecarHeader:
    """Parsed sidecar header.

    ``synthetic_legacy`` is True when the header was fabricated by the
    legacy-fallback path (headerless v0.5.1 sidecar in non-strict
    mode). Callers writing observability code use this flag to
    distinguish "genuinely legacy" from "genuinely current" without
    string-sniffing the ``run_id``.
    """

    kind: str
    schema_version: int
    run_id: str
    sidecar_type: str
    created_at: str
    ract_version: str
    synthetic_legacy: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict. ``synthetic_legacy`` and
        ``extra`` are NOT written -- they are consumer-side only.
        """
        return {
            "kind": self.kind,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "sidecar_type": self.sidecar_type,
            "created_at": self.created_at,
            "ract_version": self.ract_version,
        }


# ---------------------------------------------------------------------------
# Public write API
# ---------------------------------------------------------------------------


def _iso_utc_now() -> str:
    """Return the current UTC time in ISO-8601 with ``Z`` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ract_version() -> str:
    """Return the running ract package version (best-effort)."""
    try:
        from ract import __version__ as v  # noqa: PLC0415
        return str(v)
    except Exception:  # noqa: BLE001 -- diagnostic only
        return "unknown"


def build_sidecar_header(
    *,
    sidecar_type: str,
    schema_version: int,
    run_id: str,
    ract_version: str | None = None,
    created_at: str | None = None,
) -> SidecarHeader:
    """Construct a :class:`SidecarHeader` for embedding in a sidecar
    file.

    The write-side allowlist check is INTENTIONALLY strict: passing
    a ``schema_version`` outside the sidecar_type's known set raises
    :class:`SidecarUnknownSchema` at WRITE time (not read time), so
    the substrate never emits a payload the substrate itself would
    refuse to read.
    """
    if sidecar_type not in _KNOWN_SIDECAR_SCHEMAS:
        raise KeyError(
            f"sidecar_type {sidecar_type!r} is not registered; call "
            f"register_sidecar_type() first"
        )
    known = _KNOWN_SIDECAR_SCHEMAS[sidecar_type]
    if schema_version not in known:
        # We do NOT have a path here -- write-side check pre-writes.
        # SP amendment (cross-family Q3 DEFECT): raise the WRITE-time
        # subclass so callers logging ``exc.path`` on the READ-time
        # variant do not receive a synthetic ``<pre-write>`` path.
        raise SidecarUnknownSchemaAtWrite(
            sidecar_type=sidecar_type,
            header_schema_version=schema_version,
            known_versions=known,
        )
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(
            f"run_id must be a non-empty str; got {run_id!r}"
        )
    return SidecarHeader(
        kind=HEADER_KIND,
        schema_version=schema_version,
        run_id=run_id,
        sidecar_type=sidecar_type,
        created_at=created_at or _iso_utc_now(),
        ract_version=ract_version or _ract_version(),
    )


def header_as_jsonl_line(header: SidecarHeader) -> str:
    """Serialize a header for JSONL insertion as the first line.

    Trailing ``\\n`` included so callers concatenate directly.

    Uses :func:`ract.canonical.dumps_jcs` for canonical ordering
    (module_03 architecture gate: no bare ``sort_keys=True`` on
    canonical paths).
    """
    from ract.canonical import dumps_jcs  # noqa: PLC0415

    raw = dumps_jcs(header.to_dict())
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    return text + "\n"


def json_body_with_header(
    header: SidecarHeader, body: dict[str, Any]
) -> dict[str, Any]:
    """Return ``body`` with the header nested under ``sidecar_header``.

    The header key is placed first in insertion order for
    grep-friendliness; JSON-load restores as a dict either way.
    """
    if not isinstance(body, dict):
        raise TypeError(
            f"body must be dict; got {type(body).__name__}"
        )
    if "sidecar_header" in body:
        raise ValueError(
            "body already contains 'sidecar_header' key; refusing "
            "to overwrite"
        )
    out: dict[str, Any] = {"sidecar_header": header.to_dict()}
    for k, v in body.items():
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------


def _synthetic_legacy_run_id(path: Path) -> str:
    """Return a deterministic synthetic run_id for a headerless sidecar.

    Format: ``RUN-LEGACY-{sha256(absolute_path)[:16]}``. Deterministic
    across re-reads so observability tools can correlate. Uses
    absolute path so cwd differences do not produce different stamps
    for the same file.
    """
    try:
        key = str(path.resolve())
    except OSError:
        key = str(path)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"RUN-LEGACY-{digest}"


_LEGACY_SCHEMA_VERSION: int = 3


def _validate_header_shape(
    payload: Any, *, path: Path, sidecar_type: str | None
) -> SidecarHeader:
    """Validate a parsed header dict shape + return the SidecarHeader.

    Raises :class:`SidecarHeaderMissing` on shape violation. Does NOT
    check schema_version allowlist (caller does that after knowing
    the sidecar_type).
    """
    if not isinstance(payload, dict):
        raise SidecarHeaderMissing(
            f"sidecar {path!s}: header record is not a JSON object; "
            f"got {type(payload).__name__}"
        )
    if payload.get("kind") != HEADER_KIND:
        raise SidecarHeaderMissing(
            f"sidecar {path!s}: header record kind field is "
            f"{payload.get('kind')!r}, expected {HEADER_KIND!r}"
        )
    for required in ("schema_version", "run_id", "sidecar_type", "created_at"):
        if required not in payload:
            raise SidecarHeaderMissing(
                f"sidecar {path!s}: header missing required field "
                f"{required!r}"
            )
    if not isinstance(payload["schema_version"], int):
        raise SidecarHeaderMissing(
            f"sidecar {path!s}: header schema_version is not an int; "
            f"got {type(payload['schema_version']).__name__}"
        )
    if not isinstance(payload["run_id"], str) or not payload["run_id"]:
        raise SidecarHeaderMissing(
            f"sidecar {path!s}: header run_id must be a non-empty str"
        )
    if not isinstance(payload["sidecar_type"], str) or not payload["sidecar_type"]:
        raise SidecarHeaderMissing(
            f"sidecar {path!s}: header sidecar_type must be a "
            f"non-empty str"
        )
    if sidecar_type is not None and payload["sidecar_type"] != sidecar_type:
        # A sidecar_type mismatch is a header-shape violation from the
        # caller's POV -- the file was written for one purpose and the
        # reader is asking for another.
        raise SidecarHeaderMissing(
            f"sidecar {path!s}: header sidecar_type "
            f"{payload['sidecar_type']!r} does not match caller's "
            f"expected sidecar_type {sidecar_type!r}"
        )
    return SidecarHeader(
        kind=HEADER_KIND,
        schema_version=payload["schema_version"],
        run_id=payload["run_id"],
        sidecar_type=payload["sidecar_type"],
        created_at=payload["created_at"],
        ract_version=str(payload.get("ract_version", "unknown")),
        synthetic_legacy=False,
    )


def _emit_header_trace_event(
    kind: str, payload: dict[str, Any]
) -> None:
    """Best-effort trace-event emit. Silent on absence of writer.

    Uses :func:`ract.trace.sink.emit` when a run has a bound writer;
    logs at INFO otherwise. Never raises -- a header event is an
    audit signal, not a control-plane primitive.
    """
    try:
        from ract.trace.sink import emit as _emit  # noqa: PLC0415

        _emit(kind, payload)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 -- audit signal, not load-bearing
        _LOG.info("sidecar_header trace event %s payload=%s", kind, payload)


def read_sidecar_header(
    path: Path,
    *,
    sidecar_type: str | None = None,
    expected_run_id: str | None = None,
    min_schema_version: int | None = None,
    strict: bool = False,
    is_jsonl: bool = False,
) -> SidecarHeader:
    """Read + validate the header of a sidecar file.

    - ``sidecar_type`` -- when supplied, the header's ``sidecar_type``
      must match. Also triggers the ``schema_version`` allowlist
      check against ``known_versions_for(sidecar_type)``.
    - ``expected_run_id`` -- when supplied, the header's ``run_id``
      must equal this value or :class:`SidecarRunIdMismatch` is
      raised.
    - ``min_schema_version`` -- when supplied, ``schema_version`` must
      be >= this or :class:`SidecarDowngradeRefused` is raised.
      Mirrors module_01's ``--min-schema`` policy.
    - ``strict`` -- when True, a headerless file is refused with
      :class:`SidecarHeaderMissing`. When False (v0.5.2 default per
      Ox Alpha co-build Fork 3), a headerless file is accepted with
      a synthetic ``RUN-LEGACY-*`` stamp + WARN + trace event.
    - ``is_jsonl`` -- when True, the header is the FIRST LINE of the
      file (JSONL layout). When False, the header is under the
      top-level ``sidecar_header`` key of a JSON object.

    Never returns without either a valid header OR a synthetic
    legacy header. Every refusal path raises a
    :class:`SidecarHeaderError` subclass.
    """
    if not path.exists():
        raise FileNotFoundError(f"sidecar {path!s} does not exist")

    try:
        if is_jsonl:
            with path.open("r", encoding="utf-8") as fh:
                first = fh.readline()
            if not first.strip():
                header_payload: Any = None
            else:
                header_payload = json.loads(first)
            # SP amendment (Ox Alpha A Q4 DEFECT sub-finding):
            # shape-misdeclaration guard. A caller passing
            # is_jsonl=True on an envelope file whose entire
            # content is one JSON object (dumps_jcs is compact)
            # would parse the whole object AS the header. If that
            # object has no ``kind`` field, the file would
            # SILENTLY hit the legacy-fallback path, skipping the
            # binding check. Detect: parsed first-line dict that
            # contains a ``sidecar_header`` nested key AND no
            # top-level ``kind`` field is the ENVELOPE layout
            # mis-declared as JSONL.
            if (
                isinstance(header_payload, dict)
                and "sidecar_header" in header_payload
                and header_payload.get("kind") != HEADER_KIND
            ):
                raise SidecarHeaderMissing(
                    f"sidecar {path!s}: called with is_jsonl=True "
                    f"but the file appears to be envelope layout "
                    f"(nested 'sidecar_header' key detected). Call "
                    f"read_sidecar_header with is_jsonl=False."
                )
        else:
            body = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(body, dict):
                header_payload = None
            else:
                header_payload = body.get("sidecar_header")
    except SidecarHeaderMissing:
        raise
    except (OSError, ValueError) as exc:
        # File unreadable / JSON invalid. In strict mode refuse; in
        # non-strict mode treat as legacy (fall through).
        if strict:
            raise SidecarHeaderMissing(
                f"sidecar {path!s}: could not read header ({exc})"
            ) from exc
        header_payload = None

    if header_payload is None or (
        isinstance(header_payload, dict)
        and header_payload.get("kind") != HEADER_KIND
    ):
        # Headerless payload path.
        if strict:
            raise SidecarHeaderMissing(
                f"sidecar {path!s}: no header record found (strict "
                f"mode). Set strict=False to accept v0.5.1-and-earlier "
                f"sidecars with a synthetic legacy stamp."
            )
        # SP amendment (cross-family Q5 DEFECT): require sidecar_type
        # even in non-strict mode -- a caller reading a sidecar MUST
        # declare what type they expect. Prevents the "unknown"
        # sidecar_type routing key leak into downstream code.
        if sidecar_type is None:
            raise ValueError(
                f"sidecar {path!s}: read_sidecar_header requires "
                f"sidecar_type when strict=False (F-3.2 binding "
                f"contract). Pass the expected type discriminant."
            )
        synthetic = _synthetic_legacy_run_id(path)
        # SP amendment (cross-family Q2 + Ox Alpha A Q2 DEFECT):
        # closing the "run A writes headerless, run B consumes
        # same path" bleed under the legacy-fallback path. Two
        # refuse conditions, both operative in non-strict:
        #
        # (i) Caller passed ``expected_run_id`` explicitly -- they
        #     are asking to validate the sidecar's run_id, and the
        #     synthetic RUN-LEGACY-* stamp will never match a real
        #     run_id. Refuse (Ox Alpha A DEFECT: legacy branch
        #     used to early-return, silently skipping the
        #     expected_run_id check the caller requested).
        #
        # (ii) Caller did NOT pass expected_run_id but an ambient
        #      run_id is bound (implicit expectation via ambient
        #      plumbing). If ambient != synthetic (which is always
        #      the case -- synthetic is path-derived, ambient is
        #      run-scoped), refuse. Preserves the "pure
        #      observability read without any bound run" mode
        #      (both expected_run_id and ambient are None) as the
        #      only path to accept a legacy stamp silently.
        try:
            from ract.runtime import get_current_run_id  # noqa: PLC0415

            _ambient = get_current_run_id()
        except Exception:  # noqa: BLE001
            _ambient = None
        _refuse_target: str | None = None
        if expected_run_id is not None:
            _refuse_target = expected_run_id
        elif _ambient is not None and _ambient != synthetic:
            _refuse_target = _ambient
        if _refuse_target is not None:
            _emit_header_trace_event(
                "sidecar.header.mismatch_refused",
                {
                    "path": str(path),
                    "header_run_id": synthetic,
                    "expected_run_id": _refuse_target,
                    "reason": "legacy_fallback_binding_refused",
                },
            )
            raise SidecarRunIdMismatch(
                path=path,
                header_run_id=synthetic,
                expected_run_id=_refuse_target,
            )
        # SP amendment (Ox Alpha A Q2 incidental min_schema fold):
        # the legacy branch also used to skip the
        # ``min_schema_version`` floor. A caller demanding >= 4
        # would silently accept a synthetic v3 stamp. Enforce the
        # floor here too so the caller's downgrade-refusal policy
        # applies uniformly to legacy sidecars.
        if (
            min_schema_version is not None
            and _LEGACY_SCHEMA_VERSION < min_schema_version
        ):
            _emit_header_trace_event(
                "sidecar.header.missing_refused",
                {"path": str(path), "reason": "legacy_below_min_schema"},
            )
            raise SidecarDowngradeRefused(
                path=path,
                header_schema_version=_LEGACY_SCHEMA_VERSION,
                min_schema_version=min_schema_version,
            )
        header = SidecarHeader(
            kind=HEADER_KIND,
            schema_version=_LEGACY_SCHEMA_VERSION,
            run_id=synthetic,
            sidecar_type=sidecar_type,
            created_at="0000-00-00T00:00:00Z",
            ract_version="pre-header",
            synthetic_legacy=True,
        )
        _LOG.warning(
            "sidecar_header: %s has no header record; stamping "
            "synthetic legacy run_id=%s + schema_version=%d. This "
            "sidecar was written by v0.5.1 or earlier; migrate by "
            "re-writing it via a v0.5.2+ writer.",
            path,
            synthetic,
            _LEGACY_SCHEMA_VERSION,
        )
        _emit_header_trace_event(
            "sidecar.header.legacy_fallback",
            {"path": str(path), "synthetic_run_id": synthetic},
        )
        return header

    header = _validate_header_shape(
        header_payload, path=path, sidecar_type=sidecar_type
    )

    # Schema allowlist check (only when caller passed sidecar_type).
    if sidecar_type is not None:
        known = known_versions_for(sidecar_type)
        if header.schema_version not in known:
            _emit_header_trace_event(
                "sidecar.header.missing_refused",
                {"path": str(path), "reason": "unknown_schema"},
            )
            raise SidecarUnknownSchemaAtRead(
                path=path,
                sidecar_type=sidecar_type,
                header_schema_version=header.schema_version,
                known_versions=known,
            )

    if min_schema_version is not None and header.schema_version < min_schema_version:
        _emit_header_trace_event(
            "sidecar.header.missing_refused",
            {"path": str(path), "reason": "downgrade"},
        )
        raise SidecarDowngradeRefused(
            path=path,
            header_schema_version=header.schema_version,
            min_schema_version=min_schema_version,
        )

    if expected_run_id is not None and header.run_id != expected_run_id:
        _emit_header_trace_event(
            "sidecar.header.mismatch_refused",
            {
                "path": str(path),
                "header_run_id": header.run_id,
                "expected_run_id": expected_run_id,
            },
        )
        raise SidecarRunIdMismatch(
            path=path,
            header_run_id=header.run_id,
            expected_run_id=expected_run_id,
        )

    return header


# ---------------------------------------------------------------------------
# Writer helpers -- callers that want the one-liner
# ---------------------------------------------------------------------------


def write_json_sidecar_with_header(
    path: Path,
    body: dict[str, Any],
    *,
    sidecar_type: str,
    schema_version: int,
    run_id: str,
) -> SidecarHeader:
    """Write ``body`` as JSON at ``path`` with a header nested under
    ``sidecar_header``.

    Convenience helper for plain-JSON sidecars. Callers with more
    exotic serialization (JCS canonical form, JSONL) should use
    :func:`build_sidecar_header` + :func:`json_body_with_header` /
    :func:`header_as_jsonl_line` directly.

    Returns the :class:`SidecarHeader` that was written so the caller
    can echo it into an observability event.
    """
    header = build_sidecar_header(
        sidecar_type=sidecar_type,
        schema_version=schema_version,
        run_id=run_id,
    )
    merged = json_body_with_header(header, body)
    path.parent.mkdir(parents=True, exist_ok=True)
    from ract.canonical import dumps_jcs  # noqa: PLC0415

    raw = dumps_jcs(merged)
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    # SP amendment (Ox Alpha Q7 DEFECT verdict): tmp + os.replace so
    # a reader NEVER observes a partial write. Previously only the
    # loop_state persist path had this atomicity discipline; now
    # every caller of the write helper inherits it. On serialization
    # failure the tmp file is cleaned up in a finally clause so no
    # ``.tmp`` litter accumulates.
    import os as _os  # noqa: PLC0415

    tmp_path = path.parent / (path.name + ".tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        _os.replace(str(tmp_path), str(path))
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
    _emit_header_trace_event(
        "sidecar.header.written",
        {
            "path": str(path),
            "sidecar_type": sidecar_type,
            "schema_version": schema_version,
            "run_id": run_id,
        },
    )
    return header


__all__ = [
    "HEADER_KIND",
    "SidecarDowngradeRefused",
    "SidecarHeader",
    "SidecarHeaderError",
    "SidecarHeaderMissing",
    "SidecarRunIdMismatch",
    "SidecarSchemaError",
    "SidecarUnknownSchema",
    "SidecarUnknownSchemaAtRead",
    "SidecarUnknownSchemaAtWrite",
    "build_sidecar_header",
    "header_as_jsonl_line",
    "json_body_with_header",
    "known_versions_for",
    "read_sidecar_header",
    "register_sidecar_type",
    "restore_registry",
    "snapshot_registry",
    "write_json_sidecar_with_header",
]


# RACT 0.5.2 module_04
