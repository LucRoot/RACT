"""B-137: a prose or tool-call first reply runs the request as one step through the loop."""

from __future__ import annotations

from typing import Any

from ract.manager import Manager, _has_tool_calls
from ract.plan_gate import AGENT_TARGET, approval_needed
from ract.rooted import Rooted


class Provider:
    """Answers each planning request from a list of raw replies."""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def complete(self, messages, **_kw):
        self.calls += 1
        return Rooted(value=self.replies.pop(0), assumption="", confidence=1.0)


def _text(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}


def _tools(content: str = "") -> dict[str, Any]:
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "run_tests", "arguments": "{}"},
    }
    return {
        "choices": [
            {
                "message": {"content": content, "tool_calls": [call]},
                "finish_reason": "tool_calls",
            }
        ]
    }


def test_a_tool_call_first_reply_becomes_the_one_step_with_its_opening() -> None:
    provider = Provider([_tools("I will run the tests first.")])
    plan = Manager(provider, "plan").plan("fix the failing test").unwrap()
    assert plan.planned is False and provider.calls == 1  # no re-ask: nothing lost
    (step,) = plan.steps
    assert step.agent is True and step.action == "fix the failing test"
    assert _has_tool_calls(step.opening)


def test_prose_twice_becomes_the_one_step_and_says_so() -> None:
    provider = Provider([_text("Sure, I can help."), _text("Let me look.")])
    rooted = Manager(provider, "plan").plan("fix the failing test")
    plan = rooted.unwrap()
    assert plan.planned is False and plan.steps[0].agent is True
    assert "went straight to tools" in rooted.assumption


def test_a_json_plan_is_still_a_plan() -> None:
    reply = _text(
        '{"assumption": "a", "confidence": 0.9, "steps": [{"action": "x", '
        '"provider_hint": "local", "expected_artifact": "src/calc.py"}]}'
    )
    plan = Manager(Provider([reply]), "plan").plan("fix").unwrap()
    assert plan.planned is True and plan.steps[0].agent is False


def test_an_agent_step_is_always_shown_for_approval_in_default_mode() -> None:
    """G-233 note 1: the one-step plan is shown before any tool call runs."""
    from ract.ui.plan_approval_view import Step as PlanStep

    steps = [PlanStep(n=1, action="fix the failing test", target=AGENT_TARGET)]
    assert approval_needed(steps, mode="default") is True


def test_headless_default_refuses_an_agent_plan_and_names_accept_edits() -> None:
    """G-233 note 2: headless with nobody to answer does not run it."""
    from ract.approval_callback import refuse_plan_needing_approval
    from ract.manager import Plan, Step

    plan = Plan(
        assumption="",
        confidence=0.5,
        steps=[Step(action="fix", provider_hint="", expected_artifact="", agent=True)],
        planned=False,
    )
    resolution = refuse_plan_needing_approval(plan)
    assert resolution is not None and resolution.kind == "refused"
    assert "--accept-edits" in resolution.error


def test_the_plan_event_and_the_headless_result_say_planned() -> None:
    """G-233 note 3: a field, not only text."""
    from ract.headless import result_object
    from ract.manager import Plan, Step
    from ract.session_events import EventStream, SessionEvent, plan_event_data

    plan = Plan(
        assumption="",
        confidence=0.5,
        steps=[Step(action="fix", provider_hint="", expected_artifact="", agent=True)],
        planned=False,
    )
    assert plan_event_data(plan)["planned"] is False
    events: list[SessionEvent] = []
    stream = EventStream(session="s")
    stream.subscribe(events.append)
    stream.emit("plan.proposed", plan_event_data(plan), turn=1)
    stream.emit("turn.finished", {"outcome": "done", "verdict": "v"}, turn=1)
    assert result_object(events, session="s", exit_code=0)["planned"] is False


def test_with_the_step_loop_off_prose_is_the_answer_and_tools_are_refused(
    tmp_path,
) -> None:
    from ract.executor.steps import Executor
    from ract.manager import Step
    from ract.providers.router import ProviderRouter

    executor = Executor(router=ProviderRouter({}), project_dir=tmp_path)
    prose = Step(
        action="q",
        provider_hint="",
        expected_artifact="",
        agent=True,
        opening=_text("hi"),
    )
    assert executor._agent_without_tools(prose, 1).unwrap()[1] == "hi"
    tools = Step(
        action="q", provider_hint="", expected_artifact="", agent=True, opening=_tools()
    )
    refused = executor._agent_without_tools(tools, 1)
    assert not refused.is_ok() and "step agent loop is off" in refused.error
