"""B-233: the strong-model path (ADR-0049 D6).

A capability signal selects the variant: ``strong`` merges the PLANNER and
EDITOR steps into fewer, larger steps and may run EXPLORER reads in parallel
read-only contexts; a weak model keeps the D5 mechanism byte for byte. The
strength signal is the harness's ``model_strength`` attribute, which today
defaults to weak until a capability cache wires probe facts to it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ract import strong_path
from ract.manager import Plan, Step
from ract.rooted import Rooted
from ract.strong_path import (
    MERGED_ROLE,
    STRONG,
    WEAK,
    apply_strong_path,
    explore_in_parallel,
    select_variant,
    strength_from_probe,
)


def _step(action: str, artifact: str = "src/out.py") -> Step:
    return Step(action=action, provider_hint="local", expected_artifact=artifact)


def _plan(*steps: Step) -> Plan:
    return Plan(assumption="a", confidence=0.9, steps=list(steps))


# select_variant


@pytest.mark.parametrize(
    "roles,strength,expected",
    [
        (["planner", "editor", "verifier"], WEAK, ["planner", "editor", "verifier"]),
        (
            ["planner", "editor", "verifier"],
            "either",
            ["planner", "editor", "verifier"],
        ),
        (
            ["planner", "editor", "verifier"],
            STRONG,
            [MERGED_ROLE, "verifier"],
        ),
        (["intake", "explorer"], STRONG, ["intake", "explorer"]),
        (["editor", "planner"], STRONG, ["editor", "planner"]),
        ([], STRONG, []),
    ],
)
def test_select_variant(roles, strength, expected) -> None:
    assert select_variant(roles, strength=strength) == expected
    # The weak path is the identity, exactly (D5 unchanged).
    assert select_variant(roles, strength=WEAK) == list(roles)


# strength_from_probe


def _probe(findings: list[tuple[str, str, int | None]]) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        findings=[
            SimpleNamespace(label=label, status=status, number=number)
            for label, status, number in findings
        ]
    )


def test_a_full_probe_promotes_a_model() -> None:
    probe = _probe(
        [
            ("chat", "works", None),
            ("tool calling", "works", None),
            ("reasoning text", "returned", None),
            ("context window", "works", 131072),
        ]
    )
    assert strength_from_probe(probe) == STRONG


@pytest.mark.parametrize(
    "findings",
    [
        # No tool calling.
        [
            ("chat", "works", None),
            ("reasoning text", "returned", None),
            ("context window", "works", 131072),
        ],
        # Tool calling seen but not supported.
        [
            ("tool calling", "not supported", None),
            ("reasoning text", "returned", None),
            ("context window", "works", 131072),
        ],
        # No reasoning text.
        [
            ("tool calling", "works", None),
            ("reasoning text", "not returned", None),
            ("context window", "works", 131072),
        ],
        # Context window under the floor.
        [
            ("tool calling", "works", None),
            ("reasoning text", "returned", None),
            ("context window", "works", 8192),
        ],
        # Context window unknown.
        [
            ("tool calling", "works", None),
            ("reasoning text", "returned", None),
            ("context window", "not tried", None),
        ],
    ],
)
def test_a_partial_probe_keeps_a_model_weak(findings) -> None:
    assert strength_from_probe(_probe(findings)) == WEAK


def test_an_unprobed_provider_is_weak() -> None:
    assert strength_from_probe(_probe([])) == WEAK


# apply_strong_path


def test_strong_collapses_the_plan_to_one_agent_step() -> None:
    plan = _plan(_step("fix add()", "src/calc.py"), _step("add a note", "src/notes.py"))
    merged = apply_strong_path(plan, strength=STRONG)
    assert len(merged.steps) == 1
    step = merged.steps[0]
    assert step.agent is True
    assert "Step 1: fix add()" in step.action
    assert "Step 2: add a note" in step.action


@pytest.mark.parametrize(
    "plan,strength",
    [
        (_plan(_step("one"), _step("two")), WEAK),
        (_plan(_step("only one")), STRONG),
        (
            _plan(
                Step(action="answer only", provider_hint="", expected_artifact=""),
                Step(
                    action="and another question",
                    provider_hint="",
                    expected_artifact="",
                ),
            ),
            STRONG,
        ),
    ],
)
def test_other_plans_pass_through_unchanged(plan, strength) -> None:
    assert apply_strong_path(plan, strength=strength) is plan


def test_strength_for_harness_defaults_to_weak() -> None:
    from types import SimpleNamespace

    assert strong_path.strength_for_harness(SimpleNamespace()) == WEAK
    assert (
        strong_path.strength_for_harness(SimpleNamespace(model_strength=STRONG))
        == STRONG
    )
    # A value outside the closed set fails closed.
    assert (
        strong_path.strength_for_harness(SimpleNamespace(model_strength="huge")) == WEAK
    )


# explore_in_parallel


class _Scripted:
    """One model serving every parallel explorer, keyed by the question."""

    def __init__(self, scripts: dict[str, list[str]]) -> None:
        self.scripts = {key: list(value) for key, value in scripts.items()}

    def __call__(self, messages: list[dict[str, Any]]) -> Rooted[dict[str, Any]]:
        question = next(
            str(m.get("content", "")) for m in messages if m.get("role") == "user"
        )
        replies = self.scripts[question]
        content = replies.pop(0) if replies else json.dumps({"final": "done"})
        return Rooted(
            value={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
            },
            assumption="scripted",
            confidence=1.0,
        )


def test_parallel_explorers_answer_in_order(tmp_path: Path) -> None:
    model = _Scripted(
        {
            "count the files": [json.dumps({"final": "three files"})],
            "name the entry point": [json.dumps({"final": "main.py"})],
        }
    )
    answers = explore_in_parallel(
        model, ["count the files", "name the entry point"], tmp_path
    )
    assert [a.value for a in answers] == ["three files", "main.py"]
    assert explore_in_parallel(model, [], tmp_path) == []


def test_a_write_attempt_in_a_parallel_explorer_is_refused(tmp_path: Path) -> None:
    model = _Scripted(
        {
            "change something": [
                json.dumps(
                    {
                        "tool": "write_file",
                        "arguments": {
                            "path": "pwned.txt",
                            "content": "x",
                            "create": True,
                        },
                    }
                ),
                json.dumps({"final": "the write did not go through"}),
            ]
        }
    )
    answers = explore_in_parallel(model, ["change something"], tmp_path)
    # The loop told the model the call was refused and still ended on its answer.
    assert answers[0].value == "the write did not go through"
    # The read-only context could not write.
    assert not (tmp_path / "pwned.txt").exists()


# The run-level acceptance: fewer model calls for the same verified result.


def _run_scenario(tmp_path: Path, fake_model_server, scenario: str, monkeypatch):
    import threading

    from ract.session_events import EventStream
    from ract.session_turn import TurnRequest, run_turn
    from tests.test_session_turn import _repo

    server = fake_model_server(scenario)
    tmp_path.mkdir(parents=True, exist_ok=True)
    ws = _repo(tmp_path, server.base_url)
    (ws / "tests").mkdir(exist_ok=True)
    if scenario.endswith("_strong"):
        # The merged step runs through the step agent loop (D5 budgets).
        with (ws / "ract.yaml").open("a", encoding="utf-8") as fh:
            fh.write("agent:\n  step_tools: true\n")

        def _accept_all(path, before, after):
            # The proposed review would read the real console; this test
            # approves the proposal whole (the answers the operator's "a"
            # per hunk would give).
            from ract.review_hunks import ProposedDecision

            if after is None:
                return ProposedDecision(path, None, 1, 0, answers={1: "accepted"})
            return ProposedDecision(path, after, 1, 0, answers={1: "accepted"})

        monkeypatch.setattr("ract.ract_runner.console_proposed_reviewer", _accept_all)
    monkeypatch.setattr("builtins.input", lambda prompt="": "approve")
    events = []
    stream = EventStream(session=f"s-{scenario}")
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="add the greeting module",
        session_id=f"s-{scenario}",
        resume=False,
        auto=True,
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    return code, server, ws, events


FILES = ("src/greet.py", "src/util.py", "tests/test_greet.py")


def test_the_strong_path_makes_fewer_calls_for_the_same_result(
    tmp_path: Path, fake_model_server, monkeypatch
) -> None:
    weak_code, weak_server, weak_ws, _ = _run_scenario(
        tmp_path / "weak", fake_model_server, "plan_three_additions", monkeypatch
    )
    assert weak_code == 0
    assert len(weak_server.chat_requests) == 4  # the plan, then one per step
    weak_files = {name: (weak_ws / name).read_text(encoding="utf-8") for name in FILES}

    monkeypatch.setattr(strong_path, "strength_for_harness", lambda harness: STRONG)
    strong_code, strong_server, strong_ws, events = _run_scenario(
        tmp_path / "strong",
        fake_model_server,
        "plan_three_additions_strong",
        monkeypatch,
    )
    assert strong_code == 0, [e.data for e in events if e.kind == "error.surfaced"]
    # The plan plus one tool-call reply plus the final answer: fewer than 4.
    assert len(strong_server.chat_requests) == 3
    # The same verified result: identical bytes in every file.
    for name, text in weak_files.items():
        assert (strong_ws / name).read_text(encoding="utf-8") == text
