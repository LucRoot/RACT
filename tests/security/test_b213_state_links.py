"""B-213: no writer of RACT's state follows a link or junction under ``.ract``.

``MemoryArena.save`` wrote with no link check although ``load`` refused links.
Repro on c191903: a junction ``.ract/memory -> outside``; ``load`` gave an
empty arena, then ``save`` wrote ``outside/s1.json``. Every state writer now
calls ``workspace_state.check_state_path`` first. Junctions need no privilege
on Windows; elsewhere a symlink stands in.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ract.manager import Plan, Step
from ract.memory_arena import MemoryArena, MemoryArenaError
from ract.plan_replay import PlanReplay
from ract.session_store import SessionStore
from ract.workspace_state import StateDirRefused, check_state_path


def _dir_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            pytest.skip(f"no junction here: {done.stdout.strip()} {done.stderr.strip()}")
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.fixture(params=[".ract", ".ract/memory"])
def linked(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[Path, Path, str]:
    """A project whose ``.ract`` (or ``.ract/memory``) is a link to a folder outside it."""
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / request.param
    link.parent.mkdir(parents=True, exist_ok=True)
    _dir_link(link, outside)
    return root, outside, request.param


def _nothing_outside(outside: Path) -> None:
    assert [p.name for p in outside.rglob("*")] == []


def test_the_memory_arena_is_not_saved_through_a_link(linked) -> None:  # type: ignore[no-untyped-def]
    root, outside, _ = linked
    arena = MemoryArena()
    with pytest.raises(MemoryArenaError, match="link or a junction"):
        arena.save(root / ".ract" / "memory" / "s1.json")
    _nothing_outside(outside)


def test_a_plan_is_not_saved_through_a_link(linked) -> None:  # type: ignore[no-untyped-def]
    root, outside, _ = linked
    plan = Plan(assumption="a", confidence=1.0, steps=[Step(action="x", provider_hint="", expected_artifact="")])
    with pytest.raises(StateDirRefused):
        PlanReplay().save(plan, root / ".ract" / "memory" / "plan.json")
    _nothing_outside(outside)


def test_a_session_is_not_saved_through_a_link(linked) -> None:  # type: ignore[no-untyped-def]
    root, outside, _ = linked
    with pytest.raises(StateDirRefused):
        SessionStore(root / ".ract" / "memory").save("s1", {"turns": []})
    _nothing_outside(outside)


@pytest.mark.parametrize(
    "rel",
    [
        ".ract/pending/abc.patch",  # worktree.apply's skipped-path patch
        ".ract/runs/r1.json",  # run_checkpoint
        ".ract/undo/t1/manifest.json",  # undo_backup
        ".ract/memory/s1.json",
    ],
)
def test_every_state_path_under_a_linked_ract_is_refused(tmp_path: Path, rel: str) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    _dir_link(root / ".ract", outside)
    with pytest.raises(StateDirRefused, match="remove it and RACT makes a plain folder"):
        check_state_path(root / rel)


def test_a_plain_ract_folder_is_written_as_before(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".ract" / "memory").mkdir(parents=True)
    MemoryArena().save(root / ".ract" / "memory" / "s1.json")
    assert (root / ".ract" / "memory" / "s1.json").is_file()
    check_state_path(tmp_path / "elsewhere" / "file.json")  # not RACT's state: no check


def _linked_ract(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    _dir_link(root / ".ract", outside)
    return root, outside


def test_repl_history_load_and_save_take_the_state_path_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Audit round 2 (seam 6 P2): the REPL read and appended .ract/repl_history
    # with no check_state_path, so a repo-shipped link got the operator's typed
    # commands (which routinely hold keys and paths) on exit, and could plant
    # fake history that the session loads.
    from ract import repl

    root, outside = _linked_ract(tmp_path)
    (outside / "repl_history").write_text("planted fake history\n", encoding="utf-8")
    monkeypatch.chdir(root)
    session = repl.ReplSession.__new__(repl.ReplSession)
    session._history_path = Path(".ract") / "repl_history"
    session._save_history()
    note = capsys.readouterr().err
    assert "history" in note  # one-line stderr note; the feature degrades, no crash
    assert repl._history_path_or_disabled(Path(".ract") / "repl_history") is None
    assert (outside / "repl_history").read_text(encoding="utf-8") == (
        "planted fake history\n"
    )


def test_repl_history_path_is_kept_in_a_plain_ract_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract import repl

    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.chdir(root)
    kept = repl._history_path_or_disabled(Path(".ract") / "repl_history")
    assert kept == Path(".ract") / "repl_history"


def test_the_other_state_writers_refuse_a_linked_ract(tmp_path: Path) -> None:
    # B-213 part 2: the error memory, the refactor ledger and the session
    # snapshots write directly under .ract.
    from ract.error_memory import ErrorMemory
    from ract.refactor_ledger import RefactorLedger
    from ract.session_rollback import SessionRollback

    root, outside = _linked_ract(tmp_path)
    (outside / "error_memory.jsonl").write_text('{"pattern": "kept"}\n', encoding="utf-8")
    with pytest.raises(StateDirRefused):
        ErrorMemory(root).clear()
    assert (outside / "error_memory.jsonl").read_text(encoding="utf-8") != ""
    with pytest.raises(StateDirRefused):
        RefactorLedger(project_dir=root).save()
    with pytest.raises(StateDirRefused):
        SessionRollback(root)
    assert sorted(p.name for p in outside.iterdir()) == ["error_memory.jsonl"]
