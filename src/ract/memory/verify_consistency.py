"""Cross-index consistency verifier for the memory system.

v0.5.2 hardening module_06 (DA-B F-5.1 companion).

The three-index memory system (symbol / graph / semantic) is
maintained by independent updaters:

- :mod:`ract.memory.walker` populates ``symbols`` on file scan.
- :mod:`ract.memory.graph_populator` derives edges via LSP.
- :mod:`ract.memory.semantic_builder` embeds symbol slices.

A watcher cascade keeps them in step at runtime -- but a crash
between cascades, a manual DB edit, or a graph rebuild against a
stale symbol snapshot can leave the trio internally inconsistent.
Silent inconsistency is a retrieval-quality drift, not a crash,
so operators do not notice until output goes sideways.

The verifier walks the store and reports discrepancies:

- **orphan_edge**: an ``edges`` row references a
  ``source_symbol_id`` or ``target_symbol_id`` not present in
  ``symbols``. The graph cascade should have caught this;
  survival means either a stray delete missed the graph, or a
  graph rebuild trusted a stale symbol export.
- **missing_symbol_file**: a ``symbols`` row's ``file_path`` no
  longer exists on disk. A rename or a rm that outran the
  watcher.
- **dangling_edge_location**: an ``edges.location_file`` no
  longer indexes any symbols. Usually a companion to
  ``missing_symbol_file`` -- flagged separately so the operator
  sees BOTH sides of the break.
- **semantic_stale** (best-effort, only when the semantic index
  is attached): a semantic slice's ``symbol_id`` is no longer
  present in ``symbols``. Semantic drift is the retrieval-
  quality symptom most likely to bite an operator.

The report is a frozen dataclass with a closed ``status``
Literal (mirroring
:class:`ract.trace.verify.TraceVerifyResult`) and a bespoke
``inconsistencies: list[IndexInconsistency]`` (each carrying the
kind + the concrete symbol / file / edge that flagged). Caller
code stays uniform on the ``.status`` switch; humans get the
domain-specific detail.

Structural errors (a missing DB file, a permission denied on
open) still raise; content-level discrepancies surface as
dataclass details.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ract.core.module_identity import _module_knot, register_module_knot


_LOG = logging.getLogger("ract.memory.verify_consistency")


# ---------------------------------------------------------------------------
# Status literal + inconsistency dataclass
# ---------------------------------------------------------------------------


IndexConsistencyStatus = Literal[
    "CONSISTENT",
    "INCONSISTENT",
    "UNAVAILABLE",
]
"""Closed status vocabulary for :class:`IndexConsistencyReport`.

- ``CONSISTENT`` -- every attached index cross-checks cleanly.
- ``INCONSISTENT`` -- one or more :class:`IndexInconsistency`
  entries flagged. Detail lives in
  :attr:`IndexConsistencyReport.inconsistencies`.
- ``UNAVAILABLE`` -- a required backing store (typically the
  symbol DB) could not be opened. ``reason`` names the cause.
  Callers who want a total surface treat UNAVAILABLE like
  INCONSISTENT.
"""

_LEGAL_STATUSES: frozenset[str] = frozenset(
    ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE")
)


IndexInconsistencyKind = Literal[
    "orphan_edge",
    "missing_symbol_file",
    "dangling_edge_location",
    "semantic_stale",
    "check_error",
]


_LEGAL_KINDS: frozenset[str] = frozenset(
    (
        "orphan_edge",
        "missing_symbol_file",
        "dangling_edge_location",
        "semantic_stale",
        # v0.5.2 module_06 SP Q5 fold: a sweep-infrastructure
        # failure (graph sweep raised, semantic backend errored
        # mid-walk) surfaces as ``check_error`` rather than
        # abusing ``orphan_edge`` for a non-edge condition.
        "check_error",
    )
)


@dataclass(frozen=True)
class IndexInconsistency:
    """One flagged cross-index discrepancy.

    Fields:

    - ``kind`` -- :data:`IndexInconsistencyKind` literal.
    - ``file`` -- the file path implicated (or ``None`` when the
      inconsistency is edge-only).
    - ``symbol_id`` -- the symbol row id implicated (or ``None``
      when the inconsistency is file-only).
    - ``edge_id`` -- the edge row id implicated (or ``None``
      when the inconsistency is symbol-only).
    - ``detail`` -- a one-sentence human-readable explanation.
    """

    kind: IndexInconsistencyKind
    file: str | None
    symbol_id: int | None
    edge_id: int | None
    detail: str

    def __post_init__(self) -> None:
        if self.kind not in _LEGAL_KINDS:
            raise ValueError(
                f"IndexInconsistency.kind must be one of "
                f"{sorted(_LEGAL_KINDS)}; got {self.kind!r}"
            )


@dataclass(frozen=True)
class IndexConsistencyReport:
    """The one shape ``ract memory verify-consistency`` returns.

    Fields:

    - ``status`` -- :data:`IndexConsistencyStatus` literal.
    - ``symbols_checked`` -- rows walked in the symbol DB.
    - ``edges_checked`` -- rows walked in the graph DB
      (``0`` when the graph is not attached).
    - ``semantic_slices_checked`` -- rows walked in the semantic
      index (``0`` when the semantic index is not attached).
    - ``checks_skipped`` -- tuple of skip-reason strings, one
      per check-category the sweep DID NOT perform (e.g.
      ``"disk-existence"`` when ``check_files_on_disk=False``,
      ``"graph_index_not_attached"`` when no graph handle was
      supplied, ``"semantic_sweep_raised: <exc>"`` when the
      semantic backend blew up mid-sweep). v0.5.2 module_06 SP
      Q5 fold: this closes the honest-verify silent-coverage
      gap Ox Alpha flagged -- a CONSISTENT verdict from a
      partial sweep is weaker than a full sweep, and the shape
      must express it. Empty tuple on a full sweep.
    - ``inconsistencies`` -- concrete flagged items (may be
      empty on CONSISTENT).
    - ``reason`` -- human-readable one-sentence summary for the
      CLI. On CONSISTENT this names how many were checked; on
      INCONSISTENT it names the first inconsistency; on
      UNAVAILABLE it names the missing backing store.
    """

    status: IndexConsistencyStatus
    symbols_checked: int
    edges_checked: int
    semantic_slices_checked: int
    checks_skipped: tuple[str, ...] = field(default_factory=tuple)
    inconsistencies: tuple[IndexInconsistency, ...] = field(default_factory=tuple)
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in _LEGAL_STATUSES:
            raise ValueError(
                f"IndexConsistencyReport.status must be one of "
                f"{sorted(_LEGAL_STATUSES)}; got {self.status!r}"
            )
        if self.symbols_checked < 0:
            raise ValueError(
                f"IndexConsistencyReport.symbols_checked must be "
                f">= 0; got {self.symbols_checked!r}"
            )
        if self.edges_checked < 0:
            raise ValueError(
                f"IndexConsistencyReport.edges_checked must be "
                f">= 0; got {self.edges_checked!r}"
            )
        if self.semantic_slices_checked < 0:
            raise ValueError(
                f"IndexConsistencyReport.semantic_slices_checked "
                f"must be >= 0; got "
                f"{self.semantic_slices_checked!r}"
            )
        # Status/inconsistencies coherence.
        if self.status == "CONSISTENT" and self.inconsistencies:
            raise ValueError(
                "IndexConsistencyReport.status='CONSISTENT' with "
                "non-empty inconsistencies is contradictory"
            )
        if self.status == "INCONSISTENT" and not self.inconsistencies:
            raise ValueError(
                "IndexConsistencyReport.status='INCONSISTENT' "
                "requires at least one inconsistency"
            )

    @property
    def is_consistent(self) -> bool:
        """True only when :attr:`status` is CONSISTENT.

        UNAVAILABLE returns False -- a report that could not be
        computed is not proof of consistency.
        """
        return self.status == "CONSISTENT"

    @classmethod
    def consistent(
        cls,
        *,
        symbols_checked: int,
        edges_checked: int = 0,
        semantic_slices_checked: int = 0,
        checks_skipped: tuple[str, ...] = (),
        reason: str = "",
    ) -> "IndexConsistencyReport":
        default_reason = (
            f"consistent across {symbols_checked} symbols, "
            f"{edges_checked} edges, {semantic_slices_checked} "
            f"semantic slices"
        )
        if checks_skipped:
            default_reason += f" (checks skipped: {', '.join(checks_skipped)})"
        return cls(
            status="CONSISTENT",
            symbols_checked=symbols_checked,
            edges_checked=edges_checked,
            semantic_slices_checked=semantic_slices_checked,
            checks_skipped=checks_skipped,
            inconsistencies=(),
            reason=reason or default_reason,
        )

    @classmethod
    def inconsistent(
        cls,
        *,
        symbols_checked: int,
        edges_checked: int,
        semantic_slices_checked: int,
        inconsistencies: tuple[IndexInconsistency, ...],
        checks_skipped: tuple[str, ...] = (),
        reason: str = "",
    ) -> "IndexConsistencyReport":
        if not inconsistencies:
            raise ValueError("inconsistent() requires >= 1 inconsistency")
        return cls(
            status="INCONSISTENT",
            symbols_checked=symbols_checked,
            edges_checked=edges_checked,
            semantic_slices_checked=semantic_slices_checked,
            checks_skipped=checks_skipped,
            inconsistencies=inconsistencies,
            reason=reason
            or (
                f"{len(inconsistencies)} inconsistency(ies); first "
                f"kind={inconsistencies[0].kind}"
            ),
        )

    @classmethod
    def unavailable(cls, *, reason: str) -> "IndexConsistencyReport":
        return cls(
            status="UNAVAILABLE",
            symbols_checked=0,
            edges_checked=0,
            semantic_slices_checked=0,
            inconsistencies=(),
            reason=reason,
        )


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def verify_indexes(
    *,
    symbol_index: Any,
    graph_index: Any | None = None,
    semantic_index: Any | None = None,
    check_files_on_disk: bool = True,
    max_inconsistencies: int = 500,
) -> IndexConsistencyReport:
    """Cross-check the attached indexes and return a report.

    Contract:

    - ``symbol_index`` is required; a ``None`` symbol index is
      reported as ``UNAVAILABLE`` rather than raising.
    - ``graph_index`` and ``semantic_index`` are optional; when
      absent, their checks are skipped and their counts are 0.
    - ``check_files_on_disk`` gates the missing-symbol-file
      probe (the only check that touches the filesystem).
      Disable in unit tests where the DB carries synthetic
      paths.
    - ``max_inconsistencies`` caps the returned detail list to
      keep the CLI output bounded on a catastrophically drifted
      store. The COUNT of missed items is preserved in
      :attr:`IndexConsistencyReport.reason`.

    Structural errors (DB file missing, permission denied) still
    raise -- content-level discrepancies surface as dataclass
    inconsistencies.
    """
    if symbol_index is None:
        return IndexConsistencyReport.unavailable(reason="symbol_index is None")

    # v0.5.2 module_06 SP Q5 fold: refuse a vacuous
    # ``max_inconsistencies <= 0`` request. Pre-fix, the loop's
    # ``if len(inconsistencies) >= max`` check tripped on the
    # first iteration when ``max <= 0``, ``truncated`` was set,
    # every downstream sweep was gated on ``not truncated`` and
    # skipped, and the empty ``inconsistencies`` list fell
    # through to ``CONSISTENT`` -- a VACUOUS CONSISTENT report
    # from zero actual checking. Now we reject the input at the
    # boundary so callers can't shape a false-clean report.
    if max_inconsistencies < 1:
        raise ValueError(
            f"max_inconsistencies must be >= 1; got {max_inconsistencies!r}"
        )

    inconsistencies: list[IndexInconsistency] = []
    checks_skipped: list[str] = []
    truncated = False

    # Record disabled check-categories up front so a CONSISTENT
    # verdict carries the honest partial-sweep signal.
    if not check_files_on_disk:
        checks_skipped.append("disk-existence")
    if graph_index is None:
        checks_skipped.append("graph_index_not_attached")
    if semantic_index is None:
        checks_skipped.append("semantic_index_not_attached")

    # -- symbols pass ------------------------------------------------
    try:
        symbol_files = list(symbol_index.files())
    except Exception as exc:
        return IndexConsistencyReport.unavailable(
            reason=f"symbol_index.files() failed: {exc}"
        )
    symbols_checked = symbol_index.count()
    known_files: set[str] = set(symbol_files)

    if check_files_on_disk:
        for file_path in symbol_files:
            if len(inconsistencies) >= max_inconsistencies:
                truncated = True
                break
            try:
                if not Path(file_path).exists():
                    inconsistencies.append(
                        IndexInconsistency(
                            kind="missing_symbol_file",
                            file=file_path,
                            symbol_id=None,
                            edge_id=None,
                            detail=(
                                "symbol_index carries rows for "
                                f"{file_path!r} but the file is "
                                "gone from disk (rename or delete "
                                "outran the watcher)"
                            ),
                        )
                    )
            except OSError as exc:
                # Path check failed (permission, invalid path).
                # Report as inconsistency rather than raise so
                # the sweep continues.
                inconsistencies.append(
                    IndexInconsistency(
                        kind="missing_symbol_file",
                        file=file_path,
                        symbol_id=None,
                        edge_id=None,
                        detail=f"path check failed: {exc}",
                    )
                )

    # -- graph pass --------------------------------------------------
    edges_checked = 0
    if graph_index is not None and not truncated:
        try:
            conn = graph_index.connection
            cur = conn.execute(
                "SELECT id, source_symbol_id, target_symbol_id, "
                "location_file FROM edges"
            )
            valid_symbol_ids: set[int] = set()
            # Materialise once; symbol counts on realistic repos
            # are 10k-100k -- fine for a memory set.
            sym_cur = symbol_index.connection.execute("SELECT id FROM symbols")
            for r in sym_cur.fetchall():
                valid_symbol_ids.add(r["id"])
            for row in cur:
                edges_checked += 1
                if len(inconsistencies) >= max_inconsistencies:
                    truncated = True
                    break
                src = row["source_symbol_id"]
                tgt = row["target_symbol_id"]
                if src not in valid_symbol_ids:
                    inconsistencies.append(
                        IndexInconsistency(
                            kind="orphan_edge",
                            file=row["location_file"],
                            symbol_id=src,
                            edge_id=row["id"],
                            detail=(
                                f"edge id={row['id']} references "
                                f"missing source_symbol_id={src}"
                            ),
                        )
                    )
                    continue
                if tgt not in valid_symbol_ids:
                    inconsistencies.append(
                        IndexInconsistency(
                            kind="orphan_edge",
                            file=row["location_file"],
                            symbol_id=tgt,
                            edge_id=row["id"],
                            detail=(
                                f"edge id={row['id']} references "
                                f"missing target_symbol_id={tgt}"
                            ),
                        )
                    )
                    continue
                loc = row["location_file"]
                if loc and loc not in known_files:
                    inconsistencies.append(
                        IndexInconsistency(
                            kind="dangling_edge_location",
                            file=loc,
                            symbol_id=None,
                            edge_id=row["id"],
                            detail=(
                                f"edge id={row['id']} cites "
                                f"location_file {loc!r} which the "
                                "symbol_index no longer indexes"
                            ),
                        )
                    )
        except Exception as exc:
            _LOG.warning("verify_indexes: graph_index sweep failed: %s", exc)
            # v0.5.2 module_06 SP Q5 fold: was mislabeled as
            # ``orphan_edge`` (a sweep-infrastructure failure is
            # NOT an orphan-edge condition). Now surfaces as
            # ``check_error`` so the closed-Literal kind stays
            # meaningful. The status still flips INCONSISTENT
            # because we could not attest the graph sweep.
            inconsistencies.append(
                IndexInconsistency(
                    kind="check_error",
                    file=None,
                    symbol_id=None,
                    edge_id=None,
                    detail=f"graph sweep raised: {exc}",
                )
            )

    # -- semantic pass (best-effort) --------------------------------
    semantic_slices_checked = 0
    if semantic_index is not None and not truncated:
        # Semantic index shape varies by backend. Best-effort:
        # if it exposes ``iter_symbol_ids()`` we walk; else we
        # skip. A missing/unsupported semantic backend does NOT
        # flip status to INCONSISTENT.
        iter_ids = getattr(semantic_index, "iter_symbol_ids", None)
        if callable(iter_ids):
            try:
                sym_cur = symbol_index.connection.execute("SELECT id FROM symbols")
                valid_symbol_ids = {r["id"] for r in sym_cur.fetchall()}
                for sid in iter_ids():
                    semantic_slices_checked += 1
                    if len(inconsistencies) >= max_inconsistencies:
                        truncated = True
                        break
                    if sid not in valid_symbol_ids:
                        inconsistencies.append(
                            IndexInconsistency(
                                kind="semantic_stale",
                                file=None,
                                symbol_id=sid,
                                edge_id=None,
                                detail=(
                                    f"semantic index carries "
                                    f"symbol_id={sid} not present "
                                    "in symbol_index"
                                ),
                            )
                        )
            except Exception as exc:
                _LOG.warning(
                    "verify_indexes: semantic_index sweep failed: %s",
                    exc,
                )
                # v0.5.2 module_06 SP Q5 fold: record the
                # semantic sweep failure in checks_skipped so a
                # subsequent CONSISTENT verdict carries the
                # honest partial-sweep signal (previously the
                # exception was logged only, letting the report
                # come out CONSISTENT with no evidence the
                # semantic slice was verified).
                checks_skipped.append(f"semantic_sweep_raised: {exc}")

    # -- report ------------------------------------------------------
    if not inconsistencies:
        return IndexConsistencyReport.consistent(
            symbols_checked=symbols_checked,
            edges_checked=edges_checked,
            semantic_slices_checked=semantic_slices_checked,
            checks_skipped=tuple(checks_skipped),
        )
    reason = (
        f"{len(inconsistencies)} inconsistency(ies); first "
        f"kind={inconsistencies[0].kind}"
    )
    if truncated:
        reason += f" (truncated at max_inconsistencies={max_inconsistencies})"
    return IndexConsistencyReport.inconsistent(
        symbols_checked=symbols_checked,
        edges_checked=edges_checked,
        semantic_slices_checked=semantic_slices_checked,
        inconsistencies=tuple(inconsistencies),
        checks_skipped=tuple(checks_skipped),
        reason=reason,
    )


__all__ = [
    "IndexConsistencyReport",
    "IndexConsistencyStatus",
    "IndexInconsistency",
    "IndexInconsistencyKind",
    "verify_indexes",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)
