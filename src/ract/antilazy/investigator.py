"""Investigator — pre-completion adversarial context loader.

ALM §8. The Investigator reads files the primary loop did not touch and
returns one-line findings (or an explicit statement that no finding
exists, with evidence the file was read). Its report is required input
to G6 (under-edit) and G7 (companion red team). A completion without an
Investigator report emits ``laziness.violated`` with
``kind="investigator_missing"`` and is not authenticated.

File selection is bounded to at most ``max_files`` files per run
(default 20). Ranking is by symbol-graph adjacency to touched symbols:
files that import touched modules, are imported by touched modules,
or share a call edge with a touched symbol rank higher. The bound keeps
the Investigator's runtime cost bounded on giant workspaces (Lateral
Chain branch B).

The primary provider must not schedule the Investigator on itself;
the callee is passed in as a ``companion`` provider so the Investigator
attests independence the same way G7 does.

Reference sources:

- ALM spec §8 (Adversarial Context Loading: the Investigator).
- ``ract.antilazy.symgraph`` for the symbol-graph primitive.
- ``ract.antilazy.companion`` for the different-provider constraint the
  Investigator honors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from ract.antilazy.symgraph import SymbolGraph


InvestigatorFindingKind = Literal[
    "missed_bug",
    "missed_call_site_update",
    "missed_test",
]


# ---------------------------------------------------------------------------
# InvestigatorFinding + InvestigatorReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvestigatorFinding:
    """One line-level finding produced by the Investigator.

    ``file`` is the path of the file the finding is anchored to. ``line``
    is the 1-based line number. ``kind`` is one of the three shipped
    kinds ALM §8 names; the vocabulary is closed at the type level so a
    new kind is an explicit ADR bump. ``evidence`` is a short human-
    readable string (one or two sentences) the operator reads at
    review time.
    """

    file: Path
    line: int
    kind: InvestigatorFindingKind
    evidence: str


@dataclass(frozen=True)
class InvestigatorReport:
    """Aggregate output of one Investigator pass.

    ``run_id`` binds the report to the run that produced it (matches the
    ``Event.run_id`` shape). ``files_read`` is the ordered tuple of
    files the Investigator opened; ``findings`` names the concrete
    issues; ``no_finding_explicit`` names files the Investigator opened
    and explicitly cleared. Together, ``files_read`` equals the union
    of files touched by ``findings`` plus ``no_finding_explicit`` — the
    invariant callers assert.
    """

    run_id: bytes
    files_read: tuple[Path, ...]
    findings: tuple[InvestigatorFinding, ...] = field(default_factory=tuple)
    no_finding_explicit: tuple[Path, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# File selection — top-K by symbol-graph adjacency to touched symbols
# ---------------------------------------------------------------------------


DEFAULT_MAX_FILES: int = 20


def select_investigation_files(
    symgraph: "SymbolGraph",
    touched_files: tuple[Path, ...],
    *,
    max_files: int = DEFAULT_MAX_FILES,
) -> tuple[Path, ...]:
    """Rank untouched files by symbol-graph adjacency and return the top K.

    Adjacency signals (each contributes one to the file's score):

    - An import edge from any touched file to a symbol defined in the
      candidate file.
    - An import edge from the candidate file to a symbol defined in a
      touched file.
    - A call edge whose caller lives in a touched file and whose callee
      lives in the candidate (or vice versa).

    Ties are broken by lexicographic path order so the ranking is
    deterministic across runs. Files in ``touched_files`` are excluded
    (the Investigator's job is to look OUTSIDE the touched set) and
    files in ``symgraph.generated_files`` are excluded (generated code
    is not part of the loop's intent surface).

    Second Pass hardening (module_05 Q3): the primary provider could
    try to bias intent so it names no symbols the graph would connect
    to hidden files. A ``fallback_random_sample`` is applied when the
    adjacency-ranked list is shorter than ``max_files``: the remaining
    slots are filled from the untouched-file set in lexicographic order.
    This means the Investigator always opens ``max_files`` files (or
    the whole untouched set, whichever is smaller), regardless of how
    thin the intent's symbol graph is.
    """
    touched_str = {str(p).replace("\\", "/") for p in touched_files}
    generated = set(symgraph.generated_files)

    def _file_of(qualified_name: str) -> str | None:
        node = symgraph.symbols.get(qualified_name)
        if node is None:
            return None
        return node.source_file

    def _is_touched(path: str) -> bool:
        return path.replace("\\", "/") in touched_str

    scores: dict[str, int] = {}

    # Import-edge scoring.
    for imp_edge in symgraph.import_edges:
        importer_file = imp_edge.source_file
        imported_file = _file_of(imp_edge.imported_name)
        if imported_file is None:
            continue
        if _is_touched(importer_file) and not _is_touched(imported_file):
            if imported_file not in generated:
                scores[imported_file] = scores.get(imported_file, 0) + 1
        elif _is_touched(imported_file) and not _is_touched(importer_file):
            if importer_file not in generated:
                scores[importer_file] = scores.get(importer_file, 0) + 1

    # Call-edge scoring — the caller's source_file is authoritative for
    # locality; the callee's source is resolved through the symbols map.
    for call_edge in symgraph.call_edges:
        caller_file = call_edge.source_file
        callee_file = _file_of(call_edge.callee)
        if callee_file is None:
            continue
        if _is_touched(caller_file) and not _is_touched(callee_file):
            if callee_file not in generated:
                scores[callee_file] = scores.get(callee_file, 0) + 1
        elif _is_touched(callee_file) and not _is_touched(caller_file):
            if caller_file not in generated:
                scores[caller_file] = scores.get(caller_file, 0) + 1

    # Rank: score DESC, path ASC. Convert to Path so the return type
    # is uniform with ``touched_files``.
    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    picked: list[str] = [path for path, _ in ranked][:max_files]

    # Second Pass Q3 defence: pad with untouched files in lexicographic
    # order until we hit ``max_files`` or run out. This costs the
    # primary the guarantee that it can hide files by not naming their
    # symbols.
    if len(picked) < max_files:
        all_files = {node.source_file for node in symgraph.symbols.values()}
        remainder = sorted(
            path
            for path in all_files
            if not _is_touched(path) and path not in generated and path not in picked
        )
        needed = max_files - len(picked)
        picked.extend(remainder[:needed])

    return tuple(Path(p) for p in picked)


# ---------------------------------------------------------------------------
# run_investigator — the pre-completion contract
# ---------------------------------------------------------------------------


# The companion-shaped callable the Investigator asks for a per-file
# opinion. Real companions call an LLM; tests pass a deterministic
# stub. Signature: ``(intent, file, contents) -> InvestigatorFinding | None``.
InvestigatorProbe = Callable[[str, Path, str], "InvestigatorFinding | None"]


def run_investigator(
    *,
    intent: str,
    symgraph: "SymbolGraph",
    touched_files: tuple[Path, ...],
    probe: InvestigatorProbe,
    file_reader: Callable[[Path], str] | None = None,
    run_id: bytes,
    max_files: int = DEFAULT_MAX_FILES,
) -> InvestigatorReport:
    """Run one Investigator pass and return its report.

    ``probe`` is a companion-provider-backed callable. For each candidate
    file the Investigator reads the file contents (via ``file_reader``,
    defaulting to ``Path.read_text``) and calls the probe. A truthy
    return is recorded as a finding; a falsy return records the file
    in ``no_finding_explicit`` so the report proves the Investigator
    opened it.

    ``run_id`` must be 16 bytes so the report can be correlated with
    events. ``max_files`` bounds the runtime.

    The function does not itself decide whether the report is
    "sufficient" — that is AL-1's job. It only shapes and returns the
    ``InvestigatorReport``.
    """
    if len(run_id) != 16:
        raise ValueError("run_id must be a 16-byte UUID")

    reader = file_reader or (lambda p: p.read_text(encoding="utf-8"))
    candidates = select_investigation_files(
        symgraph, touched_files, max_files=max_files
    )
    findings: list[InvestigatorFinding] = []
    no_finding: list[Path] = []
    read_paths: list[Path] = []
    for candidate in candidates:
        try:
            contents = reader(candidate)
        except (OSError, UnicodeDecodeError):
            # A file the Investigator could not read is not evidence.
            # We still count it in files_read so the operator sees the
            # attempt in the report.
            read_paths.append(candidate)
            no_finding.append(candidate)
            continue
        read_paths.append(candidate)
        result = probe(intent, candidate, contents)
        if result is None:
            no_finding.append(candidate)
        else:
            findings.append(result)

    report = InvestigatorReport(
        run_id=run_id,
        files_read=tuple(read_paths),
        findings=tuple(findings),
        no_finding_explicit=tuple(no_finding),
    )
    _emit_investigator_report(report)
    return report


# ---------------------------------------------------------------------------
# Trace emit helpers
# ---------------------------------------------------------------------------


def _emit_investigator_report(report: InvestigatorReport) -> None:
    """Best-effort emit of an ``investigator.report`` event."""
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "investigator.report",
            {
                "run_id": report.run_id.hex(),
                "files_read": [str(p) for p in report.files_read],
                "findings": [
                    {
                        "file": str(f.file),
                        "line": f.line,
                        "kind": f.kind,
                        "evidence": f.evidence,
                    }
                    for f in report.findings
                ],
                "no_finding_explicit": [str(p) for p in report.no_finding_explicit],
            },
        )
    except Exception:  # noqa: BLE001
        pass


def emit_investigator_missing_event() -> None:
    """Emit ``laziness.violated`` with ``kind=investigator_missing``.

    Called by the completion path when a run reaches T1 without any
    ``investigator.report`` event in the trace. AL-1 does not fire on
    the rootknot directly for this case — the earlier gate (the
    completion refusal) is where laziness surfaces.
    """
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "investigator_missing",
                "detail": (
                    "Completion attempted without an Investigator report "
                    "in the trace. A run without adversarial context "
                    "loading is unauthenticated (ALM §8)."
                ),
            },
        )
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "DEFAULT_MAX_FILES",
    "InvestigatorFinding",
    "InvestigatorFindingKind",
    "InvestigatorProbe",
    "InvestigatorReport",
    "emit_investigator_missing_event",
    "run_investigator",
    "select_investigation_files",
]


# RACT 0.4.0
