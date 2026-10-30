"""B-110 D6: a tier-2 tool call asks the operator at the terminal, showing the change.

Only "y" or "yes" typed at the console runs the call. The change is shown with
secret-shaped values masked and control characters made visible, and no line
runs past the terminal at 40 columns.
"""

from __future__ import annotations

import pytest

from ract.approval_callback import console_tier_2_callback
from ract.tools.write import EditFileArgs, WriteFileArgs

WORKFLOW = WriteFileArgs(
    path=".github/workflows/ci.yml",
    content="on: push\njobs:\n  t:\n    run: echo \x1b[31mred\n",
    create=True,
)


def _answer(
    monkeypatch: pytest.MonkeyPatch, text: str | type[BaseException]
) -> list[str]:
    prompts: list[str] = []

    def read_line(prompt: str) -> str:
        prompts.append(prompt)
        if isinstance(text, type):
            raise text()
        return text

    monkeypatch.setattr("ract.approval_callback.read_line", read_line)
    return prompts


@pytest.mark.parametrize("typed", ["y", "yes", " Y "])
def test_yes_typed_at_the_terminal_allows_once(monkeypatch, typed: str) -> None:
    prompts = _answer(monkeypatch, typed)
    assert console_tier_2_callback("write_file", WORKFLOW) is True
    assert prompts == ["Allow this change? [y/s/N]: "]


@pytest.mark.parametrize("typed", ["", "n", "no", "always", "approved", "a"])
def test_anything_else_refuses(monkeypatch, typed: str) -> None:
    _answer(monkeypatch, typed)
    assert console_tier_2_callback("write_file", WORKFLOW) is False


def test_eof_refuses(monkeypatch) -> None:
    _answer(monkeypatch, EOFError)
    assert console_tier_2_callback("write_file", WORKFLOW) is False


def test_the_change_is_shown_masked_and_escaped(monkeypatch, capsys) -> None:
    _answer(monkeypatch, "n")
    key = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
    edit = EditFileArgs(
        path="AGENTS.md",
        old="token: old",
        new=f"token: {key}",
        expected_digest="0" * 64,
    )
    console_tier_2_callback("edit_file", edit)
    console_tier_2_callback("write_file", WORKFLOW)
    out = capsys.readouterr().out
    assert "Tier 2:" in out and "edit_file AGENTS.md" in out
    assert "-token: old" in out
    assert key not in out  # the key never reaches the screen
    assert "\x1b" not in out  # a control character in the change is made visible
    assert "write_file .github/workflows/ci.yml" in out


def test_no_line_runs_past_40_columns(monkeypatch, capsys) -> None:
    monkeypatch.setattr("ract.approval_callback._terminal_width", lambda: 40)
    _answer(monkeypatch, "n")
    long = WriteFileArgs(
        path=".github/workflows/" + "w" * 60 + ".yml",
        content="run: " + "x" * 120 + "\n",
        create=True,
    )
    console_tier_2_callback("write_file", long)
    for line in capsys.readouterr().out.splitlines():
        assert len(line) <= 40, line


# ------------------------------------------------------------------ for this session


def _session(tmp_path, session_id, answers):
    from ract.tier2_approvals import SessionApprovals

    asked: list[str] = []

    def ask(name, args, note):
        asked.append(note)
        return answers.pop(0)

    return SessionApprovals(tmp_path, session_id, ask), asked


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr("ract.core.keys._default_state_dir", lambda: tmp_path / "state")
    from ract import tier2_approvals

    tier2_approvals._LIVE.clear()
    yield tmp_path
    tier2_approvals._LIVE.clear()


def test_s_allows_the_same_file_for_the_rest_of_the_session(state) -> None:
    approve, asked = _session(state, "s-1", ["session"])
    assert approve("write_file", WORKFLOW) is True
    assert approve("write_file", WORKFLOW) is True  # not asked again
    assert asked == [""]
    other = WriteFileArgs(path=".envrc", content="x\n", create=True)
    approve.ask = lambda *_a: "deny"
    assert approve("write_file", other) is False  # another file still asks


def test_once_asks_again_next_time(state) -> None:
    approve, asked = _session(state, "s-1", ["once", "deny"])
    assert approve("write_file", WORKFLOW) is True
    assert approve("write_file", WORKFLOW) is False
    assert len(asked) == 2


def test_a_resumed_session_asks_again_and_says_why(state) -> None:
    from ract import tier2_approvals

    first, _ = _session(state, "s-0192", ["session"])
    assert first("write_file", WORKFLOW) is True
    tier2_approvals.forget("s-0192")  # /resume, or a new process
    again, asked = _session(state, "s-0192", ["deny"])
    assert again("write_file", WORKFLOW) is False
    assert asked == ["approvals from session s-0192 do not carry over"]


def test_the_record_on_disk_never_approves(state) -> None:
    from ract import tier2_approvals

    first, _ = _session(state, "s-1", ["session"])
    first("write_file", WORKFLOW)
    tier2_approvals.forget("s-1")
    assert tier2_approvals.recorded(state, "s-1") == {".github/workflows/ci.yml"}
    again, asked = _session(state, "s-1", ["deny"])
    assert again("write_file", WORKFLOW) is False and len(asked) == 1


def test_no_session_means_no_session_allowance(state) -> None:
    approve, asked = _session(state, None, ["session", "deny"])
    assert approve("write_file", WORKFLOW) is True
    assert approve("write_file", WORKFLOW) is False
    assert len(asked) == 2


def test_the_note_is_printed_before_the_change(monkeypatch, capsys) -> None:
    from ract.approval_callback import console_tier_2_choice

    _answer(monkeypatch, "s")
    choice = console_tier_2_choice(
        "write_file", WORKFLOW, "approvals from session s-9 do not carry over"
    )
    out = capsys.readouterr().out
    assert choice == "session"
    assert out.index("do not carry over") < out.index("Tier 2:")
    assert "y allows it once, s for this session, N refuses" in out
