"""Function contracts package (v0.5.0 memory discipline, module_06).

Four verbs carry a change from user request through to a candidate
diff:

- :func:`~ract.memory.functions.intake.intake`
- :func:`~ract.memory.functions.research.research`
- :func:`~ract.memory.functions.plan.plan`
- :func:`~ract.memory.functions.edit.edit`

The remaining four verbs (verify / review / commit / document)
defer to v0.6 per master spec §Bounded scope; ADR-0036 records the
rationale.

Every function reads its budget from
:func:`ract.memory.budget_registry.get`, assembles context via the
:mod:`~ract.memory.functions.provider_adapter` composer + the
retrieve primitive from module_05, delegates the model call to a
:class:`MemoryFunctionProvider`, and returns a frozen output contract
from :mod:`~ract.memory.functions.contracts`.

Composition (module_07) reads the contracts to route between verbs;
SubstrateLoop (module_09) wires the function calls into
:class:`~ract.core.substrate.SubstrateStepSpec` instances.
"""

from __future__ import annotations

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.functions.contracts import (
    CandidateDiff,
    ChangePlan,
    CommitRef,
    HunkSummary,
    Invariant,
    InvariantKind,
    RequestType,
    ResearchBundle,
    RiskAssessment,
    RiskLevel,
    ScopeHints,
    SignatureRow,
    SymbolRef,
    SymbolWithRationale,
    TargetSymbol,
    VerificationCriterion,
    WorkOrder,
    from_json,
    to_json,
)
from ract.memory.functions.edit import (
    EDIT_FUNCTION_NAME,
    EDIT_PROMPT_VERSION,
    EditValidationReport,
    MAX_PARSE_RETRIES,
    edit,
)
from ract.memory.functions.errors import (
    BoundedContextError,
    EmptyResearchError,
    InfeasiblePlanError,
    InvalidSyntaxError,
    MemoryFunctionError,
    OversizedResearchError,
    ProviderContractError,
)
from ract.memory.functions.intake import (
    INTAKE_FUNCTION_NAME,
    INTAKE_PROMPT_VERSION,
    IntakeContext,
    intake,
)
from ract.memory.functions.plan import (
    MAX_MID_INVOCATION_RETRIEVES,
    MID_INVOCATION_RETRIEVE_BUDGET,
    PLAN_FUNCTION_NAME,
    PLAN_PROMPT_VERSION,
    plan,
)
from ract.memory.functions.prompts_loader import (
    PROMPTS_DIR,
    PromptCoverageError,
    PromptMissingError,
    assert_prompt_shipped,
    load_prompt,
    prompt_path,
    verify_prompt_coverage,
)
from ract.memory.functions.provider_adapter import (
    STATE_CONTEXT_CAP_FRACTION,
    MemoryFunctionProvider,
    assemble_prompt,
    refuse_over_ceiling,
    refuse_over_max,
    seat_prompt_section,
    seat_state_section,
)
from ract.memory.functions.research import (
    IndexBundle,
    RELEVANT_SYMBOLS_CAP,
    RESEARCH_FUNCTION_NAME,
    RESEARCH_PROMPT_VERSION,
    research,
)


__all__ = [
    "BoundedContextError",
    "CandidateDiff",
    "ChangePlan",
    "CommitRef",
    "EDIT_FUNCTION_NAME",
    "EDIT_PROMPT_VERSION",
    "EditValidationReport",
    "EmptyResearchError",
    "HunkSummary",
    "INTAKE_FUNCTION_NAME",
    "INTAKE_PROMPT_VERSION",
    "IndexBundle",
    "InfeasiblePlanError",
    "IntakeContext",
    "Invariant",
    "InvariantKind",
    "InvalidSyntaxError",
    "MAX_MID_INVOCATION_RETRIEVES",
    "MAX_PARSE_RETRIES",
    "MID_INVOCATION_RETRIEVE_BUDGET",
    "MemoryFunctionError",
    "MemoryFunctionProvider",
    "OversizedResearchError",
    "PLAN_FUNCTION_NAME",
    "PLAN_PROMPT_VERSION",
    "PROMPTS_DIR",
    "PromptCoverageError",
    "PromptMissingError",
    "ProviderContractError",
    "RELEVANT_SYMBOLS_CAP",
    "RESEARCH_FUNCTION_NAME",
    "RESEARCH_PROMPT_VERSION",
    "RequestType",
    "ResearchBundle",
    "RiskAssessment",
    "RiskLevel",
    "STATE_CONTEXT_CAP_FRACTION",
    "ScopeHints",
    "SignatureRow",
    "SymbolRef",
    "SymbolWithRationale",
    "TargetSymbol",
    "VerificationCriterion",
    "WorkOrder",
    "assemble_prompt",
    "assert_prompt_shipped",
    "edit",
    "from_json",
    "intake",
    "load_prompt",
    "plan",
    "prompt_path",
    "refuse_over_ceiling",
    "refuse_over_max",
    "research",
    "seat_prompt_section",
    "seat_state_section",
    "to_json",
    "verify_prompt_coverage",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
