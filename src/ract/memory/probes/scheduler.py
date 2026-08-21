"""Probe scheduler + capability record persistence (module_08 step 5).

Runs the three probes (needle, coherence, adherence) against a
provider, reduces the reports into a :class:`ModelCapability` record,
and writes it atomically to ``.ract/probes/capability.json``
(unified on ``.ract/`` by v0.5.1 wiring module_10, Lens A C2).

Design notes:

- ``write_capability_record`` uses atomic-replace (write to a
  ``.tmp`` sibling, ``os.replace`` into place) so a process kill
  mid-write cannot leave a truncated JSON file on disk (Second Pass
  Q4 in module_08.md).
- ``read_capability_record`` returns ``None`` on missing file
  (fresh install path); it raises on malformed JSON so a corrupted
  file surfaces immediately rather than silently reverting to spec
  defaults.
- The actual cron scheduler defers to v0.6 per master spec §Bounded
  scope; :class:`ProbeScheduler` here is a synchronous harness that
  ``ract memory init`` will invoke once and (in v0.6) a weekly cron
  will invoke on cadence.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ract.canonical import dumps_jcs
from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.events import EventSink, NullEventSink, emit_probe_evaluated
from ract.memory.probes.adherence import AdherenceProbe, AdherenceProbeReport
from ract.memory.probes.coherence import CoherenceProbe, CoherenceProbeReport
from ract.memory.probes.needle import NeedleProbe, NeedleProbeReport


from ract.workspace_state import WORKSPACE_STATE_DIR_NAME as _RACT_DIR

CAPABILITY_RECORD_PATH: Path = Path(_RACT_DIR) / "probes" / "capability.json"
"""Relative location of the shipped capability record.

Callers pass a repo root; the writer joins that root with this
path. Tests use a tmp_path for isolation.
"""

CAPABILITY_SCHEMA_VERSION: int = 1
"""Schema version for the JSON record. Bumped when the payload shape changes."""


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelCapability:
    """Reduced capability record derived from the three probe reports.

    ``usable_context_window`` — from :class:`NeedleProbeReport`.
    ``reasoning_quality_bound`` — from :class:`CoherenceProbeReport`.
    ``persistence_bound`` — from :class:`AdherenceProbeReport`.
    ``recorded_at`` — POSIX seconds when the record was written.
    ``schema_version`` — capability record schema version.
    """

    usable_context_window: int
    reasoning_quality_bound: int
    persistence_bound: int
    recorded_at: int
    schema_version: int = CAPABILITY_SCHEMA_VERSION


@dataclass(frozen=True)
class ProbeReports:
    """Aggregate carrier for the three per-probe reports.

    :func:`run_all_probes` returns this record; the scheduler and the
    write helper both consume it.
    """

    needle: NeedleProbeReport
    coherence: CoherenceProbeReport
    adherence: AdherenceProbeReport


# ---------------------------------------------------------------------------
# Scheduler + runner
# ---------------------------------------------------------------------------


def run_all_probes(
    provider: Any,
    *,
    declaration: Any | None = None,
    sink: EventSink | None = None,
    needle_probe: NeedleProbe | None = None,
    coherence_probe: CoherenceProbe | None = None,
    adherence_probe: AdherenceProbe | None = None,
) -> ProbeReports:
    """Run the three probes and return their reports.

    Every probe is invoked with the SAME ``provider`` and
    ``declaration``; probes do not share state across runs. The
    ``sink`` is threaded to each probe so ``probe.evaluated`` events
    fire in a single trace stream.
    """
    active_needle = needle_probe or NeedleProbe()
    active_coherence = coherence_probe or CoherenceProbe()
    active_adherence = adherence_probe or AdherenceProbe()
    active_sink = sink or NullEventSink()
    needle_report = active_needle.run(
        provider, declaration=declaration, sink=active_sink
    )
    coherence_report = active_coherence.run(
        provider, declaration=declaration, sink=active_sink
    )
    adherence_report = active_adherence.run(
        provider, declaration=declaration, sink=active_sink
    )
    return ProbeReports(
        needle=needle_report,
        coherence=coherence_report,
        adherence=adherence_report,
    )


@dataclass
class ProbeScheduler:
    """Synchronous probe harness.

    v0.5.0 ships :meth:`run_once` (invoked by ``ract memory init``);
    the cron-driven weekly cadence lands in v0.6. The scheduler
    accepts the three probe instances so a caller can pin the
    context sizes / depths per environment.
    """

    needle_probe: NeedleProbe = field(default_factory=NeedleProbe)
    coherence_probe: CoherenceProbe = field(default_factory=CoherenceProbe)
    adherence_probe: AdherenceProbe = field(default_factory=AdherenceProbe)

    def run_once(
        self,
        provider: Any,
        *,
        declaration: Any | None = None,
        sink: EventSink | None = None,
    ) -> ProbeReports:
        """Run the three probes exactly once."""
        return run_all_probes(
            provider,
            declaration=declaration,
            sink=sink,
            needle_probe=self.needle_probe,
            coherence_probe=self.coherence_probe,
            adherence_probe=self.adherence_probe,
        )


# ---------------------------------------------------------------------------
# Capability record persistence
# ---------------------------------------------------------------------------


def reduce_to_capability(reports: ProbeReports) -> ModelCapability:
    """Reduce the three reports into a :class:`ModelCapability` record."""
    return ModelCapability(
        usable_context_window=reports.needle.usable_context_window,
        reasoning_quality_bound=reports.coherence.reasoning_quality_bound,
        persistence_bound=reports.adherence.persistence_bound,
        recorded_at=int(time.time()),
    )


def write_capability_record(
    reports: ProbeReports,
    root: Path,
    *,
    sink: EventSink | None = None,
) -> Path:
    """Write the reduced record atomically under ``root``.

    Path resolves as ``root / CAPABILITY_RECORD_PATH``. Parent
    directories are created on demand. The write uses tmp + fsync +
    ``os.replace`` so a process kill mid-write cannot corrupt the
    on-disk record (Second Pass Q4).
    """
    active_sink = sink or NullEventSink()
    capability = reduce_to_capability(reports)
    target = root / CAPABILITY_RECORD_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _capability_to_json(capability)
    # Write via tempfile in the same directory so os.replace is
    # atomic on both POSIX and Windows.
    fd, tmp_name = tempfile.mkstemp(
        prefix="capability-",
        suffix=".json.tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    emit_probe_evaluated(
        active_sink,
        {
            "probe": "scheduler",
            "action": "capability_record_written",
            "path": str(target),
            "usable_context_window": capability.usable_context_window,
            "reasoning_quality_bound": capability.reasoning_quality_bound,
            "persistence_bound": capability.persistence_bound,
        },
    )
    return target


def read_capability_record(root: Path) -> ModelCapability | None:
    """Return the capability record under ``root`` or ``None``.

    Returns ``None`` when the file is missing (fresh install path so
    the caller falls back to module_01 spec defaults). Raises
    :class:`ValueError` on malformed JSON or unsupported schema
    version — a corrupted file must surface loudly rather than
    silently reverting to defaults (module_04 semantic-index
    ``SemanticStoreCorruptError`` precedent).
    """
    target = root / CAPABILITY_RECORD_PATH
    if not target.is_file():
        return None
    text = target.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"capability record at {target} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"capability record at {target} must be a JSON object; "
            f"got {type(payload).__name__}"
        )
    schema_version = payload.get("schema_version")
    if schema_version != CAPABILITY_SCHEMA_VERSION:
        raise ValueError(
            f"capability record at {target} has unsupported schema_version "
            f"{schema_version!r}; expected {CAPABILITY_SCHEMA_VERSION!r}"
        )
    return _capability_from_json(payload)


def _capability_to_json(capability: ModelCapability) -> str:
    """Return the canonical JSON string for a :class:`ModelCapability`.

    v0.5.1 module_09 (Lens F H3 closure): migrated from
    ``json.dumps(sort_keys=True, separators=(",", ": "))`` to
    :func:`ract.canonical.dumps_jcs`. The prior custom-separators form
    was not JCS-canonical; the capability record is consumed as-is by
    :func:`read_capability_record` (JSON parse) so migration is
    behavior-preserving, and any future promotion of this record to a
    hash-input surface (probe-attestation event, capability sidecar
    signature) inherits stable canonical bytes for free.
    """
    payload = {
        "schema_version": capability.schema_version,
        "usable_context_window": capability.usable_context_window,
        "reasoning_quality_bound": capability.reasoning_quality_bound,
        "persistence_bound": capability.persistence_bound,
        "recorded_at": capability.recorded_at,
    }
    return dumps_jcs(payload).decode("utf-8") + "\n"


def _capability_from_json(payload: dict[str, Any]) -> ModelCapability:
    """Return a :class:`ModelCapability` from a parsed JSON payload."""
    required = (
        "usable_context_window",
        "reasoning_quality_bound",
        "persistence_bound",
        "recorded_at",
    )
    for key in required:
        if key not in payload:
            raise ValueError(
                f"capability record missing required field {key!r}; "
                f"got keys {sorted(payload)!r}"
            )
        if not isinstance(payload[key], int) or isinstance(payload[key], bool):
            raise ValueError(
                f"capability record field {key!r} must be int; "
                f"got {type(payload[key]).__name__}"
            )
    return ModelCapability(
        usable_context_window=payload["usable_context_window"],
        reasoning_quality_bound=payload["reasoning_quality_bound"],
        persistence_bound=payload["persistence_bound"],
        recorded_at=payload["recorded_at"],
        schema_version=payload.get("schema_version", CAPABILITY_SCHEMA_VERSION),
    )


__all__ = [
    "CAPABILITY_RECORD_PATH",
    "CAPABILITY_SCHEMA_VERSION",
    "ModelCapability",
    "ProbeReports",
    "ProbeScheduler",
    "read_capability_record",
    "reduce_to_capability",
    "run_all_probes",
    "write_capability_record",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
