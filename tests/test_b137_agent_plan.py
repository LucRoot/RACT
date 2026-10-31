"""B-137: a prose or tool-call first reply runs the request as one step through the loop."""

from __future__ import annotations

from typing import Any

from ract.manager import Manager, _has_tool_calls
from ract.plan_gate import approval_needed
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
    rooted = Manager(provider, "plan").plan("fix the failing test")
    assert rooted.is_ok(), rooted.error  # the harness reads is_ok, not unwrap
    plan = rooted.unwrap()
    assert plan.planned is False and provider.calls == 1  # no re-ask: nothing lost
    (step,) = plan.steps
    assert step.agent is True and step.action == "fix the failing test"
    assert _has_tool_calls(step.opening)


def test_the_planner_the_harness_calls_passes_the_agent_plan_on() -> None:
    """The J4 flip: the harness calls Planner.plan, which checks the plan's confidence."""
    from ract.planner import Planner

    provider = Provider([_tools("I will run the tests first.")])
    rooted = Planner(Manager(provider, "plan")).plan("fix the failing test")
    assert rooted.is_ok(), rooted.error
    assert rooted.unwrap().steps[0].agent is True


def test_prose_twice_with_the_step_loop_on_becomes_the_one_step() -> None:
    provider = Provider([_text("Sure, I can help."), _text("Let me look.")])
    manager = Manager(provider, "plan")
    manager.agent_steps = True  # the harness sets it from agent.step_tools
    rooted = manager.plan("fix the failing test")
    assert rooted.is_ok(), rooted.error
    plan = rooted.unwrap()
    assert plan.planned is False and plan.steps[0].agent is True
    # The loop starts fresh with the tools; replayed prose would end it at once.
    assert plan.steps[0].opening is None
    assert "went straight to tools" in rooted.assumption


def test_prose_twice_with_the_step_loop_off_keeps_the_plain_sentence() -> None:
    from ract.manager import NO_PLAN_SENTENCE

    provider = Provider([_text("Sure, I can help."), _text("Let me look.")])
    rooted = Manager(provider, "plan").plan("fix the failing test")
    assert not rooted.is_ok() and rooted.error == NO_PLAN_SENTENCE  # B-086


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

    steps = [PlanStep(n=1, action="fix the failing test", agent=True)]  # B-195
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


def test_with_the_step_loop_off_the_tool_calls_are_refused_and_named(
    tmp_path,
) -> None:
    from ract.executor.steps import Executor
    from ract.manager import Step
    from ract.providers.router import ProviderRouter

    executor = Executor(router=ProviderRouter({}), project_dir=tmp_path)
    tools = Step(
        action="q", provider_hint="", expected_artifact="", agent=True, opening=_tools()
    )
    refused = executor._agent_without_tools(tools, 1)
    assert not refused.is_ok() and "step agent loop is off" in refused.error


def test_headless_a_tool_call_first_reply_runs_as_the_one_step(
    tmp_path, fake_model_server
) -> None:
    """End to end (the J4 flip found it): the harness reads the plan through the
    Planner's confidence floor, and the one step is the request as typed."""
    import json

    from tests.fixtures.fake_model_server import Scenario
    from tests.test_headless import _ract
    from tests.test_session_turn import _repo

    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {
                        "reply": {
                            "kind": "tool_calls",
                            "content": "I will read it first.",
                            "calls": [
                                {
                                    "name": "read_file",
                                    "arguments": {"path": "src/calc.py"},
                                }
                            ],
                        }
                    },
                    {"reply": {"kind": "text", "content": "add subtracts."}},
                ]
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)
    config = ws / "ract.yaml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\nagent:\n  step_tools: true\n",
        encoding="utf-8",
    )
    result = _ract(ws, "-p", "--accept-edits", "look at add", "--output-format", "json")
    assert result.returncode == 0, result.stderr
    assert "Planning failed" not in result.stderr
    assert "1. look at add" in result.stderr
    assert "dialect brief" not in result.stderr  # the planning prompt is not the step
    assert json.loads(result.stdout.strip().splitlines()[-1])["planned"] is False
