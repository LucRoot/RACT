"""B-064a wiring (ADR-0049 D12): the plan is approved once, before its first step.

A real harness with a scripted planner and step replies, in a project that is not a
git repository (the direct path). The operator's answers come through ``input``; the
session events are captured from the turn's reporter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from ract import turn_context
from ract.approval_callback import console_plan_approval, refuse_plan_needing_approval
from ract.harness import Harness
from ract.rooted import Rooted


def _harness(tmp_path: Path, *replies: str) -> Harness:
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "manager.txt").write_text("manager", encoding="utf-8")
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:9/v1",
                "model": "m",
            }
        },
        "prompts_dir": "prompts",
    }
    (tmp_path / "ract.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    harness = Harness.from_config_path(tmp_path / "ract.yaml").unwrap()
    harness.manager.provider.complete = MagicMock(
        side_effect=[
            Rooted(
                value={"choices": [{"message": {"content": text}}]},
                assumption="ok",
                confidence=1.0,
            )
            for text in replies
        ]
    )
    return harness


PLAN = (
    '{"assumption": "a", "confidence": 0.9, "steps": ['
    '{"action": "Create a", "provider_hint": "local", "expected_artifact": "a.txt"},'
    '{"action": "Create b", "provider_hint": "local", "expected_artifact": "b.txt"}]}'
)
ONE_STEP = (
    '{"assumption": "a", "confidence": 0.9, "steps": ['
    '{"action": "Create a", "provider_hint": "local", "expected_artifact": "a.txt"}]}'
)


def _run(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    answers: list[str],
    *,
    plan_approval: Any = console_plan_approval,
) -> tuple[Any, list[tuple[str, dict]], list[str], list[str]]:
    events: list[tuple[str, dict]] = []
    asked: list[str] = []
    per_step: list[str] = []
    queue = list(answers)

    def fake_input(prompt: str = "") -> str:
        asked.append(prompt)
        return queue.pop(0)

    def per_step_approval(step: Any) -> bool:
        per_step.append(step.expected_artifact)
        return True

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    turn_context.bind(None, lambda kind, data: events.append((kind, data)))
    try:
        result = harness.run(
            "make a and b",
            approval_callback=per_step_approval,
            plan_approval=plan_approval,
        )
    finally:
        turn_context.bind(None)
    return result, events, asked, per_step


def _kinds(events: list[tuple[str, dict]]) -> list[str]:
    wanted = {"plan.proposed", "plan.approval_requested", "plan.approval_answered"}
    return [kind for kind, _ in events if kind in wanted]


def test_approve_runs_the_plan_without_asking_per_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path, PLAN, "aaa", "bbb")
    result, events, asked, per_step = _run(harness, monkeypatch, ["approve"])

    assert result.is_ok(), result.error
    assert _kinds(events) == [
        "plan.proposed",
        "plan.approval_requested",
        "plan.approval_answered",
    ]
    answered = dict(events)["plan.approval_answered"]
    assert answered["answer"] == "approve" and answered["kept"] == [1, 2]
    assert answered["edited"] is None
    assert len(asked) == 1
    # The approval covers exactly the targets shown: no per-step question.
    assert per_step == []
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "aaa"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "bbb"


def test_skip_drops_the_step_and_reports_it_skipped_by_you(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path, PLAN, "bbb")
    result, events, _, _ = _run(harness, monkeypatch, ["skip 1"])

    assert result.is_ok(), result.error
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "bbb"
    finished = [d for k, d in events if k == "step.finished"]
    assert [(d["n"], d["outcome"]) for d in finished] == [(1, "skipped"), (2, "done")]
    assert finished[0]["hint"] == "skipped by you"
    answered = dict(events)["plan.approval_answered"]
    assert answered["skipped"] == [{"n": 1, "reason": "user"}]


def test_cancel_runs_nothing_and_changes_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path, PLAN)
    before = sorted(p.name for p in tmp_path.iterdir())
    result, events, _, _ = _run(harness, monkeypatch, ["cancel"])

    assert not result.is_ok()
    assert result.hint == "plan_cancelled"
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert harness.manager.provider.complete.call_count == 1  # the plan only
    assert dict(events)["plan.approval_answered"]["answer"] == "cancel"
    assert not [k for k, _ in events if k.startswith("step.")]


def test_an_answer_that_is_not_understood_asks_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path, PLAN, "aaa", "bbb")
    result, events, asked, _ = _run(harness, monkeypatch, ["y please", "approve"])

    assert result.is_ok(), result.error
    assert len(asked) == 2
    assert [k for k, _ in events].count("plan.approval_answered") == 1


def test_a_one_step_plan_keeps_the_per_step_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path, ONE_STEP, "aaa")
    result, events, asked, per_step = _run(harness, monkeypatch, [])

    assert result.is_ok(), result.error
    assert asked == []
    assert per_step == ["a.txt"]
    assert "plan.approval_requested" not in [k for k, _ in events]


def test_headless_default_refuses_before_any_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path, PLAN)
    result, events, asked, _ = _run(
        harness, monkeypatch, [], plan_approval=refuse_plan_needing_approval
    )

    assert not result.is_ok()
    assert "refused" in (result.error or "") and "--accept-edits" in (
        result.error or ""
    )
    assert asked == []
    assert harness.manager.provider.complete.call_count == 1
    assert not (tmp_path / "a.txt").exists()
    assert not [k for k, _ in events if k.startswith("step.")]


def test_a_step_writing_a_file_the_plan_did_not_list_still_asks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract.harness import _approved_plan_callback
    from ract.manager import Step

    calls: list[str] = []

    def base(step: Any) -> bool:
        calls.append(step.expected_artifact)
        return False

    callback = _approved_plan_callback(base, {"a.txt"})
    assert callback(Step(action="x", provider_hint="local", expected_artifact="a.txt"))
    assert not callback(
        Step(action="y", provider_hint="local", expected_artifact="other.txt")
    )
    assert calls == ["other.txt"]


def _two_writes() -> str:
    return PLAN


def test_cancel_in_a_session_turn_is_refused_with_exit_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_model_server: Any
) -> None:
    import threading

    from ract.session_events import EventStream
    from ract.session_turn import TurnRequest, run_turn
    from tests.fixtures.fake_model_server import Scenario
    from tests.test_session_turn import _repo

    server = fake_model_server(
        Scenario.from_dict({"turns": [{"reply": {"kind": "text", "content": PLAN}}]})
    )
    ws = _repo(tmp_path, server.base_url)
    monkeypatch.setattr("builtins.input", lambda prompt="": "cancel")
    stream = EventStream(session="s-test")
    events: list[Any] = []
    stream.subscribe(events.append)

    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="make a and b",
        session_id="s-test",
        resume=False,
        auto=True,
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())

    assert code == 0
    finished = [e.data for e in events if e.kind == "turn.finished"][-1]
    assert finished["outcome"] == "refused"
    assert not (ws / "a.txt").exists() and not (ws / "b.txt").exists()
    assert len(server.chat_requests) == 1  # the plan only


def test_headless_default_exits_3_before_any_step(
    tmp_path: Path, fake_model_server: Any
) -> None:
    from tests.fixtures.fake_model_server import Scenario
    from tests.test_headless import _ract
    from tests.test_session_turn import _repo

    server = fake_model_server(
        Scenario.from_dict({"turns": [{"reply": {"kind": "text", "content": PLAN}}]})
    )
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "make a and b")

    assert result.returncode == 3, result.stdout + result.stderr
    assert "--accept-edits" in result.stdout + result.stderr
    assert len(server.chat_requests) == 1
    assert not (ws / "a.txt").exists()
