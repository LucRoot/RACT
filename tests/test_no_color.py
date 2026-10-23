"""B-041a: NO_COLOR and --no-color remove every color and escape byte.

Each case runs RACT in a child process so the console is built the way a user's
shell builds it. FORCE_COLOR makes Rich write color even when the output is a
pipe, which is what makes these tests meaningful.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ESC = "\x1b"


def _run(cwd: Path, args: list[str], code: str | None = None, **env: str) -> str:
    base = {
        key: value
        for key, value in os.environ.items()
        if key not in {"NO_COLOR", "FORCE_COLOR", "TERM"}
    }
    base.update(env)
    if code is None:
        code = "import sys; from ract.cli import main; sys.exit(main(sys.argv[1:]))"
        command = [sys.executable, "-c", code, *args]
    else:
        command = [sys.executable, "-c", code]
    proc = subprocess.run(
        command,
        cwd=cwd,
        env=base,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    return proc.stdout + proc.stderr


def test_no_color_wins_over_forced_color(tmp_path: Path) -> None:
    out = _run(tmp_path, ["doctor"], NO_COLOR="1", FORCE_COLOR="1")
    assert ESC not in out


def test_forced_color_without_no_color_keeps_color(tmp_path: Path) -> None:
    out = _run(tmp_path, ["doctor"], FORCE_COLOR="1")
    assert ESC in out


def test_empty_no_color_is_treated_as_unset(tmp_path: Path) -> None:
    out = _run(tmp_path, ["doctor"], NO_COLOR="", FORCE_COLOR="1")
    assert ESC in out


@pytest.mark.parametrize("args", [["--no-color", "doctor"], ["doctor", "--no-color"]])
def test_no_color_flag_works_before_and_after_the_subcommand(
    tmp_path: Path, args: list[str]
) -> None:
    out = _run(tmp_path, args, FORCE_COLOR="1")
    assert ESC not in out
    assert "config_exists" in out or "FAIL" in out


def test_plain_mode_draws_tables_with_plain_characters(tmp_path: Path) -> None:
    out = _run(tmp_path, ["doctor"], NO_COLOR="1")
    assert "+" in out
    assert "│" not in out
    assert "─" not in out


def test_a_failing_check_keeps_its_word_without_color(tmp_path: Path) -> None:
    out = _run(tmp_path, ["doctor"], NO_COLOR="1")
    assert "FAIL" in out
    assert "config_exists" in out


def test_clear_writes_no_escape_when_color_is_off(tmp_path: Path) -> None:
    code = (
        "from pathlib import Path\n"
        "from ract.repl import ReplSession\n"
        "ReplSession(Path('ract.yaml')).handle('/clear')\n"
    )
    out = _run(tmp_path, [], code=code, NO_COLOR="1")
    assert ESC not in out


def test_clear_still_clears_the_screen_when_color_is_on(tmp_path: Path) -> None:
    code = (
        "from pathlib import Path\n"
        "from ract.repl import ReplSession\n"
        "ReplSession(Path('ract.yaml')).handle('/clear')\n"
    )
    out = _run(tmp_path, [], code=code, FORCE_COLOR="1")
    assert f"{ESC}[2J" in out


def test_help_under_no_color_has_no_escape_and_lists_commands(tmp_path: Path) -> None:
    code = (
        "from pathlib import Path\n"
        "from ract.repl import ReplSession\n"
        "ReplSession(Path('ract.yaml')).handle('/help')\n"
    )
    out = _run(tmp_path, [], code=code, NO_COLOR="1", FORCE_COLOR="1")
    assert ESC not in out
    assert "/sessions" in out


def test_source_writes_escapes_only_from_the_renderer_and_the_console() -> None:
    offenders = []
    for path in (ROOT / "src" / "ract").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if '"\\033[' in text or '"\\x1b[' in text:
            if path.name not in {"session_render.py", "tui.py"}:
                offenders.append(path.name)
    assert offenders == []
