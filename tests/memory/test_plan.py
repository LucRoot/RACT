"""Tests for :func:`ract.memory.functions.plan.plan`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.memory.functions import (
    ChangePlan,
    IndexBundle,
    InfeasiblePlanError,
    ProviderContractError,
    RequestType,
    ResearchBundle,
    RiskLevel,
    ScopeHints,
    SymbolRef,
    SymbolWithRationale,
    WorkOrder,
    plan,
)
from ract.memory.functions.testing import MockProvider


def _work_order() -> WorkOrder:
    return WorkOrder(
        request_type=RequestType.REFACTOR,
        scope_hints=ScopeHints(mentioned_symbols=("greet",)),
        success_criteria=("test_greet passes",),
        constraints=(),
    )


def _research() -> ResearchBundle:
    return ResearchBundle(
        relevant_symbols=(
            SymbolWithRationale(
                symbol=SymbolRef(name="greet", file_path="greet.py"),
                rationale="target",
            ),
        ),
        call_neighborhood=(),
        architectural_context="one function.",
    )


def _plan_response() -> str:
    return json.dumps(
        {
            "target_symbols": [
                {
                    "name": "greet",
                    "file_path": "greet.py",
                    "kind": "function",
                    "action": "rename",
                    "notes": "greet -> say_hello",
                }
            ],
            "load_manifest": [
                {"name": "greet", "file_path": "greet.py", "kind": "function"},
                {"name": "main", "file_path": "main.py", "kind": "function"},
            ],
            "invariants": [
                {
                    "kind": "test_name",
                    "expression": "test_greet_passes",
                    "description": "regression coverage",
                }
            ],
            "verification_criteria": [
                {
                    "predicate_id": "P1",
                    "kind": "test_passes",
                    "payload": {"test": "test_greet_passes"},
                }
            ],
            "risk_assessment": {
                "level": "low",
                "rationale": "one call site",
                "blast_radius_symbol_ids": [42],
            },
            "iteration_bound": 2,
        }
    )


def test_plan_returns_change_plan(tmp_path: Path):
    provider = MockProvider(responses_by_function={"plan": _plan_response()})
    result = plan(_work_order(), _research(), IndexBundle(), provider)
    assert isinstance(result, ChangePlan)
    assert result.target_symbols[0].symbol.name == "greet"
    assert result.iteration_bound == 2
    assert result.risk_assessment.level is RiskLevel.LOW


def test_plan_load_manifest_covers_every_reference(tmp_path: Path):
    provider = MockProvider(responses_by_function={"plan": _plan_response()})
    result = plan(_work_order(), _research(), IndexBundle(), provider)
    manifest_names = {ref.name for ref in result.load_manifest}
    assert "greet" in manifest_names
    assert "main" in manifest_names


def test_plan_infeasible_raises_on_empty_targets(tmp_path: Path):
    infeasible = json.dumps(
        {
            "target_symbols": [],
            "load_manifest": [],
            "invariants": [],
            "verification_criteria": [],
            "risk_assessment": {"level": "high", "rationale": "no code path"},
            "iteration_bound": 1,
        }
    )
    provider = MockProvider(responses_by_function={"plan": infeasible})
    with pytest.raises(InfeasiblePlanError):
        plan(_work_order(), _research(), IndexBundle(), provider)


def test_plan_iteration_bound_out_of_range_raises(tmp_path: Path):
    over = json.dumps(
        {
            "target_symbols": [
                {
                    "name": "x",
                    "file_path": "x.py",
                    "kind": "function",
                    "action": "modify",
                }
            ],
            "load_manifest": [],
            "invariants": [],
            "verification_criteria": [],
            "risk_assessment": {"level": "low", "rationale": "ok"},
            "iteration_bound": 99,
        }
    )
    provider = MockProvider(responses_by_function={"plan": over})
    with pytest.raises(ProviderContractError):
        plan(_work_order(), _research(), IndexBundle(), provider)
