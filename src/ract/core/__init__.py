"""RACT core primitives."""

from ract.core.assumption_registry import AssumptionRegistry, bind_assumption
from ract.core.compile import CompilerInputs, IntentCompiler
from ract.core.gates import evaluate_invocation
from ract.core.predicate import (
    AcceptancePredicate,
    AcceptanceSuite,
    PredicateResult,
)
from ract.core.transaction import (
    ContainerRef,
    ResourceBudget,
    StepTransaction,
    TransactionOutcome,
    new_step_id,
    open_transaction,
)

__all__ = [
    "AcceptancePredicate",
    "AcceptanceSuite",
    "AssumptionRegistry",
    "CompilerInputs",
    "ContainerRef",
    "IntentCompiler",
    "PredicateResult",
    "ResourceBudget",
    "StepTransaction",
    "TransactionOutcome",
    "bind_assumption",
    "evaluate_invocation",
    "new_step_id",
    "open_transaction",
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
    ContainerRef,
    ResourceBudget,
    StepTransaction,
    TransactionOutcome,
    new_step_id,
    open_transaction,
)

# RACT 0.4.0
