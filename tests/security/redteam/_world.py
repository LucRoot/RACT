"""B-027: the hostile world every red-team module attacks from.

A temporary git project with a signed grant (a throwaway key in the test's
own config folder), a PATH of placeholder executables outside the project,
and a call helper that runs a tool inside a tier-3 context whose runner is
the scripted one: nothing here executes a command.
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ract.policy import tier3
from ract.policy.grant import sign
from ract.policy.operator_key import generate, unlock
from ract.tools import run_tool
from ract.tools.command import ScriptedRunner

PASS = "throwaway passphrase for a test"
RULES = (
    "    - id: tests\n      argv: [python, -m, pytest]\n"
    "    - id: build\n      argv: [python, -m, build]\n"
    "    - id: lint\n      argv: [ruff, check]\n"
    "    - id: typecheck\n      argv: [mypy]\n"
    "    - id: format\n      argv: [ruff, format, --check]\n"
)
EXECUTABLES = ("python", "ruff", "mypy", "sh", "bash", "git")


@dataclass
class World:
    project: Path
    bin_dir: Path
    key: Any

    def resign(
        self, *, days: int = 60, rules: str = RULES, max_mode: str = "allowlist"
    ) -> None:
        write_policy(self.project, self.key, days=days, rules=rules, max_mode=max_mode)
        sign(self.project, unlock(PASS), self.key)


def write_policy(root: Path, key: Any, *, days: int, rules: str, max_mode: str) -> None:
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    (root / ".ract").mkdir(exist_ok=True)
    (root / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(root)}'\n"
        f"issued_at: {now:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {now + timedelta(days=days):%Y-%m-%dT%H:%M:%SZ}\n"
        f"key_id: {key.key_id}\n"
        f"max_mode: {max_mode}\n"
        "sandbox: best_effort\n"
        f"commands:\n  allow:\n{rules}"
        "  deny:\n    - argv: [ruff, check, --fix]\n    - argv: [python, -m, pytest, --pdb]\n",
        encoding="utf-8",
    )


def build(tmp_path: Path, monkeypatch) -> World:
    cfg = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    root = tmp_path / "victim"
    (root / "tests").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "tests" / "test_calc.py").write_text(
        "def test_add():\n    pass\n", encoding="utf-8"
    )
    (root / "src" / "calc.py").write_text("x = 1\n", encoding="utf-8")
    (root / "conftest.py").write_text("", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "c"]):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
            cwd=root,
            check=True,
            capture_output=True,
        )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in EXECUTABLES:
        exe = bin_dir / (f"{name}.exe" if os.name == "nt" else name)
        exe.write_text("", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir))
    key = generate(PASS)
    world = World(root, bin_dir, key)
    world.resign(days=30)
    return world


def call(
    world: World,
    tool: str,
    args: dict | None = None,
    *,
    answer: Any = True,
    mode: str = "ask",
    runner: Any = None,
    written: tuple[str, ...] = (),
    expected_pin: str | None = None,
    sessions: Any = None,
):
    """Run *tool* in a tier-3 context; ``(rooted, asked, runner)``."""
    asked: list[dict] = []
    runner = runner or ScriptedRunner([{"exit_code": 0}])
    approve = (
        (lambda facts: asked.append(facts) or answer) if answer is not None else None
    )
    ctx = tier3.for_project(
        world.project,
        approve,
        runner,
        expected_pin=expected_pin,
        mode=mode,
        session_approvals=sessions,
    )
    ctx.model_written.update(written)
    with tier3.bound(ctx):
        rooted = run_tool(world.project, tool, args or {})
    return rooted, asked, runner


def nothing_ran(runner: Any) -> bool:
    return getattr(runner, "calls", []) == []
