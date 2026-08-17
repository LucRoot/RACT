"""ALM Gate G2 — mutation-kill threshold.

After the model claims completion and the transaction is about to
commit, mutation testing runs against the touched surface. Each mutant
is scored against the ``AcceptanceSuite`` that governs the run; a
mutant that the suite catches counts as "killed", a mutant that
survives is a piece of surface the tests do not cover, and a mutant
the ACH-style equivalence detector flags as semantically equivalent to
the original does not count against the kill rate. Below a
configurable threshold (default 0.7) the pre-commit gate rolls back
and emits ``laziness.violated`` with ``kind="mutation_kill_below_threshold"``.

See ``docs/RACT_v0.4.0_ANTILAZY_SPEC.md`` §3.2 and
``docs/ADRs/ADR-0019-antilazy-holdout-and-mutation-kill.md``.

Reference sources:

- ``mutmut`` public repo: ``https://github.com/boxed/mutmut``.
- Stryker (per-mutant test-set restriction): ``https://stryker-mutator.io/``.
- Meta ACH (LLM-based Equivalence Detector, 0.79 precision): public
  Meta engineering post.
"""

from __future__ import annotations

import ast
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Protocol, runtime_checkable

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot
    from ract.core.predicate import AcceptanceSuite


# ---------------------------------------------------------------------------
# Bounds — lateral chain branch B
# ---------------------------------------------------------------------------


DEFAULT_KILL_THRESHOLD: float = 0.7
"""Default kill-rate floor from ALM spec §3.2."""

DEFAULT_MUTANTS_PER_FILE_CAP: int = 200
"""Maximum mutants per touched file (lateral chain branch B).

Above this cap, ``run_mutation`` samples randomly under a fixed seed
so the cap does not create a non-deterministic false-negative surface.
"""

DEFAULT_PER_MUTANT_TIMEOUT_SECONDS: float = 10.0
"""Per-mutant wall-clock budget for kill evaluation.

A mutant that exceeds the budget lands under ``mutants_survived`` (not
``mutants_equivalent``), so the timeout cannot inflate the kill rate.
"""

DEFAULT_EQUIVALENCE_BATCH_SIZE: int = 10
"""Batch size for the equivalence detector (lateral chain branch C).

One dispatch per ``DEFAULT_EQUIVALENCE_BATCH_SIZE`` mutants; the
companion returns a JSON array of verdicts.
"""


# ---------------------------------------------------------------------------
# Mutant + report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mutant:
    """One mutation applied to a touched file.

    ``id`` is a stable string identifier (typically
    ``"<path>::<line>::<mutation_kind>::<n>"``) so a mutant listed in
    the report can be re-inspected across runs. ``payload`` is the
    mutated source; the mutation runner writes it into a scratch copy
    of the workspace before evaluating the suite.
    """

    id: str
    path: str
    line: int
    kind: str  # e.g. "operator_swap", "constant_bump", "conditional_flip"
    original: str
    payload: str


@dataclass(frozen=True)
class MutationReport:
    """Aggregate result of one G2 run against a touched surface."""

    touched_files: tuple[str, ...]
    mutants_total: int
    mutants_killed: int
    mutants_survived: tuple[str, ...]
    mutants_equivalent: tuple[str, ...]
    kill_rate: float
    threshold: float

    def passed(self) -> bool:
        """Return True when ``kill_rate >= threshold``."""
        return self.kill_rate >= self.threshold

    def to_canonical(self) -> dict[str, object]:
        """Return the on-disk shape for ``mutation.json``."""
        return {
            "touched_files": list(self.touched_files),
            "mutants_total": self.mutants_total,
            "mutants_killed": self.mutants_killed,
            "mutants_survived": list(self.mutants_survived),
            "mutants_equivalent": list(self.mutants_equivalent),
            "kill_rate": self.kill_rate,
            "threshold": self.threshold,
        }


# ---------------------------------------------------------------------------
# Sources & detectors
# ---------------------------------------------------------------------------


@runtime_checkable
class MutantSource(Protocol):
    """Produces mutants for a set of touched files.

    Kept as a protocol so ``mutmut`` (default production source) can be
    swapped for a synthetic source in unit tests without importing the
    ``mutmut`` runtime.
    """

    def generate(self, touched_files: tuple[str, ...]) -> tuple[Mutant, ...]:
        """Return the tuple of mutants generated for ``touched_files``."""
        ...  # pragma: no cover — protocol


@runtime_checkable
class KillEvaluator(Protocol):
    """Given a mutant, return whether the suite kills it.

    Tests inject synthetic evaluators; the production path wraps a
    scratch-worktree pytest run per mutant.
    """

    def kills(self, mutant: Mutant, suite: "AcceptanceSuite") -> bool:
        """Return True iff the suite fails on the mutated workspace."""
        ...  # pragma: no cover — protocol


@runtime_checkable
class EquivalenceDetector(Protocol):
    """Companion-backed detector for semantically equivalent mutants.

    The production adapter batches mutants into groups of
    ``DEFAULT_EQUIVALENCE_BATCH_SIZE`` and issues one companion
    dispatch per batch (lateral chain branch C). Tests inject a
    deterministic classifier.
    """

    def classify(self, mutants: Iterable[Mutant]) -> tuple[str, ...]:
        """Return the ids of mutants judged semantically equivalent."""
        ...  # pragma: no cover — protocol


# ---------------------------------------------------------------------------
# Simple AST-based synthetic source (used when mutmut is unavailable)
# ---------------------------------------------------------------------------


class AstArithmeticMutantSource:
    """Minimal built-in ``MutantSource`` that flips arithmetic operators.

    Not a substitute for ``mutmut`` in production — its purpose is to
    give ``run_mutation`` a deterministic default source so the ALM
    layer degrades gracefully on machines that do not have ``mutmut``
    installed. Only ``+``, ``-``, ``*``, ``/`` in ``ast.BinOp`` nodes
    are flipped.

    Substrate module_04 lateral chain branch A: keeping the fallback
    self-contained means the antilazy runtime does not fail hard when
    the dev dependency is missing on a fresh checkout.
    """

    #: Ordered swap map so mutation is deterministic and reversible.
    _SWAPS: dict[type[ast.operator], type[ast.operator]] = {
        ast.Add: ast.Sub,
        ast.Sub: ast.Add,
        ast.Mult: ast.Div,
        ast.Div: ast.Mult,
    }

    def __init__(
        self,
        workspace: "WorkspaceSnapshot | None" = None,
        *,
        cap_per_file: int = DEFAULT_MUTANTS_PER_FILE_CAP,
    ) -> None:
        self._workspace = workspace
        self._cap = max(1, int(cap_per_file))

    def generate(self, touched_files: tuple[str, ...]) -> tuple[Mutant, ...]:
        if self._workspace is None:
            return ()
        mutants: list[Mutant] = []
        for path in touched_files:
            source = self._workspace.files.get(path)
            if source is None:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            counter = 0
            for node in ast.walk(tree):
                if not isinstance(node, ast.BinOp):
                    continue
                op_type = type(node.op)
                swap = self._SWAPS.get(op_type)
                if swap is None:
                    continue
                if counter >= self._cap:
                    break
                new_op = swap()
                new_node = ast.BinOp(left=node.left, op=new_op, right=node.right)
                ast.copy_location(new_node, node)
                try:
                    payload = ast.unparse(new_node)
                except AttributeError:  # pragma: no cover — 3.9 fallback
                    payload = f"<mutation at line {node.lineno}>"
                original = ""
                try:
                    original = ast.unparse(node)
                except AttributeError:  # pragma: no cover — 3.9 fallback
                    original = f"<original at line {node.lineno}>"
                mutants.append(
                    Mutant(
                        id=f"{path}::{node.lineno}::binop_swap::{counter}",
                        path=path,
                        line=node.lineno,
                        kind="binop_swap",
                        original=original,
                        payload=payload,
                    )
                )
                counter += 1
        return tuple(mutants)


# ---------------------------------------------------------------------------
# Equivalence filter — batches into companion dispatches
# ---------------------------------------------------------------------------


def filter_equivalent(
    mutants: Iterable[Mutant],
    detector: EquivalenceDetector,
    *,
    batch_size: int = DEFAULT_EQUIVALENCE_BATCH_SIZE,
) -> tuple[str, ...]:
    """Return the ids of mutants ``detector`` marks equivalent.

    Batches the mutants into groups of ``batch_size`` so one companion
    dispatch covers up to that many mutants (lateral chain branch C).
    The detector is trusted to be idempotent per mutant; the returned
    tuple is the set of ids that ``detector.classify`` produced across
    every batch.
    """
    mutant_list = list(mutants)
    if not mutant_list:
        return ()
    equivalent: list[str] = []
    for start in range(0, len(mutant_list), max(1, batch_size)):
        batch = mutant_list[start : start + max(1, batch_size)]
        equivalent.extend(detector.classify(batch))
    # Preserve order; de-dup while keeping first-seen order.
    seen: set[str] = set()
    ordered: list[str] = []
    for mid in equivalent:
        if mid not in seen:
            seen.add(mid)
            ordered.append(mid)
    return tuple(ordered)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _sample_capped(
    mutants: tuple[Mutant, ...], cap: int, *, seed: int
) -> tuple[Mutant, ...]:
    """Return at most ``cap`` mutants, sampled deterministically per seed.

    Lateral chain branch B: the sampling seed is fixed so the false-
    negative surface the cap creates is reproducible across runs of
    the same workspace.
    """
    if len(mutants) <= cap:
        return mutants
    rng = random.Random(seed)
    return tuple(rng.sample(mutants, cap))


def run_mutation(
    touched_files: tuple[str, ...],
    suite: "AcceptanceSuite",
    *,
    source: MutantSource,
    evaluator: KillEvaluator,
    detector: EquivalenceDetector | None = None,
    threshold: float = DEFAULT_KILL_THRESHOLD,
    cap_per_file: int = DEFAULT_MUTANTS_PER_FILE_CAP,
    per_mutant_timeout_seconds: float = DEFAULT_PER_MUTANT_TIMEOUT_SECONDS,
    sample_seed: int = 0xC001,
) -> MutationReport:
    """Return the ``MutationReport`` for ``touched_files`` under ``suite``.

    Ordering: (1) generate mutants via ``source``; (2) cap per-file at
    ``cap_per_file`` with deterministic sampling; (3) for each mutant,
    evaluate whether ``suite`` kills it via ``evaluator.kills`` with a
    per-mutant timeout; (4) if a ``detector`` is provided, filter the
    surviving mutants through the equivalence detector; (5) compute
    ``kill_rate = killed / (total - equivalent)``.

    A mutant that exceeds ``per_mutant_timeout_seconds`` lands under
    ``mutants_survived`` (not ``mutants_equivalent``), so a hung
    evaluator does not inflate the kill rate (branch A of the Second
    Pass adversarial questions).
    """
    raw_mutants = source.generate(touched_files)
    # Cap per file with a deterministic sample.
    per_file: dict[str, list[Mutant]] = {}
    for mutant in raw_mutants:
        per_file.setdefault(mutant.path, []).append(mutant)
    capped: list[Mutant] = []
    for path in touched_files:
        pool = tuple(per_file.get(path, ()))
        capped.extend(_sample_capped(pool, cap_per_file, seed=sample_seed))
    mutants = tuple(capped)

    killed_ids: list[str] = []
    survived_ids: list[str] = []
    for mutant in mutants:
        started = time.monotonic()
        try:
            killed = bool(evaluator.kills(mutant, suite))
        except Exception:  # noqa: BLE001 — a raising evaluator is a survival
            killed = False
        elapsed = time.monotonic() - started
        if elapsed >= per_mutant_timeout_seconds:
            # Timeout — surface as survived so a hang cannot inflate
            # the kill rate. Never marked equivalent.
            survived_ids.append(mutant.id)
            continue
        if killed:
            killed_ids.append(mutant.id)
        else:
            survived_ids.append(mutant.id)

    equivalent_ids: tuple[str, ...] = ()
    if detector is not None and survived_ids:
        by_id = {m.id: m for m in mutants}
        survived_mutants = tuple(by_id[mid] for mid in survived_ids if mid in by_id)
        equivalent_ids = filter_equivalent(survived_mutants, detector)
    equivalent_set = set(equivalent_ids)
    # Remove equivalents from the survived pool so the report matches
    # the kill-rate denominator.
    net_survived = tuple(mid for mid in survived_ids if mid not in equivalent_set)
    net_total = len(mutants) - len(equivalent_set)
    kill_rate = (len(killed_ids) / net_total) if net_total > 0 else 1.0

    report = MutationReport(
        touched_files=tuple(touched_files),
        mutants_total=len(mutants),
        mutants_killed=len(killed_ids),
        mutants_survived=net_survived,
        mutants_equivalent=equivalent_ids,
        kill_rate=kill_rate,
        threshold=threshold,
    )
    # Trace: emit predicate.evaluated with kind="mutation" so a report
    # reader can see the G2 outcome on the same channel as substrate
    # predicate evaluations. Best-effort — a missing writer drops.
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "predicate.evaluated",
            {
                "kind": "mutation",
                "touched_files": list(report.touched_files),
                "mutants_total": report.mutants_total,
                "mutants_killed": report.mutants_killed,
                "mutants_survived_count": len(report.mutants_survived),
                "mutants_equivalent_count": len(report.mutants_equivalent),
                "kill_rate": report.kill_rate,
                "threshold": report.threshold,
                "ok": report.passed(),
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return report


# ---------------------------------------------------------------------------
# On-disk snapshot
# ---------------------------------------------------------------------------


def write_mutation_snapshot(run_dir: Path, report: MutationReport) -> Path:
    """Persist the report to ``<run_dir>/mutation.json`` and return the path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "mutation.json"
    path.write_text(
        json.dumps(report.to_canonical(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Optional ``mutmut`` adapter — imported lazily so absence is not fatal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MutmutSourceConfig:
    """Configuration bag for ``MutmutSource``.

    Kept minimal on purpose; deeper mutmut invocation shapes are the
    concern of a hardening pass, not the initial ship of G2.
    """

    cap_per_file: int = DEFAULT_MUTANTS_PER_FILE_CAP
    workspace_root: str = "."


class MutmutSource:
    """Lazy adapter over the ``mutmut`` Python library.

    Only imported when ``generate`` is called; a machine without
    ``mutmut`` gets a clear error instead of a hard import-time break.
    Not exercised in this module's unit tests — those inject
    ``AstArithmeticMutantSource`` or a synthetic source.
    """

    def __init__(self, config: MutmutSourceConfig | None = None) -> None:
        self._config = config or MutmutSourceConfig()

    def generate(
        self, touched_files: tuple[str, ...]
    ) -> tuple[Mutant, ...]:  # pragma: no cover — dev-optional path
        import importlib

        try:
            importlib.import_module("mutmut")
        except ImportError as exc:
            raise RuntimeError(
                "mutmut is not installed. Install the dev extras "
                "(pip install ract[dev]) or inject a different "
                "MutantSource. See ADR-0019."
            ) from exc
        # A production wiring of mutmut belongs in the hardening pass
        # for module_04. For now, this adapter exists so callers that
        # explicitly ask for MutmutSource get a clear error.
        raise NotImplementedError(
            "MutmutSource wiring lives in ALM module_04; use "
            "AstArithmeticMutantSource for the initial G2 ship."
        )


# RACT 0.4.0
