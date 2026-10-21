"""`scripts/ci_parity.py` runs the same checks as the CI lint-format-type job.

A comment that says "keep in step" does not keep anything in step. This test
reads the workflow and fails when its lint, format or type-check commands and
the script's list differ.
"""

from __future__ import annotations

import importlib.util
import shlex
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def _load_script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "ci_parity", REPO / "scripts" / "ci_parity.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow_check_commands() -> list[list[str]]:
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["lint-format-type"]["steps"]
    commands: list[list[str]] = []
    for step in steps:
        run = step.get("run")
        if not run:
            continue
        for line in run.splitlines():
            argv = shlex.split(line)
            if argv and argv[0] in {"ruff", "mypy"}:
                commands.append(argv)
    return commands


def test_script_commands_match_the_ci_workflow() -> None:
    assert _load_script().CI_COMMANDS == _workflow_check_commands()


def test_non_linux_runs_type_checks_for_ci_platforms(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    module = _load_script()
    monkeypatch.setattr(sys, "platform", "win32")
    cmds = module.commands()
    assert ["mypy", "src"] not in cmds
    assert ["mypy", "src", "--platform", "linux"] in cmds
    assert ["mypy", "src", "--platform", "darwin"] in cmds
    monkeypatch.setattr(sys, "platform", "linux")
    cmds = module.commands()
    assert ["mypy", "src"] in cmds
    assert ["mypy", "src", "--platform", "linux"] not in cmds
