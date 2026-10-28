"""Package T: the hint for each Windows file error says what the user can do.

The messages are the ones the file cases printed (docs/ux/windows_files/). The hint mapping is
in the lane; the messages themselves are path and executor code (senior, see the handoffs).
A hint must never be the provider check for a file problem.
"""

from __future__ import annotations

import pytest

from ract.session_turn import hint_for


@pytest.mark.parametrize(
    "error",
    [
        "Step 1 not written: the path component 'CON' is a Windows device name",
        "Step 1 not written: the path component 'aux.txt' is a Windows device name",
    ],
)
def test_a_reserved_device_name_gets_a_file_name_hint(error):
    hint = hint_for(error)
    assert "doctor" not in hint and "provider" not in hint
    assert "name" in hint and "different" in hint


def test_a_name_ending_in_a_dot_or_space_gets_a_name_hint():
    hint = hint_for(
        "Step 1 not written: the path component 'notes.' ends in a dot or space, which Windows drops"
    )
    assert "doctor" not in hint
    assert "dot or space" in hint


def test_a_file_that_could_not_be_changed_gets_a_read_only_or_in_use_hint():
    hint = hint_for(
        "Step 1 left these paths as they are: src/calc.py (could not change it: Permission denied)."
    )
    assert "doctor" not in hint
    assert "read-only" in hint or "in use" in hint or "another program" in hint


def test_an_untracked_file_gets_a_commit_hint():
    hint = hint_for(
        "file is yours and untracked, so git has no copy to restore it from). The step's changes for them are in .ract/pending/abc.patch."
    )
    assert "doctor" not in hint
    assert "git" in hint and "commit" in hint


def test_a_snapshot_that_cannot_read_a_file_gets_a_close_the_program_hint():
    hint = hint_for(
        'could not snapshot the working tree: error: open("src/calc.py"): Permission denied'
    )
    assert "doctor" not in hint
    assert "another program" in hint or "close" in hint


def test_a_turn_that_raises_prints_one_sentence_not_a_traceback(
    tmp_path, monkeypatch, capsys
):
    # Package T: a worktree error (a locked file) escaped the turn's worker thread, and the
    # interpreter printed the traceback. The worker reports one sentence instead, so no
    # exception reaches the thread's hook.
    import threading
    from pathlib import Path

    from ract import cli
    from ract.repl import ReplSession
    from tests.test_repl import _Console

    def boom(*args, **kwargs):
        raise RuntimeError(
            "could not snapshot the working tree: open src/calc.py: Permission denied"
        )

    reported: list[object] = []
    monkeypatch.setattr(
        threading, "excepthook", lambda args: reported.append(args.exc_value)
    )
    monkeypatch.setattr("ract.session_turn.run_turn", boom)
    session = ReplSession(
        Path(tmp_path) / "ract.yaml",
        dispatch=None,
        read_line=lambda prompt: "",
        console=_Console(),
        verbs=cli.CLI_VERBS,
    )
    session._events = None
    code = session._event_turn("add a greeting", dry=True)
    assert session._worker_done is None or session._worker_done.wait(5)
    assert reported == [], reported
    assert code != 0


@pytest.mark.parametrize(
    "error",
    [
        'could not snapshot the working tree: error: open("src/calc.py"): Permission denied',
        "Step 1 left these paths as they are: src/calc.py (could not change it: Permission denied).",
    ],
)
def test_a_file_held_by_another_program_gets_a_close_it_hint(error):
    # Package T: a locked or read-only file got the provider check, which is not the cause.
    hint = hint_for(error)
    assert "doctor" not in hint and "provider" not in hint
    assert "close" in hint or "permission" in hint.lower()


def test_a_path_over_the_windows_limit_gets_a_shorter_name_hint():
    # Package 4 (H1): the long-path refusal got the provider-check hint.
    hint = hint_for(
        "Step 1 not written: the full path is 327 characters; Windows refuses paths of "
        "260 characters or more"
    )
    assert "doctor" not in hint and "provider" not in hint
    assert "shorter" in hint
