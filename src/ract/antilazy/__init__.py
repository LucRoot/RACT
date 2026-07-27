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
from ract.antilazy.pre_commit import (
    GateOutcome,
    enforce_g2,
)

__all__ = [
    "DualAcceptanceSuite",
    "EquivalenceDetector",
    "GateOutcome",
    "HoldoutComposer",
    "HoldoutKind",
    "Mutant",
    "MutantSource",
    "MutationReport",
    "check_visible_and_held_out",
    "compose_held_out",
    "enforce_g2",
    "filter_equivalent",
    "run_mutation",
    "seal_held_out",
    "unseal_held_out",
    "write_dual_suite_snapshot",
    "write_mutation_snapshot",
]


# RACT 0.4.0
