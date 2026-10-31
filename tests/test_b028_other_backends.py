"""B-028 (D-142): the wsl2 and container rule shapes, the WSL resolution, the container argv.

Every process goes through a fake runner: no WSL and no Docker are started,
and nothing is pulled.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ract.policy.grant import AllowRule
from ract.security.other_backends import (
    BackendUnavailable,
    ContainerBackend,
    resolve_in_wsl,
)

DIGEST = "a" * 64


def test_a_rule_runs_on_the_host_unless_it_says_otherwise() -> None:
    rule = AllowRule(id="tests", argv=["python", "-m", "pytest"])
    assert rule.backend == "host" and rule.image is None


def test_a_container_rule_needs_an_image_pinned_by_digest() -> None:
    ok = AllowRule(
        id="tests",
        argv=["python", "-m", "pytest"],
        backend="container",
        image=f"python:3.12-slim@sha256:{DIGEST}",
    )
    assert ok.image.endswith(DIGEST)
    for image in (None, "python:3.12-slim", f"python@sha256:{'a' * 63}"):
        with pytest.raises(ValueError, match="pinned by digest"):
            AllowRule(
                id="t",
                argv=["python", "-m", "pytest"],
                backend="container",
                image=image,
            )
    with pytest.raises(ValueError, match="belongs to a rule with backend: container"):
        AllowRule(id="t", argv=["python", "-m", "pytest"], image=f"x@sha256:{DIGEST}")


def _fake(*answers):  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []
    queue = list(answers)

    def run(argv, **_kw):  # type: ignore[no-untyped-def]
        calls.append(list(argv))
        code, out = queue.pop(0)
        return SimpleNamespace(returncode=code, stdout=out, stderr=b"")

    return run, calls


def test_a_wsl2_program_is_resolved_and_hashed_inside_wsl() -> None:
    run, calls = _fake(
        (0, "Ubuntu-24.04\r\n".encode("utf-16-le")), (0, b"/usr/bin/pytest\n")
    )
    read: list[str] = []

    def read_bytes(path: str) -> bytes:
        read.append(path)
        return b"#!/usr/bin/python3\n"

    program = resolve_in_wsl("pytest", run=run, read_bytes=read_bytes)
    assert program.distro == "Ubuntu-24.04" and program.linux_path == "/usr/bin/pytest"
    assert read == ["\\\\wsl$\\Ubuntu-24.04\\usr\\bin\\pytest"]
    assert program.sha256 == hashlib.sha256(b"#!/usr/bin/python3\n").hexdigest()
    # The name reaches the shell as an argument, never inside the script text.
    assert calls[1][-2:] == ["sh", "pytest"] and "pytest" not in calls[1][6]


def test_a_program_wsl_does_not_have_is_unavailable() -> None:
    run, _ = _fake((1, b""))
    with pytest.raises(BackendUnavailable, match="not on WSL's PATH"):
        resolve_in_wsl("nope", distro="Ubuntu", run=run)
    with pytest.raises(BackendUnavailable):
        resolve_in_wsl("bin/x", distro="Ubuntu", run=run)


def test_the_container_argv_has_no_network_a_read_only_root_and_the_worktree(
    tmp_path: Path,
) -> None:
    image = f"python:3.12-slim@sha256:{DIGEST}"
    run, calls = _fake((0, b"sha256:x"))
    argv = ContainerBackend(image, run=run).render(tmp_path, ["python", "-m", "pytest"])
    assert calls[0][:3] == ["docker", "image", "inspect"]
    assert argv[argv.index("--network") + 1] == "none"
    for flag in ("--read-only", "--rm", "--pull=never", "no-new-privileges"):
        assert flag in argv
    assert f"{tmp_path.resolve()}:/workspace" in argv
    assert argv[-4:] == [image, "python", "-m", "pytest"]


def test_an_image_that_is_not_here_is_never_pulled(tmp_path: Path) -> None:
    run, calls = _fake((1, b""))
    with pytest.raises(BackendUnavailable, match="pulls nothing"):
        ContainerBackend(f"x@sha256:{DIGEST}", run=run).render(tmp_path, ["true"])
    assert [c[:2] for c in calls] == [["docker", "image"]]


def test_a_wsl2_rule_is_refused_at_run_and_nothing_runs(
    tmp_path: Path, monkeypatch
) -> None:
    """Until its backend is wired, such a rule never runs on this host."""
    import os
    from datetime import datetime, timedelta, timezone

    from ract.policy import tier3
    from ract.policy.grant import sign
    from ract.policy.operator_key import generate, unlock
    from ract.tools import run_tool
    from ract.tools.command import ScriptedRunner

    cfg = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    root = tmp_path / "proj"
    (root / ".ract").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text(
        "def test_a():\n    pass\n", encoding="utf-8"
    )
    key = generate("throwaway passphrase for a test")
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    (root / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(root)}'\n"
        f"issued_at: {now:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {now + timedelta(days=30):%Y-%m-%dT%H:%M:%SZ}\n"
        f"key_id: {key.key_id}\nmax_mode: ask\nsandbox: best_effort\n"
        "commands:\n  allow:\n    - id: tests\n      argv: [python, -m, pytest]\n"
        "      backend: wsl2\n",
        encoding="utf-8",
    )
    sign(root, unlock("throwaway passphrase for a test"), key)
    runner = ScriptedRunner([{"exit_code": 0}])
    ctx = tier3.for_project(root, lambda facts: True, runner)
    with tier3.bound(ctx):
        rooted = run_tool(root, "run_tests", {})
    assert not rooted.is_ok()
    assert "backend wsl2" in rooted.error and "nothing ran" in rooted.error
    assert runner.calls == []
