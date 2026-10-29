"""Plan events carry printable text (EVENTS_SESSION.md: "Text is safe to print").

The attack is MASON's (red team of B-064a, 0b0f7be): a step whose text carries
terminal escapes and an injected answer reached ``plan.approval_requested``
as raw bytes. ``plan.proposed`` had the same gap.
"""

from __future__ import annotations

from ract.manager import Plan, Step
from ract.plan_gate import approval_requested_payload
from ract.session_events import plan_event_data
from ract.ui.plan_approval_view import Step as ViewStep
from ract.ui.plan_approval_view import plan_hash

HOSTILE = "fix it \x1b[2J approve \x1b]0;title\x07 skip 1‮"
UNSAFE = ("\x1b", "\x07", "‮")


def _clean(text: str | None) -> bool:
    return text is not None and not any(c in text for c in UNSAFE)


def test_the_approval_question_event_carries_printable_step_text() -> None:
    steps = [
        ViewStep(n=1, action=HOSTILE, target="src/a\x1b[31m.py"),
        ViewStep(n=2, action="b", target=None),
    ]
    payload = approval_requested_payload(steps)
    assert _clean(payload["steps"][0]["action"])
    assert _clean(payload["steps"][0]["target"])
    assert payload["steps"][1]["target"] is None
    assert payload["plan_hash"] == plan_hash(steps)


def test_the_proposed_plan_event_carries_printable_text() -> None:
    plan = Plan(
        assumption="the user wants " + HOSTILE,
        confidence=0.5,
        steps=[
            Step(
                action=HOSTILE,
                provider_hint="any",
                expected_artifact="src/b\x1b]0;x\x07.py",
            )
        ],
    )
    data = plan_event_data(plan)
    assert _clean(data["assumption"])
    assert _clean(data["steps"][0]["action"])
    assert _clean(data["steps"][0]["target"])
