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
    enforce_g2,
    enforce_g3,
    enforce_g4,
)

__all__ = [
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
    "Mutant",
    "MutantSource",
    "MutationReport",
    "Patch",
    "PatchDiffGateOutcome",
    "PatchDifferentiationReport",
    "RetrievalIndex",
    "TestRunner",
    "check_leakage",
    "check_visible_and_held_out",
    "compose_held_out",
    "enforce_g2",
    "enforce_g3",
    "enforce_g4",
    "filter_equivalent",
    "generate_differentiators",
    "null_patch",
    "run_coverage_delta",
    "run_mutation",
    "run_patchdiff",
    "seal_held_out",
    "shuffle_patch",
    "unseal_held_out",
    "write_coverage_delta_snapshot",
    "write_dual_suite_snapshot",
    "write_mutation_snapshot",
    "write_patchdiff_snapshot",
]


# RACT 0.4.0
