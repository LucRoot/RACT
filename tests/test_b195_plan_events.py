"""B-195 (a): an edited plan is announced again in the shape of ``plan.proposed``.

The edit re-emitted ``plan.proposed`` with the payload of
``plan.approval_requested`` (``plan_hash`` and steps), so the assumption line
vanished from the summary and ``planned`` was missing.
"""

from __future__ import annotations

from tests.test_plan_approval_review_points import PLAN, _harness, _run


def test_the_edited_plan_keeps_assumption_confidence_and_planned(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    harness = _harness(tmp_path, PLAN, "aaa", "bbb")
    _, events, _, _ = _run(
        harness,
        monkeypatch,
        ["edit 1", "Create a, written as the file a.txt with one line", "approve"],
    )
    proposed = [d for k, d in events if k == "plan.proposed"]
    assert len(proposed) >= 2
    first, again = proposed[0], proposed[-1]
    for field in ("assumption", "confidence", "planned"):
        assert again[field] == first[field], field
    assert "plan_hash" not in again
    assert again["steps"][0]["action"] != first["steps"][0]["action"]  # the edited step
