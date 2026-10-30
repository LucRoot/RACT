"""``run_command``'s core: one argv run under a grant rule, recorded (ADR-0048 D5, D10).

LR:: The command runs as the matcher resolved it, never through a shell:
``shell=False``, stdin closed, the scrubbed ``sandbox_env`` allowlist plus
the rule's ``env_extra`` (minus ``NEVER_PASSTHROUGH`` and every ``RACT_*``
name except ``RACT_RUN_ID``), the home folders pointed at a per-step
temporary folder unless the rule says ``home: real``, ``cwd`` pinned to the
step worktree or a folder inside it, and a hard wall-clock timeout after
which the whole process tree is killed. Output is kept up to a cap per
stream: a cut shows the head, the tail and how many bytes were dropped, and
escape sequences never reach the model or the operator.

What this machine does not enforce is said, not implied: no backend
confines commands yet (slice e), so the process, memory and CPU limits and
"network off" are not enforced here; network off is asked of the command
through its proxy settings only. The result carries D10's fields; the
record goes to the step's ``commands.jsonl`` in the user state folder and
is not part of the signed Rootknot (ADR-0048 D10: "command records are in
the trace; they are not part of the signed Rootknot").

``runner`` runs the process. Tests and walkthroughs use a fake runner that
executes nothing (D-117: commands run only under the policy, never in a
test); a result from it says ``runner: fake`` so it can never read as a
real test run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ract.rooted import Rooted
from ract.session_events import safe_text

DEFAULT_TIMEOUT_S = 300
DEFAULT_OUTPUT_BYTES = 1_048_576
_ANSI = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]"
)
_HOME_NAMES = (
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
)
TRACE_NOTE = (
    "command records are in the trace; they are not part of the signed Rootknot"
)


@dataclass(frozen=True)
class RawRun:
    """What a runner observed: the exit code, both streams, the time, and a kill."""

    exit_code: int | None
    stdout: bytes
    stderr: bytes
    duration_ms: int
    killed_by: str | None = None


class CommandRunner(Protocol):
    name: str

    def run(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float
    ) -> RawRun: ...


class ProcessRunner:
    """Runs the process for real: ``process_group.spawn`` and ``kill_tree`` on timeout."""

    name = "process"

    def run(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float
    ) -> RawRun:
        from ract.executor.process_group import kill_tree, spawn

        started = time.monotonic()
        handle = spawn(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL)
        try:
            out, err = handle.popen.communicate(timeout=timeout_s)
            killed = None
        except subprocess.TimeoutExpired:
            kill_tree(handle, grace_period_seconds=2.0)
            out, err = handle.popen.communicate()
            killed = "timeout"
        return RawRun(
            handle.popen.returncode,
            out or b"",
            err or b"",
            int((time.monotonic() - started) * 1000),
            killed,
        )


class ScriptedRunner:
    """Runs nothing: answers each command from a script (tests and walkthroughs).

    Selected only by ``RACT_FAKE_RUNNER`` (a JSON list of ``{exit_code,
    stdout, stderr}``, used in order, the last repeated). Every result it
    gives says ``runner: fake``, and a fake run never makes a turn verified.
    """

    name = "fake"

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self.script = list(script) or [{"exit_code": 0}]
        self.calls: list[dict[str, Any]] = []

    def run(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float
    ) -> RawRun:
        self.calls.append({"argv": list(argv), "cwd": str(cwd), "env": dict(env)})
        step = self.script[0] if len(self.script) == 1 else self.script.pop(0)
        return RawRun(
            step.get("exit_code", 0),
            str(step.get("stdout", "")).encode("utf-8"),
            str(step.get("stderr", "")).encode("utf-8"),
            int(step.get("duration_ms", 5)),
            step.get("killed_by"),
        )


def default_runner() -> CommandRunner:
    """The real runner, or the scripted one when ``RACT_FAKE_RUNNER`` names a script."""
    script = os.environ.get("RACT_FAKE_RUNNER")
    if not script:
        return ProcessRunner()
    try:
        steps = json.loads(Path(script).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"RACT_FAKE_RUNNER does not name a readable script: {exc}"
        ) from exc
    return ScriptedRunner(steps if isinstance(steps, list) else [])


@dataclass(frozen=True)
class CommandResult:
    """D10: what is recorded for a command (values of environment variables never)."""

    argv: list[str]
    executable: str
    executable_sha256: str | None
    cwd: str
    env_names: list[str]
    env_allowlist_digest: str
    grant_digest: str | None
    rule_id: str | None
    approval_id: str | None
    approver: str | None
    sandbox: str
    enforced: bool
    limits: dict[str, Any]
    network: str
    runner: str
    exit_code: int | None
    duration_ms: int
    killed_by: str | None
    stdout: str
    stderr: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_truncated: bool
    stderr_truncated: bool
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and self.killed_by is None


def cap_output(data: bytes, cap: int) -> tuple[str, bool]:
    """The stream as text for the model and the operator: stripped, capped head and tail."""
    text = data.decode("utf-8", errors="replace")
    text = safe_text(_ANSI.sub("", text).replace("\r\n", "\n"))
    raw = text.encode("utf-8")
    if len(raw) <= cap:
        return text, False
    half = max(cap // 2, 1)
    head = raw[:half].decode("utf-8", errors="ignore")
    tail = raw[-half:].decode("utf-8", errors="ignore")
    dropped = len(raw) - 2 * half
    return f"{head}\n[cut: {dropped} bytes dropped]\n{tail}", True


def command_env(
    env_extra: list[str],
    home: str,
    step_home: Path,
    process_env: dict[str, str] | None = None,
) -> tuple[dict[str, str], str]:
    """The environment for a command, and the digest of the allowlist that made it."""
    from ract.security.sandbox_env import NEVER_PASSTHROUGH, build_sandbox_env

    source = dict(os.environ if process_env is None else process_env)
    built = build_sandbox_env(
        process_env=source, manifest_passthrough=tuple(env_extra), allowlist_file=None
    )
    # D5: RACT_RUN_ID is the one RACT_* name a command keeps.
    run_id = {"RACT_RUN_ID": source["RACT_RUN_ID"]} if "RACT_RUN_ID" in source else {}
    env = run_id | {
        k: v
        for k, v in built.env.items()
        if k not in NEVER_PASSTHROUGH
        and (not k.upper().startswith("RACT_") or k == "RACT_RUN_ID")
    }
    if home != "real":
        step_home.mkdir(parents=True, exist_ok=True)
        for name in _HOME_NAMES:
            env[name] = str(step_home)
        for name in list(env):
            if name.upper().startswith("XDG_"):
                env[name] = str(step_home)
    digest = hashlib.sha256(
        json.dumps(sorted(env), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return env, digest


def _sha256_file(path: str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        print(f"[command] the executable was not hashed: {exc}", flush=True)
        return None


def run_command(
    match: Any,
    *,
    worktree: Path,
    rule: Any = None,
    grant_digest: str | None = None,
    approval_id: str | None = None,
    approver: str | None = None,
    runner: CommandRunner | None = None,
    network: bool = False,
    timeout_s: float | None = None,
    max_output_bytes: int | None = None,
    process_env: dict[str, str] | None = None,
    project: Path | None = None,
) -> Rooted[CommandResult]:
    """Run the command *match* resolved, under *rule*, in *worktree* (D5).

    The caller has already decided: the matcher did not refuse, the grant
    holds, and the operator approved where approval is needed. Limits from
    the rule are ceilings; *timeout_s* and *max_output_bytes* only lower them.
    """
    runner = runner or default_runner()
    worktree = Path(worktree)
    cwd = worktree
    rule_cwd = getattr(rule, "cwd", "step_worktree") or "step_worktree"
    if rule_cwd.startswith("step_worktree/"):
        cwd = (worktree / rule_cwd.split("/", 1)[1]).resolve()
        try:
            cwd.relative_to(worktree.resolve())
        except ValueError:
            return Rooted(
                value=None,
                assumption="cwd stays in the step worktree",
                confidence=0.0,
                provenance=["tools.command"],
                error="the rule's cwd leaves the step worktree",
                hint="fix the rule's cwd in .ract/policy.yaml",
            )
    ceiling_s = float(
        getattr(rule, "timeout_s", DEFAULT_TIMEOUT_S) or DEFAULT_TIMEOUT_S
    )
    wall = min(ceiling_s, timeout_s) if timeout_s else ceiling_s
    ceiling_out = int(
        getattr(rule, "max_output_bytes", DEFAULT_OUTPUT_BYTES) or DEFAULT_OUTPUT_BYTES
    )
    cap = min(ceiling_out, max_output_bytes) if max_output_bytes else ceiling_out
    step_home = Path(tempfile.mkdtemp(prefix="ract-step-home-"))
    env, env_digest = command_env(
        list(getattr(rule, "env_extra", []) or []),
        getattr(rule, "home", "isolated") or "isolated",
        step_home,
        process_env,
    )
    notes = [
        "no sandbox confines commands on this machine: process, memory and CPU limits "
        "are not enforced; the wall-clock timeout is",
    ]
    if not network:
        # Asked of the command, not enforced (no backend yet): an unreachable proxy.
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "ALL_PROXY",
        ):
            env[name] = "http://127.0.0.1:9"
        env["NO_PROXY"] = ""
        notes.append(
            "network off is asked of the command through its proxy, not enforced"
        )
    argv = (
        [match.executable, *list(match.argv)[1:]]
        if match.executable
        else list(match.argv)
    )
    raw = runner.run(argv, cwd=cwd, env=env, timeout_s=wall)
    stdout, out_cut = cap_output(raw.stdout, cap)
    stderr, err_cut = cap_output(raw.stderr, cap)
    if runner.name == "fake":
        notes.append("fake runner: no command ran")
    result = CommandResult(
        argv=list(match.argv),
        executable=match.executable or "",
        executable_sha256=_sha256_file(match.executable) if match.executable else None,
        cwd=cwd.relative_to(worktree.resolve()).as_posix() if cwd != worktree else ".",
        env_names=sorted(env),
        env_allowlist_digest=env_digest,
        grant_digest=grant_digest,
        rule_id=getattr(rule, "id", None),
        approval_id=approval_id,
        approver=approver,
        sandbox="none",
        enforced=False,
        limits={"wall_s": wall, "output_bytes": cap},
        network="on" if network else "off (not enforced)",
        runner=runner.name,
        exit_code=raw.exit_code,
        duration_ms=raw.duration_ms,
        killed_by=raw.killed_by,
        stdout=stdout,
        stderr=stderr,
        stdout_bytes=len(raw.stdout),
        stderr_bytes=len(raw.stderr),
        stdout_sha256=hashlib.sha256(raw.stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(raw.stderr).hexdigest(),
        stdout_truncated=out_cut,
        stderr_truncated=err_cut,
        notes=notes,
    )
    _record(Path(project) if project is not None else worktree, result)
    return Rooted(
        value=result,
        assumption=f"{' '.join(result.argv)} ran under {result.rule_id or 'an approval'}; {TRACE_NOTE}",
        confidence=1.0,
        provenance=["tools.command", f"rule:{result.rule_id}"],
    )


def _record(project: Path, result: CommandResult) -> None:
    """Append the D10 record to this project's ``commands.jsonl`` in the user state folder."""
    from ract.key_paths import repo_key_dir

    record = asdict(result)
    record.pop("stdout")
    record.pop("stderr")
    path = repo_key_dir(project, "commands").parent / "commands.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=False) + "\n")
    except OSError as exc:
        print(f"[command] the command record was not written: {exc}", flush=True)


__all__ = [
    "CommandResult",
    "CommandRunner",
    "ProcessRunner",
    "RawRun",
    "ScriptedRunner",
    "TRACE_NOTE",
    "default_runner",
    "cap_output",
    "command_env",
    "run_command",
]
