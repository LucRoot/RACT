"""B-042: questions are answered, not written to a file.

The planner used to turn an empty expected_artifact into output.txt (or
test_results.txt), so a question asked of RACT wrote a file into the
repository, and a step that only read a file overwrote it with its reply.
An answer step now writes nothing, needs no worktree, and its text is the
answer; `/ask` and `ract -p --ask` skip the planner.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ract.executor.steps import StepResult
from ract.manager import Plan, Step
from ract.plan_validator import PlanValidator
from tests.fixtures.fake_model_server import Scenario
from tests.test_headless import _ract
from tests.test_repl import _session
from tests.test_session_turn import _plan, _repo

ANSWER = "add() is defined in src/calc.py and returns a - b."


def _git(ws: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ws, capture_output=True, text=True, check=True
    ).stdout.strip()


def _scenario(*replies: str) -> Scenario:
    return Scenario.from_dict(
        {"turns": [{"reply": {"kind": "text", "content": r}} for r in replies]}
    )


def test_a_question_plan_writes_nothing_and_answers(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_scenario(_plan(""), ANSWER))
    ws = _repo(tmp_path, server.base_url)
    calc_before = (ws / "src" / "calc.py").read_text(encoding="utf-8")

    result = _ract(ws, "-p", "what does add() do?", "--output-format", "stream-json")

    assert result.returncode == 0, result.stderr
    assert _git(ws, "status", "--porcelain") == ""
    assert not (ws / "output.txt").exists()
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == calc_before
    # No worktree, branch or commit for a step that writes nothing.
    assert _git(ws, "branch", "--list", "rootact/step/*") == ""
    events = [json.loads(line) for line in result.stdout.splitlines()]
    answer = "".join(
        e["data"]["text"]
        for e in events
        if e["kind"] == "agent.text.delta" and e["data"].get("channel") == "answer"
    )
    assert ANSWER in answer
    step_prompt = json.dumps(server.chat_requests[1].body)
    assert "no file is written" in step_prompt


def test_ask_skips_the_planner(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server(_scenario(ANSWER))
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "--ask", "what does add() do?")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ANSWER
    assert len(server.chat_requests) == 1
    assert "Core Manager" not in json.dumps(server.chat_requests[0].body)
    assert _git(ws, "status", "--porcelain") == ""


def test_ract_run_ask_records_the_answer_in_the_session(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_scenario(ANSWER))
    ws = _repo(tmp_path, server.base_url)

    result = _ract(
        ws,
        "run",
        "--config",
        "ract.yaml",
        "--session",
        "s1",
        "--ask",
        "--",
        "what does add() do?",
    )

    assert result.returncode == 0, result.stderr
    saved = json.loads((ws / ".ract" / "sessions" / "s1.json").read_text("utf-8"))
    assert any("answered: " + ANSWER in line for line in saved["outcomes"])
    assert _git(ws, "status", "--porcelain") == ""


def test_ask_and_loop_are_exclusive(tmp_path: Path) -> None:
    result = _ract(tmp_path, "run", "--ask", "--loop", "--", "why?")

    assert result.returncode == 2
    assert "--loop and --ask" in result.stderr


def test_repl_ask_runs_an_ask_turn_even_in_dry_run() -> None:
    session, calls, _ = _session()
    session.handle("/set dry-run on")

    session.handle("/ask why does add subtract?")

    argv = calls[-1]
    assert argv[0] == "run" and "--ask" in argv and "--dry-run" not in argv
    assert argv[-2:] == ["--", "why does add subtract?"]


def test_an_answer_step_is_a_valid_plan() -> None:
    plan = Plan(
        assumption="a question",
        confidence=0.9,
        steps=[Step(action="explain add", provider_hint="local", expected_artifact="")],
    )

    assert PlanValidator.validate(plan).is_valid


@pytest.mark.parametrize(
    ("artifact", "content", "expected"),
    [
        ("src/a.py", "code", "edit -> src/a.py"),
        ("", "two\n  lines", "edit -> answered: two lines"),
        ("", "x" * 500, "edit -> answered: " + "x" * 400 + " [...]"),
    ],
)
def test_history_records_the_file_or_the_bounded_answer(
    artifact: str, content: str, expected: str
) -> None:
    step = Step(action="edit", provider_hint="local", expected_artifact=artifact)

    assert StepResult(step=step, raw_response={}, content=content).outcome() == expected
