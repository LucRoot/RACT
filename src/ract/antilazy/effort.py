"""ALM Gate G8 — effort-versus-scope reconciliation.

ALM spec §3.8. Before the loop enters step one, ALM produces a
low-precision effort estimate from static heuristics — no model call,
so the primary provider cannot game the estimate through intent
framing. After the loop claims T1 completion, realized effort is
measured from the final diff and compared against the estimate; a
ratio below ``tau_effort`` (default 0.3) on any dimension triggers a
suspicion prompt to the primary provider and stops the loop from
terminating COMPLETE until the primary either enumerates skipped items
with justification or produces additional work.

Second Pass adversarial questions this module is written to answer:

- **Q2 (small-fix intents in a large codebase).** For a genuine
  one-line fix inside a thousand-file codebase, the estimator must
  produce a low expected number so the realized ratio stays near 1.0.
  The heuristic uses intent-keyword grep density AGAINST the
  workspace's filename set, so a small-fix intent whose keywords
  match a handful of files gets a low ``files_touched_expected``;
  it does not cry wolf on every small fix.

- **Q3 (intent-manipulation via keyword packing).** The keyword
  extractor drops keywords that appear in more than a configurable
  fraction of workspace filenames (default 0.5). A model that packs
  common keywords ("test", "config", "utils") sees them filtered as
  low-signal; only rare-in-workspace keywords contribute to the
  estimate. The extractor also caps the keyword count so a wall-of-
  text intent cannot amplify the estimate arbitrarily.

Lateral chain branch C (merged): a workspace with no git history or
three files falls back to a per-intent-keyword-density scalar and
marks the report ``estimate_source="fallback"``.

See ADR-0022 for rejected alternatives.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from ract.antilazy.symgraph import SymbolGraph

if TYPE_CHECKING:
    from ract.antilazy.patchdiff import Patch
    from ract.core.loop import WorkspaceSnapshot


EstimateSource = Literal["heuristic", "fallback"]
"""``heuristic`` — the full grep + symbol-fanout + git-history path.
``fallback`` — greenfield workspace, per-intent-keyword-density scalar
only (lateral chain branch C).
"""


DEFAULT_TAU_EFFORT: float = 0.3
"""ALM §3.8 default: a realized/expected ratio below 0.3 on any
dimension triggers the suspicion prompt.
"""


DEFAULT_KEYWORD_MAX: int = 12
"""Intent-keyword extractor cap. Prevents a wall-of-text intent from
amplifying the estimate arbitrarily (Second Pass Q3).
"""


DEFAULT_KEYWORD_MIN_LENGTH: int = 4
"""Filter out stopword-shaped tokens (``the``, ``a``, ``and``). Short
tokens rarely name a symbol; a real symbol reference has 4+ chars.
"""


DEFAULT_KEYWORD_MAX_FILENAME_FRACTION: float = 0.15
"""Second Pass fix (module_04 Second Pass, external reviewer Q3):
tightened from 0.5 to 0.15 so a keyword that appears in more than 15%
of workspace filenames is dropped as low-signal. The reviewer showed
that mid-frequency code tokens ("handler", "service", "runner") could
sit under a 0.5 cap and still amplify the estimate.
"""


_STOP_WORDS: frozenset[str] = frozenset(
    {
        # Common English stopwords.
        "and",
        "the",
        "for",
        "with",
        "into",
        "from",
        "that",
        "this",
        "then",
        "than",
        "when",
        "will",
        "have",
        "been",
        "were",
        "them",
        "they",
        "some",
        "just",
        "only",
        "does",
        "make",
        "made",
        "such",
        "each",
        "must",
        "your",
        # Second Pass fix (module_04 Second Pass, external reviewer Q3):
        # common code / directory tokens that satisfy min_length=4 but
        # carry near-zero signal about which parts of the workspace are
        # touched. The reviewer named these as the intent-manipulation
        # attack surface: an adversary can pack them without tripping
        # the length filter.
        "code",
        "file",
        "path",
        "line",
        "name",
        "type",
        "kind",
        "size",
        "list",
        "dict",
        "value",
        "keys",
        "item",
        "data",
        "info",
        "util",
        "utils",
        "core",
        "base",
        "impl",
        "func",
        "args",
        "kwargs",
        "self",
        "cls",
        "module",
        "package",
        "config",
        "settings",
        "options",
        "params",
        "helper",
        "helpers",
        "handler",
        "service",
        "manager",
        "runner",
        "worker",
        "engine",
        "tests",
        "test",
        "spec",
        "specs",
    }
)


# ---------------------------------------------------------------------------
# EffortEstimate + EffortActual + EffortReconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EffortEstimate:
    """Static-heuristic pre-loop effort estimate.

    Every field is an integer scalar; no model in the loop. Fields:

    - ``files_touched_expected``: grep density of intent keywords
      against workspace filenames, plus symbol-graph neighborhoods.
    - ``symbols_modified_expected``: symbol-graph fanout of matched
      entry points.
    - ``tests_added_or_updated_expected``: existing test-to-symbol
      ratio applied to ``symbols_modified_expected``.
    - ``lines_changed_expected``: per-symbol median-lines-modified
      statistic over the workspace's git history (last 30 commits
      touching similar symbols); defaults to a per-symbol constant
      when git history is absent.

    ``estimate_source`` records whether the full heuristic path or the
    greenfield fallback produced the estimate (branch C).
    """

    files_touched_expected: int
    symbols_modified_expected: int
    tests_added_or_updated_expected: int
    lines_changed_expected: int
    estimate_source: EstimateSource = "heuristic"
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def to_canonical(self) -> dict[str, object]:
        return {
            "files_touched_expected": self.files_touched_expected,
            "symbols_modified_expected": self.symbols_modified_expected,
            "tests_added_or_updated_expected": self.tests_added_or_updated_expected,
            "lines_changed_expected": self.lines_changed_expected,
            "estimate_source": self.estimate_source,
            "keywords": list(self.keywords),
        }


@dataclass(frozen=True)
class EffortActual:
    """Realized-effort measurement over the final diff."""

    files_touched_realized: int
    symbols_modified_realized: int
    tests_added_or_updated_realized: int
    lines_changed_realized: int

    def to_canonical(self) -> dict[str, object]:
        return {
            "files_touched_realized": self.files_touched_realized,
            "symbols_modified_realized": self.symbols_modified_realized,
            "tests_added_or_updated_realized": self.tests_added_or_updated_realized,
            "lines_changed_realized": self.lines_changed_realized,
        }


@dataclass(frozen=True)
class EffortReconciliation:
    """G8 output. ``anomalies`` names dimensions below ``tau_effort``.

    A non-empty ``anomalies`` tuple stops the loop from terminating
    COMPLETE until the primary provider either enumerates skipped
    items with justification or produces additional work that closes
    the anomaly.
    """

    estimate: EffortEstimate
    realized: EffortActual
    ratio: dict[str, float] = field(default_factory=dict)
    anomalies: tuple[str, ...] = field(default_factory=tuple)
    tau_effort: float = DEFAULT_TAU_EFFORT

    def to_canonical(self) -> dict[str, object]:
        return {
            "estimate": self.estimate.to_canonical(),
            "realized": self.realized.to_canonical(),
            "ratio": {k: round(v, 4) for k, v in self.ratio.items()},
            "anomalies": list(self.anomalies),
            "tau_effort": self.tau_effort,
        }


# ---------------------------------------------------------------------------
# Intent-keyword extractor — Second Pass Q3 guard
# ---------------------------------------------------------------------------


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


def _extract_keywords(
    intent: str,
    workspace: "WorkspaceSnapshot",
    *,
    max_keywords: int = DEFAULT_KEYWORD_MAX,
    min_length: int = DEFAULT_KEYWORD_MIN_LENGTH,
    max_filename_fraction: float = DEFAULT_KEYWORD_MAX_FILENAME_FRACTION,
) -> tuple[str, ...]:
    """Return the low-count, high-signal keywords from ``intent``.

    Filters:

    - Length ``>= min_length`` (drops articles / short prepositions).
    - Not in ``_STOP_WORDS`` (drops the common English tokens the
      length filter misses).
    - Does not appear in more than ``max_filename_fraction`` of
      workspace filenames (Second Pass Q3: a keyword that hits half
      the workspace is low-signal — the model may have packed it
      hoping to inflate the estimate).
    - The remainder is capped at ``max_keywords`` (Second Pass Q3:
      wall-of-text intents cannot amplify the estimate arbitrarily).

    Case-insensitive; the returned keywords are lowercase.
    """
    # Second Pass fix (module_04 Second Pass, external reviewer
    # Additional Defect #1): an empty workspace makes the hit-fraction
    # filter compute 0.0 for every token, so every token passes as
    # "high-signal" and the estimate can be inflated before the
    # greenfield fallback triggers. Return an empty keyword tuple so
    # the estimator sees zero-length signal and takes its fallback
    # path with only the tiny-workspace defaults.
    if not workspace.files:
        return ()
    tokens = _WORD_RE.findall(intent.lower())
    total_files = max(1, len(workspace.files))
    seen: dict[str, int] = {}
    for tok in tokens:
        if len(tok) < min_length:
            continue
        if tok in _STOP_WORDS:
            continue
        seen[tok] = seen.get(tok, 0) + 1
    # Filename hit-fraction filter.
    kept: list[tuple[str, int]] = []
    for tok, freq in seen.items():
        hits = 0
        for path in workspace.files:
            if tok in path.lower():
                hits += 1
        fraction = hits / total_files
        if fraction > max_filename_fraction:
            continue
        kept.append((tok, freq))
    # Rank by intent-frequency descending, then alphabetic — deterministic.
    kept.sort(key=lambda pair: (-pair[1], pair[0]))
    return tuple(tok for tok, _ in kept[:max_keywords])


# ---------------------------------------------------------------------------
# estimate_effort — the pre-loop heuristic
# ---------------------------------------------------------------------------


def estimate_effort(
    intent: str,
    workspace: "WorkspaceSnapshot",
    graph: SymbolGraph | None = None,
    *,
    tau_effort: float = DEFAULT_TAU_EFFORT,
    git_history_median_lines: int | None = None,
) -> EffortEstimate:
    """Return the ``EffortEstimate`` for ``intent`` on ``workspace``.

    Determinism: no random component, no wall-clock read. Two calls
    with the same ``(intent, workspace, graph)`` return identical
    output.

    The estimator uses:

    - Intent-keyword extraction (Second Pass Q3: high-frequency-in-
      workspace keywords are dropped as low-signal, and the count is
      capped).
    - Grep density of the kept keywords against workspace filenames
      to seed ``files_touched_expected``.
    - Symbol-graph fanout for matched entry points to add downstream
      symbols to ``symbols_modified_expected``.
    - Existing test-to-symbol ratio for
      ``tests_added_or_updated_expected``.
    - Per-symbol median-lines-modified statistic (from
      ``git_history_median_lines`` when provided) for
      ``lines_changed_expected``; when absent, a per-symbol constant.
    - Greenfield fallback (branch C): a workspace with less than 4
      files falls back to the keyword-density scalar and marks the
      source ``"fallback"``.
    """
    keywords = _extract_keywords(intent, workspace)
    file_count = len(workspace.files)

    # Greenfield fallback (lateral chain branch C).
    if file_count < 4:
        expected_files = max(1, min(file_count, len(keywords)))
        return EffortEstimate(
            files_touched_expected=expected_files,
            symbols_modified_expected=max(1, len(keywords)),
            tests_added_or_updated_expected=max(1, len(keywords) // 2),
            lines_changed_expected=max(3, len(keywords) * 3),
            estimate_source="fallback",
            keywords=keywords,
        )

    # 1) files_touched_expected via grep density.
    matched_files: set[str] = set()
    for path in workspace.files:
        low = path.lower()
        for kw in keywords:
            if kw in low:
                matched_files.add(path)
                break
    # Cap at half of the workspace so a wide keyword match cannot
    # blow past the realistic modification surface.
    files_touched_expected = max(
        1, min(len(matched_files), max(1, file_count // 2))
    )

    # 2) symbols_modified_expected via symbol-graph fanout of matched
    # entry points. The graph maps qualified names to nodes; a
    # keyword that matches the short name of a symbol seeds fanout.
    modified_symbols: set[str] = set()
    if graph is not None and graph.symbols:
        for qname in graph.symbols:
            short = qname.rsplit(".", 1)[-1].lower()
            for kw in keywords:
                if kw in short:
                    modified_symbols.add(qname)
                    break
        # Add downstream callers of the matched symbols (fanout of 1).
        callers_added: set[str] = set()
        for edge in graph.call_edges:
            if edge.callee.startswith("getattr:"):
                continue
            callee_short = edge.callee.rsplit(".", 1)[-1]
            for msym in modified_symbols:
                if msym.rsplit(".", 1)[-1] == callee_short:
                    callers_added.add(edge.caller)
                    break
        modified_symbols |= callers_added
    symbols_modified_expected = max(
        1,
        min(
            len(modified_symbols) if modified_symbols else files_touched_expected,
            # Cap so a wide-fanout symbol does not inflate the estimate
            # past a realistic modification scope.
            max(2, file_count),
        ),
    )

    # 3) tests_added_or_updated_expected via existing test-to-symbol ratio.
    test_file_count = sum(
        1
        for path in workspace.files
        if _looks_like_test_file(path)
    )
    if graph is not None and graph.symbols:
        symbol_count = max(1, len(graph.symbols))
        test_symbol_ratio = test_file_count / symbol_count
    elif file_count > 0:
        test_symbol_ratio = test_file_count / max(1, file_count)
    else:
        test_symbol_ratio = 0.1
    tests_expected_raw = symbols_modified_expected * test_symbol_ratio
    tests_added_or_updated_expected = max(1, int(round(tests_expected_raw)))

    # 4) lines_changed_expected via per-symbol median-lines statistic.
    if git_history_median_lines is not None and git_history_median_lines > 0:
        median_per_symbol = git_history_median_lines
    else:
        # Fallback constant when git history is unavailable — measured
        # median in the OSS Python corpus we surveyed is ~8 lines per
        # symbol touched. Small enough not to over-estimate small fixes
        # (Second Pass Q2), large enough that a real refactor above 30%
        # threshold requires more than a token change.
        median_per_symbol = 8
    lines_changed_expected = max(
        1, symbols_modified_expected * median_per_symbol
    )

    return EffortEstimate(
        files_touched_expected=files_touched_expected,
        symbols_modified_expected=symbols_modified_expected,
        tests_added_or_updated_expected=tests_added_or_updated_expected,
        lines_changed_expected=lines_changed_expected,
        estimate_source="heuristic",
        keywords=keywords,
    )


def _looks_like_test_file(path: str) -> bool:
    """Return True for common test-file shapes."""
    p = path.replace("\\", "/").lower()
    return (
        p.endswith("_test.py")
        or "/test_" in p
        or p.startswith("test_")
        or "/tests/" in p
        or p.startswith("tests/")
    )


# ---------------------------------------------------------------------------
# measure_actual_effort — post-loop measurement
# ---------------------------------------------------------------------------


def measure_actual_effort(
    final_diff: "Patch",
    graph: SymbolGraph | None = None,
) -> EffortActual:
    """Return an ``EffortActual`` measured from the final ``Patch``.

    Fields:

    - ``files_touched_realized``: ``len(final_diff.touched_files)``.
    - ``symbols_modified_realized``: the union of
      ``final_diff.touched_functions()`` and, when a graph is present,
      any qualified name whose short-name matches. When no graph is
      available, ``max(1, len(touched_functions))``.
    - ``tests_added_or_updated_realized``: count of hunks whose path
      looks like a test file (``_looks_like_test_file`` above).
    - ``lines_changed_realized``: ``final_diff.added_line_count()``.
    """
    touched_files = final_diff.touched_files
    touched_functions = final_diff.touched_functions()
    tests_added = sum(
        1
        for h in final_diff.hunks
        if _looks_like_test_file(h.path)
    )
    # Symbol union via graph short-name match.
    if graph is not None and graph.symbols and touched_functions:
        touched_short = {name for name in touched_functions}
        matched: set[str] = set()
        for qname in graph.symbols:
            short = qname.rsplit(".", 1)[-1]
            if short in touched_short:
                matched.add(qname)
        symbols_realized = max(len(matched), len(touched_functions))
    else:
        symbols_realized = max(0, len(touched_functions))
    return EffortActual(
        files_touched_realized=len(touched_files),
        symbols_modified_realized=symbols_realized,
        tests_added_or_updated_realized=tests_added,
        lines_changed_realized=final_diff.added_line_count(),
    )


# ---------------------------------------------------------------------------
# reconcile_effort — the ratio check
# ---------------------------------------------------------------------------


_DIMENSION_KEYS: tuple[str, ...] = (
    "files_touched",
    "symbols_modified",
    "tests_added_or_updated",
    "lines_changed",
)


def reconcile_effort(
    estimate: EffortEstimate,
    actual: EffortActual,
    tau_effort: float = DEFAULT_TAU_EFFORT,
) -> EffortReconciliation:
    """Return the ``EffortReconciliation`` for ``(estimate, actual)``.

    Ratio per dimension is ``realized / max(1, estimate)``; dimensions
    with ratio below ``tau_effort`` land in ``anomalies``.

    Second Pass Q2 (small-fix over-estimate): if the estimate is very
    small (<= 2 on a dimension) the ratio-based anomaly is suppressed
    on that dimension so a legitimate one-line fix does not trigger
    the suspicion prompt. The estimator's own small-fix path
    (keyword-density collapse) is the first line of defense; the
    ratio floor is the belt-and-braces.
    """
    ratio: dict[str, float] = {}
    anomalies: list[str] = []
    per_dim = (
        (
            "files_touched",
            estimate.files_touched_expected,
            actual.files_touched_realized,
        ),
        (
            "symbols_modified",
            estimate.symbols_modified_expected,
            actual.symbols_modified_realized,
        ),
        (
            "tests_added_or_updated",
            estimate.tests_added_or_updated_expected,
            actual.tests_added_or_updated_realized,
        ),
        (
            "lines_changed",
            estimate.lines_changed_expected,
            actual.lines_changed_realized,
        ),
    )
    for name, expected, realized in per_dim:
        expected_denom = max(1, expected)
        r = realized / expected_denom
        ratio[name] = r
        # Second Pass Q2 small-fix suppressor: expected <= 2 means the
        # estimator itself said "this is small" — do not fire.
        if expected <= 2:
            continue
        if r < tau_effort:
            anomalies.append(name)
    return EffortReconciliation(
        estimate=estimate,
        realized=actual,
        ratio=ratio,
        anomalies=tuple(anomalies),
        tau_effort=tau_effort,
    )


def suspicion_prompt_text(reconciliation: EffortReconciliation) -> str:
    """Return the primary-provider suspicion prompt (ALM §3.8).

    The prompt names each anomalous dimension and asks the primary to
    either enumerate what was skipped with justification or produce
    additional work that closes the anomaly. The loop does not
    terminate COMPLETE until the response resolves each anomaly.
    """
    if not reconciliation.anomalies:
        return ""
    lines: list[str] = []
    lines.append(
        "[EFFORT RECONCILIATION - your realized effort is well below "
        "what the codebase suggests this intent needs.]"
    )
    lines.append("")
    lines.append("Per-dimension comparison (realized / expected):")
    for name in reconciliation.anomalies:
        r = reconciliation.ratio.get(name, 0.0)
        exp = getattr(
            reconciliation.estimate, f"{name}_expected"
        )
        real = getattr(reconciliation.realized, f"{name}_realized")
        lines.append(
            f"- {name}: {real} realized vs {exp} expected "
            f"(ratio {r:.2f}, floor {reconciliation.tau_effort:.2f})"
        )
    lines.append("")
    lines.append(
        "Either enumerate the items you deliberately skipped with "
        "justification (per item: name what it is, why it is out of "
        "scope, and what would need to change for it to be in scope), "
        "or produce the additional work that closes the anomaly. "
        "The loop will not terminate COMPLETE until every anomaly is "
        "resolved."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Optional: median-lines statistic from a workspace's git history
# ---------------------------------------------------------------------------


def median_lines_from_history(commit_line_counts: list[int]) -> int:
    """Return the median line-count from a list of historical commit sizes.

    Kept as a pure helper the caller feeds ``estimate_effort`` — the
    estimator does not shell out. Returns 0 on an empty input so the
    estimator can detect the missing-history case and use its default.
    """
    if not commit_line_counts:
        return 0
    return max(1, int(statistics.median(commit_line_counts)))


__all__ = [
    "DEFAULT_KEYWORD_MAX",
    "DEFAULT_KEYWORD_MAX_FILENAME_FRACTION",
    "DEFAULT_KEYWORD_MIN_LENGTH",
    "DEFAULT_TAU_EFFORT",
    "EffortActual",
    "EffortEstimate",
    "EffortReconciliation",
    "EstimateSource",
    "estimate_effort",
    "measure_actual_effort",
    "median_lines_from_history",
    "reconcile_effort",
    "suspicion_prompt_text",
]


# RACT 0.4.0
