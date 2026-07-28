"""ALM Gate G3 — semantic patch differentiation + leakage fingerprint.

Two failure modes drive G3:

1. **Semantic no-op patches.** A patch passes the visible suite but is
   behaviorally indistinguishable from doing nothing. UTBoost measured
   over 5% of SWE-bench Verified instances as this shape. Solution:
   ask the companion for pytest-format differentiating tests that
   pass under one patch and fail under the other. Zero surviving
   differentiators against the null baseline means the patch is a
   semantic no-op. See ALM spec §3.3.

2. **Solution leakage.** A diff byte-matches a commit in the workspace
   git history or an entry in the retrieval index. SWE-Bench+ measured
   32.67% leakage on the base corpus. Solution: fingerprint each hunk
   with a rolling hash and search git history plus the retrieval index
   for matches; matches above a 5-line / 100-char floor count as
   leakage (lateral chain branch B).

Design rationale in ``docs/ADRs/ADR-0020-antilazy-patchdiff-and-
coverage-delta.md``.

Reference sources:

- PatchDiff (companion-generated differential tests). Public paper.
- UTBoost (5% no-op measurement). Public paper.
- SWE-Bench+ (32.67% leakage measurement). Public paper.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Bounds — lateral chain branches A and B
# ---------------------------------------------------------------------------


DEFAULT_MAX_DIFFERENTIATORS_PER_TRANSACTION: int = 30
"""Total differentiator budget per transaction (lateral chain branch A).

For a diff touching 12 functions with max_per_function=10 that is 120
companion tests, each requiring 3 runs. Per step. Cap the total at
30 with proportional allocation across touched functions so the cron
cadence stays viable.
"""

DEFAULT_MAX_PER_FUNCTION: int = 10
"""PatchDiff's stated per-function ceiling. Combined with the total
budget above, a diff touching a single function gets up to 10; a diff
touching 40 functions gets one each (deep-review flagged this as a
degeneration; see Flagged gaps).
"""

DEFAULT_FLAKINESS_RUNS: int = 3
"""Runs per candidate differentiator; drop the candidate if outcomes
disagree. Three-run filter is the PatchDiff spec default.
"""

MINIMUM_LEAKAGE_HUNK_LINES: int = 5
"""Lateral chain branch B: hunks below this line count are logged as
``leakage_below_floor`` and do not block commit. A one-line addition
of ``if not x: return None`` byte-matches many prior commits and would
otherwise trigger constant false positives.
"""

MINIMUM_LEAKAGE_HUNK_CHARS: int = 100
"""Companion floor to the line count. Whichever produces the larger
threshold wins (whichever is stricter). See branch B.
"""


BaselineKind = Literal["null", "shuffle", "commit_leak"]
"""What the differentiator generator ran against.

- ``"null"``: the empty diff (do-nothing baseline).
- ``"shuffle"``: a byte-shuffled variant of the claimed patch.
- ``"commit_leak"``: an earlier commit whose hunks byte-match the
  claimed patch (leakage baseline).
"""


# ---------------------------------------------------------------------------
# Patch + Hunk types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hunk:
    """One localized change inside a file.

    ``added_lines`` are the lines the patch introduces; ``removed_lines``
    are the lines it deletes. ``moved_lines`` are lines that appear in
    both ``added_lines`` and ``removed_lines`` at the file level — a
    pure reordering / relocation counts as movement rather than novel
    surface (lateral chain branch C; a refactor does not need coverage
    growth proportional to its diff size).
    """

    path: str
    added_lines: tuple[str, ...] = field(default_factory=tuple)
    removed_lines: tuple[str, ...] = field(default_factory=tuple)
    start_line: int = 0

    def content_bytes(self) -> bytes:
        """Return the canonical byte-form of this hunk for fingerprinting.

        Only additions inform the hash; removals do not fingerprint a
        leakage match (a delete-only hunk is not "the model shipped
        text it saw elsewhere"). Newlines are joined with ``\\n`` so
        fingerprints are stable across platforms.
        """
        return "\n".join(self.added_lines).encode("utf-8")

    def line_count(self) -> int:
        """Number of added lines in the hunk."""
        return len(self.added_lines)

    def char_count(self) -> int:
        """Number of characters in the added-lines payload."""
        return sum(len(ln) for ln in self.added_lines)


@dataclass(frozen=True)
class Patch:
    """A claimed patch — the model's contribution the gates evaluate.

    ``touched_files`` is derived from the hunks; ``digest`` is the
    stable identifier for report cross-reference.
    """

    hunks: tuple[Hunk, ...]

    @property
    def touched_files(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for h in self.hunks:
            seen.setdefault(h.path, None)
        return tuple(seen.keys())

    def digest(self) -> str:
        """SHA-256 of the concatenated hunk payloads. Hex form."""
        h = hashlib.sha256()
        for hunk in self.hunks:
            h.update(hunk.path.encode("utf-8"))
            h.update(b"\0")
            h.update(hunk.content_bytes())
            h.update(b"\0")
        return h.hexdigest()

    def added_line_count(self) -> int:
        """Total added-line count across all hunks."""
        return sum(h.line_count() for h in self.hunks)

    def touched_functions(self) -> tuple[str, ...]:
        """Return the set of ``def <name>`` symbols touched by any hunk.

        Approximation: parse ``def <name>`` from added lines. Real
        function-boundary detection belongs in a Rust/tree-sitter pass
        (ALM module_03 covers the symbol graph). Here we need only the
        cardinality for proportional-allocation budgeting.
        """
        symbols: dict[str, None] = {}
        pat = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
        for hunk in self.hunks:
            for line in hunk.added_lines:
                m = pat.match(line)
                if m:
                    symbols.setdefault(m.group(1), None)
        return tuple(symbols.keys())


def null_patch() -> Patch:
    """Return the empty patch — the null baseline for G3."""
    return Patch(hunks=())


def shuffle_patch(patch: Patch, *, seed: int = 0xB2) -> Patch:
    """Return a byte-shuffled variant of ``patch``.

    Deterministic per ``seed`` so the differentiator generator can
    reproduce the baseline. Character-level shuffle per hunk; the
    variant preserves length but destroys structure.
    """
    import random as _random

    rng = _random.Random(seed)
    new_hunks: list[Hunk] = []
    for hunk in patch.hunks:
        raw = "\n".join(hunk.added_lines)
        buf = list(raw)
        rng.shuffle(buf)
        shuffled = "".join(buf).split("\n")
        new_hunks.append(
            Hunk(
                path=hunk.path,
                added_lines=tuple(shuffled),
                removed_lines=hunk.removed_lines,
                start_line=hunk.start_line,
            )
        )
    return Patch(hunks=tuple(new_hunks))


# ---------------------------------------------------------------------------
# Generated differentiator tests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeneratedTest:
    """One companion-generated pytest snippet used to distinguish patches.

    ``source`` is the pytest-format text the companion returned;
    ``target_function`` names which touched function the test targets
    (so the proportional-allocation accounting is auditable).
    """

    id: str
    source: str
    target_function: str


# ---------------------------------------------------------------------------
# Protocols — DifferentiatorGenerator, TestRunner, RetrievalIndex
# ---------------------------------------------------------------------------


@runtime_checkable
class DifferentiatorGenerator(Protocol):
    """Companion-shaped verb for producing pytest-format differentiators.

    Adapters may wrap a substrate ``Provider`` and translate the
    ``generate`` call into a specific companion dispatch. Tests inject
    deterministic direct implementations.
    """

    def generate(
        self,
        patch: Patch,
        baseline: Patch,
        target_function: str,
        max_tests: int,
    ) -> tuple[GeneratedTest, ...]:
        """Return up to ``max_tests`` differentiators for ``target_function``.

        The companion is asked for tests that pass under ``patch`` and
        fail under ``baseline`` (or vice versa) — either polarity
        distinguishes the two.
        """
        ...  # pragma: no cover — protocol


@runtime_checkable
class TestRunner(Protocol):
    """Runs a generated test against a patch; returns pass/fail.

    The production path spins a scratch worktree and runs pytest under
    the touched files. Tests inject a synthetic runner keyed by
    ``(test_id, patch_digest)`` so the flakiness filter is testable
    without a live pytest.
    """

    def run(self, test: GeneratedTest, patch: Patch) -> bool:
        """Return True iff the test passes under ``patch``."""
        ...  # pragma: no cover — protocol


@runtime_checkable
class RetrievalIndex(Protocol):
    """Lookup structure the leakage check queries alongside git history.

    Substrate ships a retrieval index for some workspaces; others do
    not carry one (lateral chain branch E). When absent the leakage
    check falls back to git-history-only and marks the report
    ``retrieval_index_absent=True``.
    """

    def contains_hunk(self, hunk: Hunk) -> tuple[str, ...]:
        """Return refs where the index reports a byte-match for ``hunk``.

        Empty tuple means no match. A ref shape is opaque here — the
        production adapter returns retrieval-index document ids; a
        stub returns arbitrary string tags for tests.
        """
        ...  # pragma: no cover — protocol


# ---------------------------------------------------------------------------
# Leakage fingerprinting
# ---------------------------------------------------------------------------


def _hunk_fingerprint(hunk: Hunk) -> str:
    """Return the rolling-hash fingerprint of ``hunk``.

    SHA-256 over the newline-joined added lines. This is the coarse
    per-hunk fingerprint the leakage-scan queries first; the
    AST-normalized fingerprint below is the secondary check.
    """
    return hashlib.sha256(hunk.content_bytes()).hexdigest()


class _RenameNormalizer(ast.NodeTransformer):
    """Rewrite all ``Name`` and function/argument names to positional
    placeholders so a rename attack collides with the original.

    The transformer assigns ``_v0``, ``_v1``, ... in first-seen order.
    Function names, argument names, and class names are rewritten
    under the same registry so a shuffle-then-rename attack (per the
    Second Pass adversarial question 1) that preserves semantics via
    ``ast.NodeTransformer`` produces the same normalized AST as the
    original.
    """

    def __init__(self) -> None:
        super().__init__()
        self._names: dict[str, str] = {}

    def _rename(self, original: str) -> str:
        if original.startswith("_") and original.endswith("_"):
            # Preserve dunders and single-underscore idioms so the
            # normalization does not collapse ``__init__`` into a
            # positional slot (that would erase intent).
            return original
        if original not in self._names:
            self._names[original] = f"_v{len(self._names)}"
        return self._names[original]

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
        return ast.copy_location(
            ast.Name(id=self._rename(node.id), ctx=node.ctx), node
        )

    def visit_arg(self, node: ast.arg) -> ast.AST:  # noqa: N802
        return ast.copy_location(
            ast.arg(arg=self._rename(node.arg), annotation=node.annotation),
            node,
        )

    def visit_FunctionDef(  # noqa: N802
        self, node: ast.FunctionDef
    ) -> ast.AST:
        node = self.generic_visit(node)  # type: ignore[assignment]
        node.name = self._rename(node.name)  # type: ignore[attr-defined]
        return node

    def visit_AsyncFunctionDef(  # noqa: N802
        self, node: ast.AsyncFunctionDef
    ) -> ast.AST:
        node = self.generic_visit(node)  # type: ignore[assignment]
        node.name = self._rename(node.name)  # type: ignore[attr-defined]
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:  # noqa: N802
        node = self.generic_visit(node)  # type: ignore[assignment]
        node.name = self._rename(node.name)  # type: ignore[attr-defined]
        return node


def _ast_normalized_fingerprint(hunk: Hunk) -> str | None:
    """Return the AST-normalized fingerprint of a Python hunk, or None.

    Second Pass finding 1 (external reviewer): the
    raw-byte fingerprint is defeated by an ``ast.NodeTransformer``
    rename that preserves semantics. The secondary check parses the
    added lines as a Python module, rewrites every name / arg /
    function-name / class-name to a positional placeholder, unparses,
    and hashes. A rename attack that preserves structure collides
    with the original hunk on this normalized fingerprint.

    Returns ``None`` when the hunk is not parseable Python (either
    non-Python source or a code fragment). Non-Python paths fall
    through to the raw fingerprint alone; tree-sitter for Rust /
    TypeScript is v0.5 backlog.
    """
    if not hunk.path.endswith(".py"):
        return None
    source = "\n".join(hunk.added_lines)
    if not source.strip():
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    normalized = _RenameNormalizer().visit(tree)
    ast.fix_missing_locations(normalized)
    try:
        payload = ast.unparse(normalized)
    except AttributeError:  # pragma: no cover — 3.9 fallback
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hunk_qualifies_for_leakage(hunk: Hunk) -> bool:
    """Return True iff the hunk clears the size floor (branch B)."""
    return (
        hunk.line_count() >= MINIMUM_LEAKAGE_HUNK_LINES
        and hunk.char_count() >= MINIMUM_LEAKAGE_HUNK_CHARS
    )


def _search_git_history(
    hunk: Hunk, workspace_root: Path
) -> tuple[str, ...]:
    """Return git refs where ``hunk``'s added-line block matches.

    Two scans. The primary scan uses the first non-empty added line
    as the raw anchor for ``git log --all -S``. The secondary scan
    (Second Pass finding 1) looks for the AST-normalized signature
    via the ``ract.antilazy.leakage:<sig>`` marker convention on
    commit messages so a rename attack against a workspace whose
    leakage worker stamped normalized signatures is caught. Non-
    Python hunks skip the secondary scan.

    When git is not available or the workspace is not a repo, both
    scans return empty and the caller layers on
    ``retrieval_index_absent`` bookkeeping.
    """
    if not hunk.added_lines:
        return ()
    if not workspace_root.exists():
        return ()
    matches: list[str] = []
    # Primary scan: raw-byte anchor.
    anchor = ""
    for line in hunk.added_lines:
        candidate = line.strip()
        if candidate:
            anchor = candidate
            break
    if anchor:
        matches.extend(
            _git_log_S(anchor, hunk.path, workspace_root, cap=25)
        )
    # Secondary scan (Second Pass finding 1): AST-normalized signature
    # for Python hunks. A full tree-normalized scan across every
    # historical file is v0.5 work; the ``--grep`` scan here catches
    # workspaces whose leakage worker stamps the marker into commit
    # messages when a normalized-form leak is detected.
    normalized_fp = _ast_normalized_fingerprint(hunk)
    if normalized_fp is not None:
        marker = f"ract.antilazy.leakage:{normalized_fp}"
        matches.extend(_git_log_grep(marker, workspace_root, cap=25))
    # De-dupe while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in matches:
        if ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    return tuple(ordered)


def _git_log_S(
    anchor: str, path: str, workspace_root: Path, *, cap: int
) -> list[str]:
    """Wrapper around ``git log --all -S <anchor> -- <path>``."""
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(workspace_root),
                "log",
                "--all",
                "--format=%H",
                "-S",
                anchor,
                "--",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    hits = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    return hits[:cap]


def _git_log_grep(
    pattern: str, workspace_root: Path, *, cap: int
) -> list[str]:
    """Wrapper around ``git log --all --grep=<pattern>`` for the leakage
    marker convention.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(workspace_root),
                "log",
                "--all",
                "--format=%H",
                "--grep",
                pattern,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    hits = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    return hits[:cap]


def check_leakage(
    patch: Patch,
    workspace_root: Path,
    retrieval_index: RetrievalIndex | None = None,
) -> tuple[tuple[str, ...], bool]:
    """Return ``(leakage_matches, retrieval_index_absent)``.

    ``leakage_matches`` is the tuple of refs (git shas or retrieval-
    index document ids) that byte-match at least one qualifying hunk
    of ``patch``. Hunks below the size floor are excluded — they land
    in the report as ``leakage_below_floor`` counts through the
    orchestrator, not here.

    ``retrieval_index_absent`` is True when no ``retrieval_index``
    was supplied. The report reader uses the flag to see what evidence
    the leakage scan actually consulted.
    """
    matches: list[str] = []
    for hunk in patch.hunks:
        if not _hunk_qualifies_for_leakage(hunk):
            continue
        for ref in _search_git_history(hunk, workspace_root):
            matches.append(ref)
        if retrieval_index is not None:
            for ref in retrieval_index.contains_hunk(hunk):
                matches.append(ref)
            # Second Pass finding 1: query the retrieval index a
            # second time with the AST-normalized signature so an
            # index adapter that stores documents under normalized-
            # form keys catches a rename attack.
            normalized_fp = _ast_normalized_fingerprint(hunk)
            if normalized_fp is not None:
                synthetic = Hunk(
                    path=hunk.path,
                    added_lines=(
                        f"# ract.antilazy.leakage:{normalized_fp}",
                    ),
                    removed_lines=hunk.removed_lines,
                    start_line=hunk.start_line,
                )
                for ref in retrieval_index.contains_hunk(synthetic):
                    matches.append(ref)
    # De-dupe while preserving first-seen order.
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in matches:
        if ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    return tuple(ordered), retrieval_index is None


# ---------------------------------------------------------------------------
# Differentiator generation with proportional allocation and flakiness filter
# ---------------------------------------------------------------------------


def _proportional_budget(
    functions: tuple[str, ...],
    total_budget: int,
    per_function_cap: int,
) -> dict[str, int]:
    """Allocate ``total_budget`` across ``functions``, capped per function.

    Second Pass finding 3 (external reviewer): the
    prior implementation gave 0 differentiators to any function past
    ``total_budget`` in wide-refactor scenarios, contradicting its own
    docstring. The revised rule guarantees a minimum of 1
    differentiator per function; when the number of touched functions
    exceeds ``total_budget`` the actual dispatch count exceeds the
    stated cap in exchange for measurement coverage. That tradeoff is
    the honest one — the alternative (silent zero) is theatre.

    Allocation shape:

    - Every function gets ``floor(total_budget / n)`` (with a floor of
      1) up to ``per_function_cap``.
    - Any remainder is distributed round-robin one at a time until
      exhausted.
    - When ``n > total_budget`` the sum of allocations equals ``n``
      (one per function); callers that need a hard cap should assert
      on ``sum(allocation.values()) <= total_budget`` before
      dispatch and refuse the transaction with a specific error.
    """
    if not functions:
        return {}
    if total_budget <= 0:
        return {fn: 0 for fn in functions}
    n = len(functions)
    base = max(1, total_budget // n)
    allocation: dict[str, int] = {fn: min(per_function_cap, base) for fn in functions}
    # Distribute remainder — total may already equal or exceed budget
    # when n > total_budget (min-1 floor).
    consumed = sum(allocation.values())
    remaining = total_budget - consumed
    if remaining > 0:
        i = 0
        while remaining > 0 and i < len(functions) * per_function_cap:
            fn = functions[i % len(functions)]
            if allocation[fn] < per_function_cap:
                allocation[fn] += 1
                remaining -= 1
            i += 1
    return allocation


def _survives_flakiness(
    test: GeneratedTest,
    patch: Patch,
    runner: TestRunner,
    runs: int = DEFAULT_FLAKINESS_RUNS,
) -> bool:
    """Return True iff ``test`` returns the same verdict across ``runs`` runs.

    A test whose outcome varies across runs is flaky — the differentiator
    signal it produces is noise, not a semantic distinction. Filter it
    out before it can influence the report.
    """
    if runs <= 1:
        return True
    outcomes: list[bool] = []
    for _ in range(runs):
        try:
            outcomes.append(bool(runner.run(test, patch)))
        except Exception:  # noqa: BLE001 — a raising runner is a failure
            outcomes.append(False)
    return all(o == outcomes[0] for o in outcomes)


def generate_differentiators(
    patch: Patch,
    baseline: Patch,
    generator: DifferentiatorGenerator,
    runner: TestRunner,
    *,
    total_budget: int = DEFAULT_MAX_DIFFERENTIATORS_PER_TRANSACTION,
    per_function_cap: int = DEFAULT_MAX_PER_FUNCTION,
    flakiness_runs: int = DEFAULT_FLAKINESS_RUNS,
) -> tuple[GeneratedTest, ...]:
    """Return differentiators that distinguish ``patch`` from ``baseline``.

    Allocates ``total_budget`` proportionally across
    ``patch.touched_functions()``; asks the ``generator`` for up to
    the allocated count per function; filters each candidate through
    a three-run flakiness check on the ``runner`` (dropping ones whose
    verdicts disagree); keeps only those whose verdict actually
    differs between ``patch`` and ``baseline``.
    """
    functions = patch.touched_functions()
    if not functions:
        # A diff with no ``def`` symbols (e.g. a pure config edit) has
        # nothing to differentiate at the function level; return empty
        # so the orchestrator falls back to the leakage signal alone.
        return ()
    allocation = _proportional_budget(
        functions, total_budget, per_function_cap
    )
    kept: list[GeneratedTest] = []
    for fn, budget in allocation.items():
        if budget <= 0:
            continue
        candidates = generator.generate(patch, baseline, fn, budget)
        for cand in candidates:
            if not _survives_flakiness(cand, patch, runner, flakiness_runs):
                continue
            # Only tests whose verdict differs between patch and
            # baseline actually distinguish them.
            try:
                patch_verdict = bool(runner.run(cand, patch))
                baseline_verdict = bool(runner.run(cand, baseline))
            except Exception:  # noqa: BLE001
                continue
            if patch_verdict != baseline_verdict:
                kept.append(cand)
    return tuple(kept)


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PatchDifferentiationReport:
    """Aggregate G3 result — no-op detection + leakage evidence."""

    patch_digest: str
    baseline_kind: BaselineKind
    generated_tests: int
    tests_that_distinguish: int
    is_semantic_noop: bool
    leakage_matches: tuple[str, ...] = field(default_factory=tuple)
    leakage_below_floor: int = 0
    retrieval_index_absent: bool = False

    def to_canonical(self) -> dict[str, object]:
        return {
            "patch_digest": self.patch_digest,
            "baseline_kind": self.baseline_kind,
            "generated_tests": self.generated_tests,
            "tests_that_distinguish": self.tests_that_distinguish,
            "is_semantic_noop": self.is_semantic_noop,
            "leakage_matches": list(self.leakage_matches),
            "leakage_below_floor": self.leakage_below_floor,
            "retrieval_index_absent": self.retrieval_index_absent,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_patchdiff(
    patch: Patch,
    workspace_root: Path,
    *,
    generator: DifferentiatorGenerator,
    runner: TestRunner,
    baseline: Patch | None = None,
    baseline_kind: BaselineKind = "null",
    retrieval_index: RetrievalIndex | None = None,
    total_budget: int = DEFAULT_MAX_DIFFERENTIATORS_PER_TRANSACTION,
    per_function_cap: int = DEFAULT_MAX_PER_FUNCTION,
    flakiness_runs: int = DEFAULT_FLAKINESS_RUNS,
) -> PatchDifferentiationReport:
    """Return the ``PatchDifferentiationReport`` for ``patch``.

    Ordering: (1) pick or accept the baseline; (2) generate + filter
    differentiators; (3) run the leakage check; (4) assemble the
    report.
    """
    if baseline is None:
        if baseline_kind == "shuffle":
            baseline = shuffle_patch(patch)
        else:
            baseline = null_patch()
            baseline_kind = "null"
    all_generated: list[GeneratedTest] = []
    if patch.touched_functions():
        # Instrumented generator: capture the raw generate() calls so
        # ``generated_tests`` reflects the actual companion output
        # even when the flakiness filter drops candidates.
        allocation = _proportional_budget(
            patch.touched_functions(), total_budget, per_function_cap
        )
        for fn, budget in allocation.items():
            if budget <= 0:
                continue
            all_generated.extend(generator.generate(patch, baseline, fn, budget))
        distinguishing = _filter_distinguishing(
            tuple(all_generated), patch, baseline, runner, flakiness_runs
        )
    else:
        distinguishing = ()
    leakage_matches, retrieval_absent = check_leakage(
        patch, workspace_root, retrieval_index
    )
    below_floor = sum(
        1 for h in patch.hunks if not _hunk_qualifies_for_leakage(h)
    )
    if leakage_matches:
        baseline_kind = "commit_leak"
    is_noop = (
        patch.touched_functions() != ()
        and len(distinguishing) == 0
    )
    return PatchDifferentiationReport(
        patch_digest=patch.digest(),
        baseline_kind=baseline_kind,
        generated_tests=len(all_generated),
        tests_that_distinguish=len(distinguishing),
        is_semantic_noop=is_noop,
        leakage_matches=leakage_matches,
        leakage_below_floor=below_floor,
        retrieval_index_absent=retrieval_absent,
    )


def _filter_distinguishing(
    candidates: tuple[GeneratedTest, ...],
    patch: Patch,
    baseline: Patch,
    runner: TestRunner,
    flakiness_runs: int,
) -> tuple[GeneratedTest, ...]:
    """Return the subset of ``candidates`` that survive flakiness and
    differ across ``patch`` vs ``baseline``.
    """
    kept: list[GeneratedTest] = []
    for cand in candidates:
        if not _survives_flakiness(cand, patch, runner, flakiness_runs):
            continue
        try:
            patch_verdict = bool(runner.run(cand, patch))
            baseline_verdict = bool(runner.run(cand, baseline))
        except Exception:  # noqa: BLE001
            continue
        if patch_verdict != baseline_verdict:
            kept.append(cand)
    return tuple(kept)


# ---------------------------------------------------------------------------
# On-disk snapshot writer for evals/runs/<run_id>/patchdiff.json
# ---------------------------------------------------------------------------


def write_patchdiff_snapshot(
    run_dir: Path, report: PatchDifferentiationReport
) -> Path:
    """Persist the report to ``<run_dir>/patchdiff.json`` and return the path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "patchdiff.json"
    path.write_text(
        json.dumps(report.to_canonical(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


# RACT 0.4.0
