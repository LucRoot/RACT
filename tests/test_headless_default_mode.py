"""B-034 part 3: `ract -p` starts in `default` mode too.

`default` asks before a step that changes a file. A headless run has no
terminal to ask, so it refuses the change with exit 3 and names the flag
that lets the run change files (`--accept-edits`). An answer needs no flag.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.test_headless import _ract, _scenario
from tests.test_session_turn import _repo


def test_a_change_is_refused_without_accept_edits(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_text(encoding="utf-8")

    result = _ract(ws, "-p", "fix add", "--output-format", "json")

    assert result.returncode == 3, result.stderr
    obj = json.loads(result.stdout)
    assert obj["exit_code"] == 3 and obj["changed"] == []
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == before
    hints = [line for line in result.stderr.splitlines() if "hint:" in line]
    assert any("--accept-edits" in line for line in hints), result.stderr
    assert "src/calc.py" in result.stderr  # the refusal names the file


def test_accept_edits_lets_the_run_change_files(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "--accept-edits", "fix add", "--output-format", "json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["changed"] == ["src/calc.py"]
    assert "return a + b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")


def test_an_answer_needs_no_flag(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server(_scenario("The loader is in src/calc.py."))
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "--ask", "where is the loader?")

    assert result.returncode == 0, result.stderr
    assert "src/calc.py" in result.stdout
