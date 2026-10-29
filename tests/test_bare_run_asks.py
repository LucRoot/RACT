"""B-101 (D-026, decision O, D-103): a bare run in a terminal asks before it writes.

S2 D4: in a real terminal with no flag, the run wrote three files with no
question; the plan question and the per-step question were wired to ``--auto``
only. Each case is a real ``ract`` in a pseudo-terminal against the fake model
server, for ``ract run "<intent>"`` and the bare ``ract "<intent>"``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.fake_model_server import FakeModelServer, Scenario
from tests.ux import run_baseline as rb
from tests.ux.terminal_driver import spawn

PLAN_QUESTION = r"\[a\]pprove"
STEP_QUESTION = r"\[y/N\]"


def _plan(*targets: str) -> str:
    return json.dumps(
        {
            "assumption": "two new modules are wanted",
            "confidence": 0.8,
            "steps": [
                {
                    "action": f"Add {t} with a NOTE constant",
                    "provider_hint": "local",
                    "expected_artifact": t,
                }
                for t in targets
            ],
        }
    )


def _scenario(*targets: str) -> Scenario:
    turns = [{"reply": {"kind": "text", "content": _plan(*targets)}}]
    turns += [{"reply": {"kind": "text", "content": 'NOTE = "two"\n'}} for _ in targets]
    turns += [{"reply": {"kind": "text", "content": "Done."}}] * 3
    return Scenario.from_dict({"turns": turns})


def _run(
    tmp_path: Path,
    argv: list[str],
    targets: tuple[str, ...],
    answers: list[tuple[str, str]],
):
    with FakeModelServer(_scenario(*targets)) as server:
        ws = rb._workspace(tmp_path, "b101", git=True, files=rb.CALC_FILES)
        rb._configure(ws, server.base_url, "fake-coder")
        session = spawn(
            [str(rb.RACT), *argv], cwd=str(ws), env=rb._env(), cols=100, rows=40
        )
        seen = []
        try:
            for pattern, reply in answers:
                seen.append(session.expect(pattern, timeout=120))
                session.send_line(reply)
        finally:
            # close() waits for the run to end (up to the timeout), then ends it.
            recording = session.close(timeout=180)
    return ws, seen, recording


ENTRY_POINTS = [["run", "add two notes modules"], ["add two notes modules"]]


@pytest.mark.parametrize("argv", ENTRY_POINTS, ids=["ract-run", "bare-ract"])
def test_a_plan_that_changes_files_asks_and_cancel_writes_nothing(
    tmp_path: Path, argv: list[str]
) -> None:
    ws, seen, recording = _run(
        tmp_path, argv, ("src/a.py", "src/b.py"), [(PLAN_QUESTION, "c")]
    )
    assert seen == [True], recording.plain[-2000:]
    assert not (ws / "src" / "a.py").exists() and not (ws / "src" / "b.py").exists()


@pytest.mark.parametrize("argv", ENTRY_POINTS, ids=["ract-run", "bare-ract"])
def test_approve_writes_the_plan(tmp_path: Path, argv: list[str]) -> None:
    ws, seen, recording = _run(
        tmp_path, argv, ("src/a.py", "src/b.py"), [(PLAN_QUESTION, "a")]
    )
    assert seen == [True], recording.plain[-2000:]
    assert (ws / "src" / "a.py").is_file() and (ws / "src" / "b.py").is_file()


def test_a_single_changing_step_asks_before_it_runs(tmp_path: Path) -> None:
    ws, seen, recording = _run(
        tmp_path, ["run", "add a notes module"], ("src/a.py",), [(STEP_QUESTION, "n")]
    )
    assert seen == [True], recording.plain[-2000:]
    assert not (ws / "src" / "a.py").exists()


def test_yolo_still_asks_nothing(tmp_path: Path) -> None:
    ws, _seen, recording = _run(
        tmp_path,
        ["run", "add two notes modules", "--yolo"],
        ("src/a.py", "src/b.py"),
        [],
    )
    assert "[a]pprove" not in recording.plain and "[y/N]" not in recording.plain
    assert (ws / "src" / "a.py").is_file()
