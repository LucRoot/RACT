"""B-097 (S2 D7, D9): the approval path says which step and how it ended.

D9: "Approval denied for step 1" named plan step 2's action (a 0-based index
in the message) and the hint sent the user to check the provider setup.
D7: a resumed run said "step 1 was interrupted" for a step that was refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract import run_checkpoint as rc
from ract import undo_backup
from ract.session_turn import hint_for
from tests.security.test_run_checkpoint import PLAN, _write


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "state"
    home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home))


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    return root


def _ended_run(ws: Path, outcome: str | None) -> dict:
    checkpoint = rc.RunCheckpoint(ws, "r1", "make util")
    with undo_backup.turn(ws), rc.recording(checkpoint):
        checkpoint.plan_ready(PLAN)
        rc.step_started(1)
        _write(ws, "src/util.py", b"one\n")
        rc.step_finished(1)
        rc.step_started(2)
        _write(ws, "src/util.py", b"two\n")
        if outcome is not None:
            rc.step_ended(2, outcome)
    loaded = rc.load(ws, "r1")
    assert loaded is not None
    return loaded


@pytest.mark.parametrize(
    ("outcome", "words"),
    [
        ("refused", "step 2 was refused;"),
        ("failed", "step 2 failed;"),
        (None, "step 2 was interrupted;"),
    ],
)
def test_the_resume_note_says_how_the_step_ended(
    ws: Path, state: None, outcome: str | None, words: str
) -> None:
    loaded = _ended_run(ws, outcome)
    reset = rc.reset_in_progress(ws, loaded)
    notes = rc.resume_notices(loaded, reset)
    assert notes[0] == "step 1 done earlier, not run again"
    assert notes[1].startswith(words), notes[1]
    assert "running it again" in notes[1]


def test_a_checkpoint_without_the_ended_key_is_still_read(
    ws: Path, state: None
) -> None:
    loaded = _ended_run(ws, None)
    assert "ended" not in loaded["in_progress"]


def test_an_ended_value_that_is_not_known_is_refused(ws: Path, state: None) -> None:
    import json

    _ended_run(ws, "refused")
    path = rc.RunCheckpoint(ws, "r1", "make util").path
    data = json.loads(path.read_text(encoding="utf-8"))
    data["in_progress"]["ended"] = "done"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(rc.CheckpointRefused, match="ended"):
        rc.load(ws, "r1")


def test_approval_denied_names_the_step_shown_and_a_matching_hint() -> None:
    from ract.executor.steps import Executor
    from ract.manager import Plan, Step
    from ract.providers.router import ProviderRouter

    plan = Plan(
        assumption="a",
        confidence=0.9,
        steps=[
            Step(action="Fix add", provider_hint="local", expected_artifact=""),
            Step(
                action="Create notes", provider_hint="local", expected_artifact="n.md"
            ),
        ],
    )
    asked: list[str] = []

    def approve(step: Step) -> bool:
        asked.append(step.action)
        return step.action != "Create notes"

    class Router(ProviderRouter):
        def __init__(self) -> None:
            pass

    executor = Executor(Router())
    executor._execute_provider_step_with_fallback = (  # type: ignore[method-assign]
        lambda *a, **k: _ok_answer()
    )
    result = executor.execute("intent", plan, approval_callback=approve)
    assert not result.is_ok()
    assert asked == ["Fix add", "Create notes"]
    assert result.error.startswith("Approval denied for step 2: Create notes")
    hint = hint_for(result.error)
    assert "approve" in hint and "doctor" not in hint


def _ok_answer():
    from ract.rooted import Rooted

    raw = {"choices": [{"message": {"content": "answer"}}]}
    return Rooted(value=(raw, "answer", {}), assumption="ok", confidence=1.0)
