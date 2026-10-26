"""Package 5 (handoff 1): an interrupted step is skipped, not failed.

Ctrl-C at the approval prompt used to record "[!] 1. ... failed" before "stopping...". The
renderer already shows a stopped step as skipped (plan_state: turn.finished sets pending or
running steps to skipped), so the executor must report the same outcome.
"""

from __future__ import annotations

from ract.executor.steps import unfinished_step_outcome


def test_an_interrupted_unfinished_step_is_skipped():
    assert unfinished_step_outcome("Approval denied for step", cancelled=True) == "skipped"
    assert unfinished_step_outcome("", cancelled=True) == "skipped"


def test_a_refused_unfinished_step_is_refused():
    assert unfinished_step_outcome("refused by policy", cancelled=False) == "refused"


def test_any_other_unfinished_step_is_failed():
    assert unfinished_step_outcome("provider timed out", cancelled=False) == "failed"
