"""Tests for the shared function-contract dataclasses.

Every contract is frozen; a mutation attempt raises. Canonical JSON
round-trip is stable across nested tuples of enums and dataclasses.
"""

from __future__ import annotations

import dataclasses

import pytest

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


def _sample_work_order() -> WorkOrder:
    return WorkOrder(
        request_type=RequestType.REFACTOR,
        scope_hints=ScopeHints(
            mentioned_symbols=("User",),
            keywords=("rename",),
        ),
        success_criteria=("all references updated",),
        constraints=("no public-API break",),
        priority_markers=(("urgency", "release_blocker"),),
        ambiguity_flags=(),
    )


def _sample_research_bundle() -> ResearchBundle:
    return ResearchBundle(
        relevant_symbols=(
            SymbolWithRationale(
                symbol=SymbolRef(name="User", file_path="src/user.py"),
                rationale="target of rename",
            ),
        ),
        call_neighborhood=(
            SignatureRow(
                symbol=SymbolRef(name="Session", file_path="src/session.py"),
                signature="class Session:",
                direction="caller",
            ),
        ),
        architectural_context="single-file model.",
        similar_prior_work=(CommitRef(sha="abc123", subject="rename Order to Cart"),),
        risk_zones=(),
    )


def _sample_change_plan() -> ChangePlan:
    return ChangePlan(
        target_symbols=(
            TargetSymbol(
                symbol=SymbolRef(name="User"),
                action="rename",
                notes="User -> Account",
            ),
        ),
        load_manifest=(SymbolRef(name="User"),),
        invariants=(
            Invariant(kind=InvariantKind.TEST_NAME, expression="test_user_flow"),
        ),
        verification_criteria=(
            VerificationCriterion(
                predicate_id="P1",
                kind="test_passes",
                payload=(("test", "test_user_flow"),),
            ),
        ),
        risk_assessment=RiskAssessment(
            level=RiskLevel.MEDIUM,
            rationale="two files touched",
        ),
    )


def _sample_candidate_diff() -> CandidateDiff:
    return CandidateDiff(
        unified_diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n",
        hunks=(HunkSummary(file_path="x", start_line=1, end_line=1, summary="swap"),),
        assembled_input_tokens=42,
        output_tokens=5,
    )


# ---------------------------------------------------------------------------
# Frozen invariance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instance",
    [
        _sample_work_order(),
        _sample_research_bundle(),
        _sample_change_plan(),
        _sample_candidate_diff(),
    ],
)
def test_contract_is_frozen(instance):
    with pytest.raises(dataclasses.FrozenInstanceError):
        object.__setattr__  # sanity
        instance.__class__.__dataclass_fields__  # sanity
        setattr(instance, next(iter(instance.__dataclass_fields__)), None)


def test_scope_hints_is_frozen():
    hints = ScopeHints(mentioned_symbols=("a",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(hints, "mentioned_symbols", ())


# ---------------------------------------------------------------------------
# Canonical JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instance",
    [
        _sample_work_order(),
        _sample_research_bundle(),
        _sample_change_plan(),
        _sample_candidate_diff(),
    ],
)
def test_json_round_trip(instance):
    payload = to_json(instance)
    rehydrated = from_json(payload)
    assert rehydrated == instance
    # And the projection is deterministic.
    assert to_json(rehydrated) == payload


def test_work_order_json_is_canonical():
    order = _sample_work_order()
    payload = to_json(order)
    # Same order for two constructions of the same content.
    other = to_json(_sample_work_order())
    assert payload == other


def test_json_projection_is_sorted():
    # Ensures the projection is byte-stable across Python dict-order
    # changes: keys inside the top-level object appear in sorted order.
    payload = to_json(_sample_work_order())
    # Find the outermost key list.
    import json as _json

    obj = _json.loads(payload)
    top_keys = sorted(obj.keys())
    reconstructed = _json.dumps(obj, sort_keys=True, separators=(",", ":"))
    assert reconstructed == payload
    assert list(obj.keys()) == top_keys  # dict ordering follows sorted keys


# ---------------------------------------------------------------------------
# Iteration bound bounds
# ---------------------------------------------------------------------------


def test_change_plan_iteration_bound_default_is_3():
    plan = _sample_change_plan()
    assert plan.iteration_bound == 3


# ---------------------------------------------------------------------------
# Prompt coverage (Second Pass Q4 PARTIAL fix)
# ---------------------------------------------------------------------------


def test_verify_prompt_coverage_passes_for_shipped_constants():
    """Shipped prompt files match the four function version constants."""
    from ract.memory.functions.edit import (
        EDIT_FUNCTION_NAME,
        EDIT_PROMPT_VERSION,
    )
    from ract.memory.functions.intake import (
        INTAKE_FUNCTION_NAME,
        INTAKE_PROMPT_VERSION,
    )
    from ract.memory.functions.plan import (
        PLAN_FUNCTION_NAME,
        PLAN_PROMPT_VERSION,
    )
    from ract.memory.functions.prompts_loader import verify_prompt_coverage
    from ract.memory.functions.research import (
        RESEARCH_FUNCTION_NAME,
        RESEARCH_PROMPT_VERSION,
    )

    verify_prompt_coverage(
        {
            INTAKE_FUNCTION_NAME: INTAKE_PROMPT_VERSION,
            RESEARCH_FUNCTION_NAME: RESEARCH_PROMPT_VERSION,
            PLAN_FUNCTION_NAME: PLAN_PROMPT_VERSION,
            EDIT_FUNCTION_NAME: EDIT_PROMPT_VERSION,
        }
    )


def test_verify_prompt_coverage_raises_on_extra_file(tmp_path):
    from ract.memory.functions.prompts_loader import (
        PromptCoverageError,
        verify_prompt_coverage,
    )
    import ract.memory.functions.prompts_loader as loader

    # Redirect PROMPTS_DIR to a tmp copy that has an unregistered file.
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "intake_v1.md").write_text("# Contract version: v1\n", encoding="utf-8")
    (prompts / "extra_v9.md").write_text("# Contract version: v9\n", encoding="utf-8")
    original = loader.PROMPTS_DIR
    loader.PROMPTS_DIR = prompts
    try:
        with pytest.raises(PromptCoverageError):
            verify_prompt_coverage({"intake": "v1"})
    finally:
        loader.PROMPTS_DIR = original


def test_research_ambiguity_flag_emits_visible_event(tmp_path):
    """Second Pass Q2: an ambiguous WorkOrder must surface in the trace
    even though research proceeds with best-effort scope hints (the
    composition layer is the gate)."""
    import json

    from ract.memory.events import NullEventSink
    from ract.memory.functions import (
        IndexBundle,
        RequestType,
        ScopeHints,
        WorkOrder,
        research,
    )
    from ract.memory.functions.testing import MockProvider

    canned = json.dumps(
        {
            "relevant_symbols": [
                {"name": "x", "file_path": "x.py", "kind": "function", "rationale": "r"}
            ],
            "call_neighborhood": [],
            "architectural_context": "",
            "similar_prior_work": [],
            "risk_zones": [],
        }
    )
    provider = MockProvider(responses_by_function={"research": canned})
    sink = NullEventSink()
    ambiguous_wo = WorkOrder(
        request_type=RequestType.OTHER,
        scope_hints=ScopeHints(mentioned_symbols=("x",)),
        success_criteria=(),
        constraints=(),
        ambiguity_flags=("target unclear",),
    )
    research(ambiguous_wo, IndexBundle(), provider, sink=sink)
    # A budget.declared event was emitted BEFORE the model call
    # carrying the ambiguity flag list.
    ambiguity_events = [rec for rec in sink.records if "ambiguity_flags" in rec[1]]
    assert ambiguity_events, "research did not surface ambiguity_flags on the sink"
    assert ambiguity_events[0][1]["ambiguity_flags"] == ["target unclear"]
