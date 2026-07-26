"""RACT core primitives."""

from ract.core.assumption_registry import AssumptionRegistry, bind_assumption
from ract.core.compile import CompilerInputs, IntentCompiler
from ract.core.gates import evaluate_invocation
from ract.core.predicate import (
    AcceptancePredicate,
    AcceptanceSuite,
    PredicateResult,
)

__all__ = [
    "AcceptancePredicate",
    "AcceptanceSuite",
    "AssumptionRegistry",
    "CompilerInputs",
    "IntentCompiler",
    "PredicateResult",
    "bind_assumption",
    "evaluate_invocation",
]

# Concrete reference so static reachability tooling sees the dependency.
_CORE_EXPORTS = (
    AssumptionRegistry,
    bind_assumption,
    IntentCompiler,
    CompilerInputs,
    AcceptancePredicate,
    AcceptanceSuite,
    PredicateResult,
    evaluate_invocation,
)

# RACT 0.4.0
