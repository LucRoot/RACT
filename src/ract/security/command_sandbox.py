"""Tier-3 commands under an enforcing sandbox where one exists (B-114 slice e, B-025, ADR-0048 D7).

LR:: The Linux backend renders a bubblewrap command; until now nothing ran
it. A tier-3 command now runs inside it when, and only when, this machine
has proved it confines: ``enforcing_backend`` resolves the backend for the
platform and runs a self-test inside it once per process (a write into a
read-only system folder must fail, a host file outside the workspace must
not be visible, only the loopback interface may exist, and the probe must
reach its end). If the backend is missing, or the self-test does not prove
both, nothing claims enforcement: the command runs as before, the grant must
say ``sandbox: best_effort`` and the interface says so. Windows has no
backend here (B-028 is its own card); macOS's Seatbelt profile is rendered
but not yet run, so macOS stays best effort too.

Inside the sandbox the step worktree is ``/workspace`` (read-write), the
system folders and the executable's own prefix are read-only, ``/tmp`` is
empty, the network is unshared unless the rule says ``network: true``, and
the environment is the command's (the same allowlist ``run_command``
builds) with HOME pointed at ``/tmp``.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

# Read-only inside the sandbox, so the usual tools and their libraries work.
SYSTEM_READ = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")
# The self-test (one shell line, POSIX sh): a write into a read-only system
# folder must fail, a host file outside the workspace must not be visible,
# and only the loopback interface may exist in an unshared network namespace.
SELF_TEST = (
    "touch /usr/ract-probe 2>/dev/null && echo WROTE; "
    '[ -e "$1" ] && echo SEEN; '
    '[ "$(grep -c : /proc/net/dev)" -le 1 ] || echo NET; '
    # In its own pid namespace the probe sees a handful of processes at most.
    '[ "$(ls /proc | grep -c "^[0-9]")" -le 8 ] || echo PROC; '
    "echo DONE"
)
_checked: dict[str, Any] = {}


def _prefix_binds(executable: str) -> list[str]:
    """What of *executable*'s install prefix is bound read-only.

    The path as given, not its link target: a venv's python links into /usr,
    while its packages sit under the venv. Only the prefix's bin and lib
    folders and a venv's ``pyvenv.cfg`` are bound, never the whole prefix
    (``~/.local`` would expose ``~/.local/share``).
    """
    path = Path(os.path.abspath(executable))
    if path.parent.name != "bin" or str(path.parent.parent) in ("/", "/usr"):
        return []
    prefix = path.parent.parent
    return [
        str(prefix / name)
        for name in ("bin", "lib", "lib64", "pyvenv.cfg")
        if (prefix / name).exists()
    ]


def manifest_for(run_id: str, *, network: bool, executable: str | None) -> Any:
    """The capability manifest a tier-3 command runs under."""
    from ract.security.manifest import CapabilityManifest

    read = list(SYSTEM_READ)
    for path in _prefix_binds(executable) if executable else []:
        if path not in read:
            read.append(path)
    return CapabilityManifest.model_validate(
        {
            "run_id": run_id,
            "filesystem": {"read": read, "write": []},
            "network": {"deny_default": not network, "allow_hosts": []},
        }
    )


def _self_test(backend: Any) -> str | None:
    """None when *backend* confines; else what the probe showed."""
    import subprocess
    import tempfile

    with (
        tempfile.TemporaryDirectory(prefix="ract-sandbox-probe-") as work,
        tempfile.TemporaryDirectory(prefix="ract-sandbox-outside-") as outside,
    ):
        marker = Path(outside) / "marker"
        marker.write_text("outside", encoding="utf-8")
        rendered = backend.render(
            manifest_for("self-test", network=False, executable=None),
            Path(work),
            ("/bin/sh", "-c", SELF_TEST, "probe", str(marker)),
        )
        try:
            done = subprocess.run(
                list(rendered.argv),
                env=rendered.env,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"the self-test did not run: {exc}"
    out = done.stdout.decode("utf-8", errors="replace")
    if "DONE" not in out:
        return f"the self-test did not finish (exit {done.returncode})"
    if "WROTE" in out:
        return "a write into a read-only system folder was not refused"
    if "SEEN" in out:
        return "a file outside the workspace was visible inside"
    if "NET" in out:
        return "the network namespace has more than the loopback interface"
    if "PROC" in out:
        return "the host's processes were visible inside"
    return None


def enforcing_backend(*, system: str | None = None) -> tuple[Any | None, str]:
    """``(backend, "")`` when commands run confined here; ``(None, why not)`` otherwise."""
    name = system or platform.system()
    if name in _checked:
        return _checked[name]
    from ract.security.sandbox import SandboxNotAvailable, resolve_backend

    result: tuple[Any | None, str]
    if name != "Linux":
        result = (
            None,
            "no backend runs commands confined on this platform yet "
            "(Windows: B-028; macOS: its profile is rendered, not run)",
        )
    else:
        try:
            backend = resolve_backend(platform_override=name)
        except SandboxNotAvailable as exc:
            result = (None, str(exc))
        else:
            why = _self_test(backend)
            result = (None, why) if why else (backend, "")
    _checked[name] = result
    return result


class SandboxedRunner:
    """Runs the command inside the enforcing backend, through the real runner."""

    name = "process"
    streams = True

    def __init__(self, backend: Any, *, network: bool, run_id: str) -> None:
        self.backend = backend
        self.network = network
        self.run_id = run_id
        self.sandbox = getattr(backend, "name", "sandbox")
        # The step worktree, set by run_command: mounted at /workspace, so a
        # rule's sub-folder cwd stays inside it.
        self.worktree: Path | None = None

    def run(
        self,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout_s: float,
        keep_bytes: int | None = None,
    ):
        from ract.tools.command import DEFAULT_OUTPUT_BYTES, ProcessRunner

        inside = {**env, "HOME": "/tmp", "TMPDIR": "/tmp"}
        for name in list(inside):
            if name.upper().startswith("XDG_"):
                inside[name] = "/tmp"
        setenv: list[str] = []
        for name, value in sorted(inside.items()):
            setenv += ["--setenv", name, value]
        worktree = Path(self.worktree or cwd)
        inner_cwd = "/workspace"
        try:
            rel = Path(cwd).resolve().relative_to(worktree.resolve())
            if rel.parts:
                inner_cwd = "/workspace/" + rel.as_posix()
        except ValueError:
            inner_cwd = "/workspace"  # a cwd outside the worktree starts at its top
        program = argv[0]
        try:
            # An executable inside the project is reached through the mount.
            inside_rel = Path(program).resolve().relative_to(worktree.resolve())
            program = "/workspace/" + inside_rel.as_posix()
        except (ValueError, OSError):
            program = argv[0]  # a system executable keeps its own path
        rendered = self.backend.render(
            manifest_for(self.run_id, network=self.network, executable=argv[0]),
            worktree,
            (*setenv, "--chdir", inner_cwd, program, *argv[1:]),
        )
        return ProcessRunner().run(
            list(rendered.argv),
            cwd=Path(cwd),
            env=rendered.env,
            timeout_s=timeout_s,
            keep_bytes=keep_bytes or DEFAULT_OUTPUT_BYTES,
        )


def runner_for(rule: Any, *, run_id: str = "") -> SandboxedRunner | None:
    """A sandboxed runner when this machine confines commands, else None."""
    backend, _why = enforcing_backend()
    if backend is None:
        return None
    return SandboxedRunner(
        backend,
        network=bool(getattr(rule, "network", False)),
        run_id=run_id or os.environ.get("RACT_RUN_ID", "") or "run",
    )


def _reset_for_tests() -> None:
    _checked.clear()


__all__ = [
    "SYSTEM_READ",
    "SandboxedRunner",
    "enforcing_backend",
    "manifest_for",
    "runner_for",
]
