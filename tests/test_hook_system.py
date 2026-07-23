from __future__ import annotations


import sys
from pathlib import Path
from typing import cast

from ract.hook_system import HookManager


def test_register_persists_hook(tmp_path: Path) -> None:
    manager = HookManager(tmp_path)
    manager.register("pre", "echo", ["echo", "hello"])
    hook_path = tmp_path / "pre_echo.json"
    assert hook_path.exists()


def test_run_hooks_execute_in_order(tmp_path: Path) -> None:
    manager = HookManager(tmp_path)
    manager.register("pre", "a", ["echo", "a"])
    manager.register("pre", "b", ["echo", "b"])
    results = manager.run_hooks("pre", {})
    assert len(results) == 2
    assert cast(str, results[0]["stdout"]).strip() == "a"
    assert cast(str, results[1]["stdout"]).strip() == "b"


def test_context_passed_as_env_vars(tmp_path: Path) -> None:
    manager = HookManager(tmp_path)
    if sys.platform == "win32":
        manager.register("pre", "env", ["cmd", "/c", "echo %RACT_FOO%"])
    else:
        manager.register("pre", "env", ["sh", "-c", "echo $RACT_FOO"])
    results = manager.run_hooks("pre", {"foo": "bar"})
    assert cast(str, results[0]["stdout"]).strip() == "bar"


def test_unknown_phase_returns_empty(tmp_path: Path) -> None:
    manager = HookManager(tmp_path)
    assert manager.run_hooks("post", {}) == []


def test_failed_hook_reports_error(tmp_path: Path) -> None:
    manager = HookManager(tmp_path)
    if sys.platform == "win32":
        manager.register("pre", "fail", ["cmd", "/c", "exit 1"])
    else:
        manager.register("pre", "fail", ["false"])
    results = manager.run_hooks("pre", {})
    assert len(results) == 1
    assert results[0]["returncode"] == 1


def test_missing_command_reports_not_found(tmp_path: Path) -> None:
    manager = HookManager(tmp_path)
    manager.register("pre", "missing", ["__definitely_not_a_command__"])
    results = manager.run_hooks("pre", {})
    assert len(results) == 1
    assert results[0]["returncode"] == 127


# RACT 0.1.1 - Trust and tooling
