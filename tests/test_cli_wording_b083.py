"""B-083: CLI wording and next actions (error sweep rows 2, 4, 9, 10; cold reader 3, 5, 6, 7).

Each command runs as a user would run it (a real ``ract`` process), and no
traceback reaches the screen.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ract.session_turn import hint_for


def _ract(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    # B-138: pin the terminal the child sees; the doctor table folds its
    # cells to the width, so an ambient COLUMNS/TERM decides whether a
    # phrase survives the flattening below.
    env["NO_COLOR"] = "1"
    env["COLUMNS"] = "64"
    proc = subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=120,
    )
    assert "Traceback" not in proc.stdout + proc.stderr
    return proc


def _config(ws: Path) -> None:
    (ws / "ract.yaml").write_text(
        "project:\n  name: demo\nmanager_provider: local\nproviders:\n"
        "  local:\n    adapter: local_http\n    url: http://127.0.0.1:9/v1\n",
        encoding="utf-8",
    )


def test_a_bad_option_is_one_line_and_a_next_action(tmp_path: Path) -> None:
    proc = _ract(tmp_path, "run", "--nope")
    assert proc.returncode == 2
    lines = [line for line in proc.stderr.splitlines() if line.strip()]
    assert lines == ["ract: unrecognized arguments: --nope", "Try: ract --help"]


def test_an_empty_intent_has_no_usage_block(tmp_path: Path) -> None:
    proc = _ract(tmp_path, "run", "")
    assert proc.returncode == 2
    assert "usage:" not in proc.stderr
    assert "intent is required" in proc.stderr and "Try: ract --help" in proc.stderr


def test_doctor_without_a_config_names_ract_setup(tmp_path: Path) -> None:
    proc = _ract(tmp_path, "doctor")
    # The table wraps its cells: compare with the borders and line breaks taken out.
    flat = " ".join((proc.stdout + proc.stderr).replace("│", " ").split())
    assert "Configuration file not found" in flat
    assert "Run `ract setup` here" in flat


def test_fence_without_a_config_names_ract_setup(tmp_path: Path) -> None:
    proc = _ract(tmp_path, "fence", "inspect", "--file", "logo.bin")
    assert proc.returncode == 1  # unchanged
    assert "hint: run `ract setup` here" in proc.stderr


def test_bare_ract_without_a_config_points_a_first_timer_at_setup(tmp_path: Path) -> None:
    proc = _ract(tmp_path)
    assert "first time here? Run ract setup" in proc.stderr
    # The advanced no-terminal path stays for scripts.
    assert "ract setup --answers FILE" in proc.stderr


def test_fence_on_a_missing_file_names_it(tmp_path: Path) -> None:
    _config(tmp_path)
    proc = _ract(tmp_path, "fence", "inspect", "--file", "src/hello.py")
    assert "no file named src/hello.py in this project" in proc.stderr


def test_a_file_name_with_escape_sequences_is_shown_escaped(tmp_path: Path) -> None:
    _config(tmp_path)
    proc = _ract(tmp_path, "fence", "inspect", "--file", "src/a\x1b[31m.py")
    assert "\x1b" not in proc.stdout + proc.stderr
    assert "no file named" in proc.stderr


def test_doctor_says_provenance_in_plain_words(tmp_path: Path) -> None:
    _config(tmp_path)
    proc = _ract(tmp_path, "doctor")
    out = " ".join(proc.stdout.split())
    assert "each file a run writes is signed" in out  # S-015b wired signing
    assert "Rootknot" not in proc.stdout


def test_the_novelty_budget_has_its_own_hint() -> None:
    hint = hint_for("Novelty budget exhausted: new_file (3pts). Increase budget ...")
    assert "--allow-novelty-overrun" in hint and "doctor" not in hint


def test_an_lsp_failure_is_a_log_line_not_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from ract.memory import lsp

    source = Path(lsp.__file__).read_text(encoding="utf-8")
    start = source.index("LspClient.references_of: LSP call failed")
    call = source[source.rindex("_LOGGER.", 0, start) : start]
    assert call.startswith("_LOGGER.debug(")
    with caplog.at_level(logging.WARNING, logger=lsp._LOGGER.name):
        lsp._LOGGER.debug("LspClient.references_of: LSP call failed for x")
    assert not caplog.records
