"""B-202 (part 1): a YAML error names the line and column; the line's text is never printed.

``str()`` of a YAML error quotes the offending line, so a literal key on a
broken ``ract.yaml`` line reached the screen through every place that printed
the error (the CLI's config loads, doctor, headless, preflight, the session,
setup's answers file). The key here is a throwaway value.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from ract import config_errors, harness
from ract.preflight_validator import PreflightValidator

KEY = "sk-b202-" + "V" * 28
BROKEN = (
    f"providers:\n  local:\n    api_key: {KEY}: oops\n    url: http://127.0.0.1:9/v1\n"
)


def _error() -> yaml.YAMLError:
    try:
        yaml.safe_load(BROKEN)
    except yaml.YAMLError as exc:
        return exc
    raise AssertionError("the YAML was expected to be broken")


def test_the_raw_error_quotes_the_key_and_the_helper_does_not() -> None:
    exc = _error()
    piece = KEY[5:]  # the snippet trims the line's start, the key is still there
    assert piece in str(exc)  # what the printers showed
    shown = config_errors.yaml_problem(exc)
    assert piece not in shown and shown.startswith("line 3, column ")


def test_the_config_load_names_the_line_only(tmp_path: Path) -> None:
    config = tmp_path / "ract.yaml"
    config.write_text(BROKEN, encoding="utf-8")
    loaded = harness._load_config(config)
    assert not loaded.is_ok() and KEY[5:] not in (loaded.error or "")
    assert "line 3" in (loaded.error or "")


def test_preflight_names_the_line_only(tmp_path: Path) -> None:
    config = tmp_path / "ract.yaml"
    config.write_text(BROKEN, encoding="utf-8")
    errors = PreflightValidator(config).validate()
    assert errors and all(KEY[5:] not in e["message"] for e in errors)


def test_doctor_never_prints_the_broken_line(tmp_path: Path) -> None:
    (tmp_path / "ract.yaml").write_text(BROKEN, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env.update(NO_COLOR="1", RACT_NO_NETWORK="1")
    done = subprocess.run(
        [sys.executable, "-m", "ract.cli", "doctor", "--config", "ract.yaml"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
    )
    assert KEY[5:] not in done.stdout + done.stderr
    assert "line 3" in done.stdout + done.stderr
