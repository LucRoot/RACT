# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the novelty budget anti-rot guard."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.executor import Executor
from rootact.manager import Plan, Step
from rootact.novelty_budget import NoveltyBudget
from rootact.rooted import Rooted


class FakeAdapter:
    """Minimal fake provider adapter."""

    def __init__(self, name: str, response_content: str = "ok") -> None:
        self._name = name
        self._response_content = response_content

    @property
    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict]:
        return Rooted(
            value={"choices": [{"message": {"content": self._response_content}}]},
            assumption="fake adapter responds",
            confidence=1.0,
            provenance=["fake_adapter.complete"],
        )


class FakeRouter:
    """Fake router that always returns the configured adapter."""

    def __init__(self, adapter: FakeAdapter) -> None:
        self._adapter = adapter

    def select_for_hint(self, hint: str) -> Rooted:
        return Rooted(
            value=self._adapter,
            assumption="fake router has an adapter",
            confidence=1.0,
            provenance=["fake_router.select_for_hint"],
        )

    def fallback_chain(self, hint: str, max_attempts: int = 3) -> list[Rooted]:
        return []


def _make_plan(steps: list[Step]) -> Plan:
    return Plan(assumption="test assumption", confidence=0.9, steps=steps)


def test_novelty_budget_charges_new_file(tmp_path):
    budget = NoveltyBudget(tmp_path, budget=10)
    charges = budget.assess("new.py", "def f():\n    pass\n")

    assert any(c.category == "new_file" and c.points == 3 for c in charges)


def test_novelty_budget_charges_new_public_symbol(tmp_path):
    (tmp_path / "module.py").write_text("def existing():\n    pass\n", encoding="utf-8")
    budget = NoveltyBudget(tmp_path, budget=10)
    charges = budget.assess(
        "module.py", "def existing():\n    pass\n\ndef added():\n    pass\n"
    )

    assert any(
        c.category == "new_public_symbol" and c.points == 6 and "added" in c.detail
        for c in charges
    )


def test_novelty_budget_persists_spending(tmp_path):
    budget = NoveltyBudget(tmp_path, budget=5)
    charges = budget.assess("new.py", "def f():\n    pass\n")
    budget.spend(charges)

    budget2 = NoveltyBudget(tmp_path, budget=5)
    assert budget2.remaining == budget.remaining


def test_executor_blocks_when_budget_exhausted(tmp_path):
    (tmp_path / "module.py").write_text("def existing():\n    pass\n", encoding="utf-8")
    budget = NoveltyBudget(tmp_path, budget=5)
    adapter = FakeAdapter("mock", response_content="def new_one():\n    pass\n")
    executor = Executor(
        FakeRouter(adapter), project_dir=tmp_path, novelty_budget=budget
    )
    plan = _make_plan(
        [Step(action="add symbol", provider_hint="mock", expected_artifact="module.py")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert not result.is_ok()
    assert result.hint == "novelty-budget"
    assert "Novelty budget exhausted" in (result.error or "")


def test_executor_allows_write_with_overrun_override(tmp_path):
    (tmp_path / "module.py").write_text("def existing():\n    pass\n", encoding="utf-8")
    budget = NoveltyBudget(tmp_path, budget=5)
    adapter = FakeAdapter("mock", response_content="def new_one():\n    pass\n")
    executor = Executor(
        FakeRouter(adapter),
        project_dir=tmp_path,
        novelty_budget=budget,
        allow_novelty_overrun=True,
    )
    plan = _make_plan(
        [Step(action="add symbol", provider_hint="mock", expected_artifact="module.py")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()


def test_executor_does_not_charge_unmodified_file(tmp_path):
    (tmp_path / "module.txt").write_text("existing content\n", encoding="utf-8")
    budget = NoveltyBudget(tmp_path, budget=5)
    adapter = FakeAdapter("mock", response_content="existing content\n")
    executor = Executor(
        FakeRouter(adapter), project_dir=tmp_path, novelty_budget=budget
    )
    plan = _make_plan(
        [Step(action="keep file", provider_hint="mock", expected_artifact="module.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    assert budget.remaining == 5


def test_novelty_budget_summary_after_spending(tmp_path):
    budget = NoveltyBudget(tmp_path, budget=15)
    charges = budget.assess("new.py", "def f():\n    pass\n")
    budget.spend(charges)

    summary = budget.summary()
    assert summary["budget"] == 15
    assert summary["spent"] == 9  # new_file 3 + new_public_symbol 6
    assert summary["remaining"] == 6


# RACT 0.1.1 - Trust and Tooling
