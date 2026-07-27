"""Anti-Lazy Machine (ALM) package.

RACT v0.4.0 Anti-Lazy pipeline. Modules under this package add the ALM
gates on top of the substrate primitives (``core.predicate``,
``core.compile``, ``core.transaction``, ``security.keys``,
``providers.provider``, ``trace.sink``). The substrate does not import
from ``antilazy``; the ALM extends outward.

module_01 (this module) ships Gate G1 (held-out predicate enforcement)
and Gate G2 (mutation-kill threshold). See:

- ``docs/RACT_v0.4.0_ANTILAZY_SPEC.md`` §3.1 and §3.2 for the design.
- ``docs/ADRs/ADR-0019-antilazy-holdout-and-mutation-kill.md`` for the
  rejected alternatives.
- ``docs/ARCHITECTURE.md`` "Anti-Lazy Gate G1 and Gate G2" for the
  cross-link into the substrate architecture.
"""

from __future__ import annotations

from ract.antilazy.coverage import (
    CoverageDeltaReport,
    run_coverage_delta,
    write_coverage_delta_snapshot,
)
from ract.antilazy.holdout import (
    DualAcceptanceSuite,
    HoldoutComposer,
    HoldoutKind,
    check_visible_and_held_out,
    compose_held_out,
    seal_held_out,
    unseal_held_out,
    write_dual_suite_snapshot,
)
from ract.antilazy.mutation import (
    EquivalenceDetector,
    Mutant,
    MutantSource,
    MutationReport,
    filter_equivalent,
    run_mutation,
    write_mutation_snapshot,
)
from ract.antilazy.patchdiff import (
    DifferentiatorGenerator,
    GeneratedTest,
    Hunk,
    Patch,
    PatchDifferentiationReport,
    RetrievalIndex,
    TestRunner,
    check_leakage,
    generate_differentiators,
    null_patch,
    run_patchdiff,
    shuffle_patch,
    write_patchdiff_snapshot,
)
from ract.antilazy.pre_commit import (
    CoverageDeltaGateOutcome,
    GateOutcome,
    PatchDiffGateOutcome,
    TestIntegrityGateOutcome,
    UnderEditGateOutcome,
    enforce_g2,
    enforce_g3,
    enforce_g4,
    enforce_g5,
    enforce_g6,
)
from ract.antilazy.symgraph import (
    CallEdge,
    ImportEdge,
    SymbolGraph,
    SymbolNode,
    UnderEditReport,
    build_graph,
    compute_closure,
    load_graph,
    persist_graph,
    snapshot_digest_of,
    write_under_edit_snapshot,
)
from ract.antilazy.testintegrity import (
    TestIntegrityReport,
    TestIntegrityRule,
    TestIntegrityViolation,
    analyze_diff,
    analyze_diff_python,
    write_test_integrity_snapshot,
)

__all__ = [
    "CallEdge",
    "CoverageDeltaGateOutcome",
    "CoverageDeltaReport",
    "DifferentiatorGenerator",
    "DualAcceptanceSuite",
    "EquivalenceDetector",
    "GateOutcome",
    "GeneratedTest",
    "HoldoutComposer",
    "HoldoutKind",
    "Hunk",
    "ImportEdge",
    "Mutant",
    "MutantSource",
    "MutationReport",
    "Patch",
    "PatchDiffGateOutcome",
    "PatchDifferentiationReport",
    "RetrievalIndex",
    "SymbolGraph",
    "SymbolNode",
    "TestIntegrityGateOutcome",
    "TestIntegrityReport",
    "TestIntegrityRule",
    "TestIntegrityViolation",
    "TestRunner",
    "UnderEditGateOutcome",
    "UnderEditReport",
    "analyze_diff",
    "analyze_diff_python",
    "build_graph",
    "check_leakage",
    "check_visible_and_held_out",
    "compose_held_out",
    "compute_closure",
    "enforce_g2",
    "enforce_g3",
    "enforce_g4",
    "enforce_g5",
    "enforce_g6",
    "filter_equivalent",
    "generate_differentiators",
    "load_graph",
    "null_patch",
    "persist_graph",
    "run_coverage_delta",
    "run_mutation",
    "run_patchdiff",
    "seal_held_out",
    "shuffle_patch",
    "snapshot_digest_of",
    "unseal_held_out",
    "write_coverage_delta_snapshot",
    "write_dual_suite_snapshot",
    "write_mutation_snapshot",
    "write_patchdiff_snapshot",
    "write_test_integrity_snapshot",
    "write_under_edit_snapshot",
]


# RACT 0.4.0
