"""B-114 (slice e, ADR-0048 D7): tier-3 commands run confined only where the machine proved it.

A fake backend stands in for bubblewrap: its render returns a Python child
that prints what the self-test would print. The real Linux evidence is
the run (B-046, decision D1).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ract.security import command_sandbox
from ract.security.sandbox_linux import BwrapCommand


@pytest.fixture(autouse=True)
def fresh():
    command_sandbox._reset_for_tests()
    yield
    command_sandbox._reset_for_tests()


class FakeBackend:
    name = "linux-bwrap"

    def __init__(self, prints: str) -> None:
        self.prints = prints
        self.rendered: list[tuple] = []

    def render(self, manifest, worktree, argv_to_run=()):
        self.rendered.append((manifest, worktree, tuple(argv_to_run)))
        return BwrapCommand(
            argv=(sys.executable, "-c", f"print({self.prints!r})"),
            env={"PATH": "/usr/bin"},
            seccomp_profile="strict",
        )


def _linux_with(monkeypatch, backend) -> None:
    monkeypatch.setattr("ract.security.sandbox.resolve_backend", lambda **kw: backend)


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_no_backend_claims_enforcement_off_linux(system: str) -> None:
    backend, why = command_sandbox.enforcing_backend(system=system)
    assert backend is None and "no backend runs commands confined" in why


def test_a_backend_that_passes_its_self_test_is_used(monkeypatch) -> None:
    fake = FakeBackend("DONE")
    _linux_with(monkeypatch, fake)
    backend, why = command_sandbox.enforcing_backend(system="Linux")
    assert backend is fake and why == ""
    manifest, _worktree, argv = fake.rendered[0]
    assert manifest.network.deny_default is True and argv[0] == "/bin/sh"


@pytest.mark.parametrize(
    "prints, why",
    [
        ("WROTE\nDONE", "read-only system folder"),
        ("SEEN\nDONE", "outside the workspace was visible"),
        ("NET\nDONE", "more than the loopback"),
        ("SHADOW\nDONE", "/etc/shadow was visible"),
        ("", "did not finish"),
    ],
)
def test_a_self_test_that_does_not_prove_confinement_claims_nothing(
    monkeypatch, prints: str, why: str
) -> None:
    _linux_with(monkeypatch, FakeBackend(prints))
    backend, reason = command_sandbox.enforcing_backend(system="Linux")
    assert backend is None and why in reason


def test_the_sandboxed_runner_puts_home_in_tmp_and_starts_in_the_workspace(
    tmp_path: Path,
) -> None:
    fake = FakeBackend("ok")
    runner = command_sandbox.SandboxedRunner(fake, network=False, run_id="r1")
    raw = runner.run(
        ["/usr/bin/python3", "-m", "pytest"],
        cwd=tmp_path,
        env={
            "HOME": "/home/operator",
            "XDG_CACHE_HOME": "/home/operator/.cache",
            "PATH": "/usr/bin",
        },
        timeout_s=30,
    )
    assert raw.exit_code == 0
    manifest, worktree, argv = fake.rendered[0]
    assert worktree == tmp_path and manifest.network.deny_default is True
    joined = list(argv)
    assert joined[joined.index("HOME") + 1] == "/tmp"
    assert joined[joined.index("XDG_CACHE_HOME") + 1] == "/tmp"
    assert joined[-5:] == ["--chdir", "/workspace", "/usr/bin/python3", "-m", "pytest"]


def test_a_rule_with_network_on_shares_the_network() -> None:
    argv = ["bwrap", "--unshare-pid", "--unshare-net", "--new-session", "x"]
    assert command_sandbox.share_network(list(argv), True)[2] == "--share-net"
    assert command_sandbox.share_network(list(argv), False) == argv


def test_run_command_records_the_sandbox_when_confined(tmp_path: Path) -> None:
    from ract.policy.matcher import Match
    from ract.tools.command import run_command

    class Rule:
        id = "tests"
        cwd = "step_worktree"
        timeout_s = 60
        max_output_bytes = 4096
        home = "isolated"
        env_extra: list[str] = []

    runner = command_sandbox.SandboxedRunner(
        FakeBackend("1 passed"), network=False, run_id="r"
    )
    match = Match(
        "matches", "the rule tests", ("python", "-m", "pytest"), sys.executable, "tests"
    )
    result = run_command(
        match, worktree=tmp_path, rule=Rule(), runner=runner, project=tmp_path
    ).unwrap()
    assert result.enforced is True and result.sandbox == "linux-bwrap"
    assert result.network == "off"
    assert any("runs inside linux-bwrap" in note for note in result.notes)


def test_this_machine_without_a_backend_stays_best_effort() -> None:
    import platform

    from ract.policy.grant import sandbox_confines_commands

    if platform.system() == "Linux":
        pytest.skip("depends on bwrap on this Linux machine")
    assert sandbox_confines_commands() is False


def test_doctor_says_how_tier3_commands_run() -> None:
    from ract.doctor import sandbox_status

    assert "not confined" in sandbox_status("Windows").properties["tier-3 commands"]


def test_the_render_has_its_own_pid_namespace_and_dies_with_bwrap(
    tmp_path: Path,
) -> None:
    """Review findings 4 and 5."""
    from ract.security.sandbox_linux import LinuxSandbox

    backend = LinuxSandbox.__new__(LinuxSandbox)
    backend.bwrap_path = "/usr/bin/bwrap"
    manifest = command_sandbox.manifest_for("r", network=False, executable=None)
    argv = backend.render(manifest, tmp_path, ("/bin/true",)).argv
    for flag in ("--unshare-pid", "--die-with-parent", "--unshare-net"):
        assert flag in argv
    assert argv.index("--unshare-pid") < argv.index("--proc")


def test_a_sub_folder_cwd_stays_in_the_mounted_worktree(tmp_path: Path) -> None:
    """Review finding 6."""
    fake = FakeBackend("ok")
    runner = command_sandbox.SandboxedRunner(fake, network=False, run_id="r")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "scripts").mkdir()
    tool = tmp_path / "scripts" / "check"
    tool.write_text("", encoding="utf-8")
    runner.worktree = tmp_path
    runner.run([str(tool), "-q"], cwd=tmp_path / "pkg", env={}, timeout_s=5)
    _manifest, worktree, argv = fake.rendered[0]
    assert worktree == tmp_path
    assert (
        list(argv)[-4:]
        == ["--chdir", "/workspace/pkg", "/workspace/scripts/check", "-q"][-4:]
    )


def test_only_the_prefix_bin_and_lib_are_bound(tmp_path: Path) -> None:
    prefix = tmp_path / "home" / ".local"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib").mkdir()
    (prefix / "share").mkdir()
    binds = command_sandbox._prefix_binds(str(prefix / "bin" / "pytest"))
    assert str(prefix / "bin") in binds and str(prefix / "lib") in binds
    assert not [b for b in binds if b.endswith("share")] and str(prefix) not in binds


def test_etc_is_bound_entry_by_entry_and_resolution_only_with_the_network(
    tmp_path: Path,
) -> None:
    """G-237 L3: /etc whole showed /etc/shadow to a command run as root."""
    from ract.security.sandbox_linux import LinuxSandbox

    backend = LinuxSandbox.__new__(LinuxSandbox)
    backend.bwrap_path = "/usr/bin/bwrap"
    for network in (False, True):
        manifest = command_sandbox.manifest_for("r", network=network, executable=None)
        argv = list(backend.render(manifest, tmp_path, ("/bin/true",)).argv)
        bound = {argv[i + 1] for i, a in enumerate(argv) if a.startswith("--ro-bind")}
        assert "/etc" not in bound and "/etc/shadow" not in bound
        assert {"/etc/ld.so.cache", "/etc/ssl/certs", "/etc/passwd"} <= bound
        assert ("/etc/resolv.conf" in bound) is network
