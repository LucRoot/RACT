"""Package 2 (B-064a, ADR-0049 D12): when a plan is approved before its first step.

In default mode a plan of two or more steps that changes files asks once. A one-step plan keeps the
per-step approval. accept-edits and plan modes never ask. A plan of answer steps only never asks.
Headless default refuses a plan with file changes (exit 3) and names --accept-edits.
"""

from __future__ import annotations

from ract.plan_gate import approval_needed, headless_refusal
from ract.ui.plan_approval_view import Step


def _steps(n: int, target: str = "src/a.py"):
    return [Step(n=i + 1, action=f"step {i + 1}", target=target) for i in range(n)]


def test_default_mode_asks_for_a_two_step_plan_with_file_changes():
    assert approval_needed(_steps(2), mode="default") is True


def test_a_one_step_plan_keeps_the_per_step_approval_and_does_not_ask_once():
    assert approval_needed(_steps(1), mode="default") is False


def test_accept_edits_and_plan_modes_never_ask():
    assert approval_needed(_steps(3), mode="accept-edits") is False
    assert approval_needed(_steps(3), mode="plan") is False


def test_a_plan_of_answer_steps_only_never_asks():
    assert approval_needed(_steps(3, target=""), mode="default") is False


def test_headless_default_refuses_a_plan_with_file_changes_and_names_the_flag():
    sentence = headless_refusal(_steps(2), mode="default")
    assert sentence is not None and "--accept-edits" in sentence
    assert headless_refusal(_steps(2), mode="accept-edits") is None
    assert headless_refusal(_steps(3, target=""), mode="default") is None
