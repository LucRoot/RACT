"""``run_command``'s core: one argv run under a grant rule, recorded (ADR-0048 D5, D10).

LR:: The command runs as the matcher resolved it, never through a shell:
``shell=False``, stdin closed, the scrubbed ``sandbox_env`` allowlist plus
the rule's ``env_extra`` (minus ``NEVER_PASSTHROUGH`` and every ``RACT_*``
name except ``RACT_RUN_ID``), the home folders pointed at a per-step
temporary folder unless the rule says ``home: real``, ``cwd`` pinned to the
step worktree or a folder inside it, and a hard wall-clock timeout after
which the whole process tree is killed. Output is kept up to a cap per
stream: a cut shows the head, the tail and how many bytes were dropped, and
escape sequences never reach the model or the operator. The real runner
reads both streams while the command runs, keeping a head, a tail, the byte
count and the SHA-256 of everything, and kills the tree when either stream
passes ``OUTPUT_FLOOD_BYTES`` (G-215 C1). The executable is hashed just
before the spawn and the call is refused if it changed after the matcher
resolved it (C3). The per-step home is removed after the run (C4).

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
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ract import redaction
from ract.rooted import Rooted
from ract.session_events import safe_text

DEFAULT_TIMEOUT_S = 300
DEFAULT_OUTPUT_BYTES = 1_048_576
# G-215 C1: past this many bytes on either stream the tree is killed.
OUTPUT_FLOOD_BYTES = 64 * 1_048_576
# G-215 C2: how long the readers may take to finish after the process ends.
PIPE_GRACE_S = 5.0
PIPES_HELD_NOTE = "a process kept the pipes open"
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
    """What a runner observed: the exit code, both streams, the time, and a kill.

    A streaming runner keeps only a head (``stdout``) and a tail
    (``stdout_tail``) and says the whole stream's size and SHA-256; a runner
    that leaves them unset gave the whole stream in ``stdout``.
    """

    exit_code: int | None
    stdout: bytes
    stderr: bytes
    duration_ms: int
    killed_by: str | None = None
    stdout_tail: bytes = b""
    stderr_tail: bytes = b""
    stdout_total: int | None = None
    stderr_total: int | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    notes: tuple[str, ...] = ()


class CommandRunner(Protocol):
    name: str

    def run(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float
    ) -> RawRun: ...


class _Stream:
    """One stream as it is read: a head, a ring tail, the byte count and the hash."""

    def __init__(self, keep: int) -> None:
        self.keep = max(keep, 1)
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0
        self.sha = hashlib.sha256()
        self.lock = threading.Lock()

    def feed(self, chunk: bytes) -> int:
        with self.lock:
            self.total += len(chunk)
            self.sha.update(chunk)
            room = self.keep - len(self.head)
            if room > 0:
                self.head += chunk[:room]
                chunk = chunk[room:]
            if chunk:
                self.tail += chunk
                if len(self.tail) > self.keep:
                    del self.tail[: len(self.tail) - self.keep]
            return self.total

    def snapshot(self) -> tuple[bytes, bytes, int, str]:
        with self.lock:
            return (
                bytes(self.head),
                bytes(self.tail),
                self.total,
                self.sha.copy().hexdigest(),
            )


def _drain(pipe: Any, stream: _Stream, flood: threading.Event) -> None:
    """Read *pipe* to its end into *stream*; set *flood* past the ceiling."""
    try:
        while True:
            chunk = pipe.read1(65536)
            if not chunk:
                return
            if stream.feed(chunk) > OUTPUT_FLOOD_BYTES:
                flood.set()
    except (OSError, ValueError) as exc:
        print(f"[command] a stream stopped being read: {exc}", flush=True)


def _joined(threads: list[threading.Thread], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    for thread in threads:
        thread.join(max(deadline - time.monotonic(), 0))
    return not any(thread.is_alive() for thread in threads)


def _close_pipes(popen: Any) -> None:
    for pipe in (popen.stdout, popen.stderr):
        try:
            if pipe is not None:
                pipe.close()
        except (OSError, ValueError) as exc:
            print(f"[command] a pipe was not closed: {exc}", flush=True)


class ProcessRunner:
    """Runs the process for real: ``process_group.spawn``, streams read as they come.

    The tree is killed at the wall-clock timeout (``killed_by: timeout``) or
    when either stream passes ``OUTPUT_FLOOD_BYTES`` (``output_flood``). A
    process that keeps a pipe open after the end or the kill never holds
    RACT: after ``PIPE_GRACE_S`` the tree is killed, the pipes are closed and
    what was read is returned with the note ``PIPES_HELD_NOTE``.
    """

    name = "process"
    streams = True

    def run(
        self,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout_s: float,
        keep_bytes: int = DEFAULT_OUTPUT_BYTES,
    ) -> RawRun:
        from ract.executor.process_group import kill_tree, spawn

        started = time.monotonic()
        handle = spawn(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL)
        popen = handle.popen
        out, err = _Stream(keep_bytes), _Stream(keep_bytes)
        flood = threading.Event()
        readers = [
            threading.Thread(
                target=_drain, args=(popen.stdout, out, flood), daemon=True
            ),
            threading.Thread(
                target=_drain, args=(popen.stderr, err, flood), daemon=True
            ),
        ]
        for reader in readers:
            reader.start()
        deadline = started + timeout_s
        killed: str | None = None
        while True:
            if flood.is_set():
                killed = "output_flood"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                killed = "timeout"
                break
            try:
                popen.wait(timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if killed is not None:
            kill_tree(handle, grace_period_seconds=2.0 if killed == "timeout" else 0.0)
        notes: list[str] = []
        if not _joined(readers, PIPE_GRACE_S):
            # C2: a process outside the kill, or one left after the end, holds a pipe.
            notes.append(PIPES_HELD_NOTE)
            if killed is None:
                kill_tree(handle)
            if not _joined(readers, 2.0):
                threading.Thread(
                    target=_close_pipes, args=(popen,), daemon=True
                ).start()
        try:
            popen.wait(timeout=PIPE_GRACE_S)
        except subprocess.TimeoutExpired as exc:
            print(f"[command] the process was not reaped: {exc}", flush=True)
        o_head, o_tail, o_total, o_sha = out.snapshot()
        e_head, e_tail, e_total, e_sha = err.snapshot()
        return RawRun(
            popen.returncode,
            o_head,
            e_head,
            int((time.monotonic() - started) * 1000),
            killed,
            o_tail,
            e_tail,
            o_total,
            e_total,
            o_sha,
            e_sha,
            tuple(notes),
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


def default_runner(rule: Any = None) -> CommandRunner:
    """The runner for a command: scripted when ``RACT_FAKE_RUNNER`` names a
    script; else inside the enforcing sandbox where this machine has one
    (B-114, ``security.command_sandbox``); else the plain process runner."""
    script = os.environ.get("RACT_FAKE_RUNNER")
    if not script:
        from ract.security.command_sandbox import runner_for

        return runner_for(rule) or ProcessRunner()
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
    # G-215 C4: "removed", "not removed: <why>" or "none (home: real)".
    step_home: str = "none (home: real)"

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and self.killed_by is None


def _clean(data: bytes) -> bytes:
    text = data.decode("utf-8", errors="replace")
    return safe_text(_ANSI.sub("", text).replace("\r\n", "\n")).encode("utf-8")


def cap_output(
    data: bytes, cap: int, *, tail: bytes = b"", dropped: int = 0
) -> tuple[str, bool]:
    """The stream as text for the model and the operator: stripped, capped head and tail.

    A streaming runner gives the head as *data*, the tail as *tail* and the
    bytes it never kept between them as *dropped*.
    """
    if not dropped:
        raw = _clean(data + tail)
        if len(raw) <= cap:
            return raw.decode("utf-8"), False
        head_raw, tail_raw = raw, raw
    else:
        head_raw, tail_raw = _clean(data), _clean(tail)
    half = max(cap // 2, 1)
    head_kept = head_raw[:half]
    tail_kept = tail_raw[-half:]
    if not dropped:
        lost = len(head_raw) - 2 * half
    else:
        lost = (
            dropped
            + (len(head_raw) - len(head_kept))
            + (len(tail_raw) - len(tail_kept))
        )
    head_text = head_kept.decode("utf-8", errors="ignore")
    tail_text = tail_kept.decode("utf-8", errors="ignore")
    return f"{head_text}\n[cut: {lost} bytes dropped]\n{tail_text}", True


def command_env(
    env_extra: list[str],
    home: str,
    step_home: Path | None,
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
    if home != "real" and step_home is not None:
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
    from ract.policy.matcher import file_digest

    return file_digest(path)


def _remove_home(step_home: Path | None) -> str:
    """Remove the per-step home (G-215 C4) and say whether it went."""
    if step_home is None:
        return "none (home: real)"
    errors: list[str] = []

    def _failed(_func: Any, path: str, exc: Any) -> None:
        errors.append(f"{path}: {exc}")

    shutil.rmtree(step_home, onerror=_failed)
    if step_home.exists():
        why = errors[0] if errors else "it is still there"
        print(f"[command] the step home was not removed: {why}", flush=True)
        return f"not removed: {safe_text(why)[:200]}"
    return "removed"


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
    runner = runner or default_runner(rule)
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
    home = getattr(rule, "home", "isolated") or "isolated"
    step_home = (
        None if home == "real" else Path(tempfile.mkdtemp(prefix="ract-step-home-"))
    )
    refused: Rooted[CommandResult] | None = None
    try:
        env, env_digest = command_env(
            list(getattr(rule, "env_extra", []) or []), home, step_home, process_env
        )
        confined = getattr(runner, "sandbox", None)
        notes = [
            f"the command runs inside {confined}: the filesystem outside the "
            "workspace and the network (unless the rule allows it) are refused; "
            "process, memory and CPU limits are not enforced; the wall-clock "
            "timeout is"
            if confined
            else "no sandbox confines commands on this machine: process, memory "
            "and CPU limits are not enforced; the wall-clock timeout is",
        ]
        if not network and not confined:
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
        # C3: hashed immediately before the spawn; the record keeps this value.
        executable_sha256 = _sha256_file(match.executable) if match.executable else None
        seen = getattr(match, "executable_sha256", None)
        if seen is not None and executable_sha256 != seen:
            refused = Rooted(
                value=None,
                assumption="the executable is the file the matcher resolved",
                confidence=0.0,
                provenance=["tools.command"],
                error="the executable changed after it was resolved; nothing ran",
                hint=f"{match.executable} was replaced or rewritten; ask again",
            )
        else:
            if hasattr(runner, "worktree"):
                # The sandbox mounts the step worktree, not the rule's sub-folder.
                runner.worktree = worktree
            extra = {"keep_bytes": cap} if getattr(runner, "streams", False) else {}
            raw = runner.run(argv, cwd=cwd, env=env, timeout_s=wall, **extra)
    finally:
        home_state = _remove_home(step_home)
    if refused is not None:
        return refused
    out_total = (
        len(raw.stdout) + len(raw.stdout_tail)
        if raw.stdout_total is None
        else raw.stdout_total
    )
    err_total = (
        len(raw.stderr) + len(raw.stderr_tail)
        if raw.stderr_total is None
        else raw.stderr_total
    )
    stdout, out_cut = cap_output(
        raw.stdout,
        cap,
        tail=raw.stdout_tail,
        dropped=out_total - len(raw.stdout) - len(raw.stdout_tail),
    )
    stderr, err_cut = cap_output(
        raw.stderr,
        cap,
        tail=raw.stderr_tail,
        dropped=err_total - len(raw.stderr) - len(raw.stderr_tail),
    )
    notes.extend(raw.notes)
    if raw.killed_by == "output_flood":
        notes.append(
            f"killed: the output passed {OUTPUT_FLOOD_BYTES // 1_048_576} MiB on a stream"
        )
    if runner.name == "fake":
        notes.append("fake runner: no command ran")
    result = CommandResult(
        argv=list(match.argv),
        executable=match.executable or "",
        executable_sha256=executable_sha256,
        cwd=cwd.relative_to(worktree.resolve()).as_posix() if cwd != worktree else ".",
        env_names=sorted(env),
        env_allowlist_digest=env_digest,
        grant_digest=grant_digest,
        rule_id=getattr(rule, "id", None),
        approval_id=approval_id,
        approver=approver,
        sandbox=getattr(runner, "sandbox", None) or "none",
        enforced=bool(getattr(runner, "sandbox", None)),
        limits={"wall_s": wall, "output_bytes": cap},
        network=(
            "on"
            if network
            else "off"
            if getattr(runner, "sandbox", None)
            else "off (not enforced)"
        ),
        runner=runner.name,
        exit_code=raw.exit_code,
        duration_ms=raw.duration_ms,
        killed_by=raw.killed_by,
        stdout=stdout,
        stderr=stderr,
        stdout_bytes=out_total,
        stderr_bytes=err_total,
        stdout_sha256=raw.stdout_sha256
        or hashlib.sha256(raw.stdout + raw.stdout_tail).hexdigest(),
        stderr_sha256=raw.stderr_sha256
        or hashlib.sha256(raw.stderr + raw.stderr_tail).hexdigest(),
        stdout_truncated=out_cut,
        stderr_truncated=err_cut,
        notes=notes,
        step_home=home_state,
    )
    _record(Path(project) if project is not None else worktree, result)
    return Rooted(
        value=result,
        assumption=(
            f"{redaction.redact(' '.join(result.argv))} ran under "
            f"{result.rule_id or 'an approval'}; {TRACE_NOTE}"
        ),
        confidence=1.0,
        provenance=["tools.command", f"rule:{result.rule_id}"],
    )


def _record(project: Path, result: CommandResult) -> None:
    """Append the D10 record to this project's ``commands.jsonl`` in the user state folder."""
    from ract.key_paths import repo_key_dir

    from ract.redaction import redact_values

    record = asdict(result)
    record.pop("stdout")
    record.pop("stderr")
    # B-201: an argv can hold a key (a token flag, a URL with one); the record
    # keeps the shape and never the value.
    record = redact_values(record)
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
    "OUTPUT_FLOOD_BYTES",
    "PIPES_HELD_NOTE",
    "ProcessRunner",
    "RawRun",
    "ScriptedRunner",
    "TRACE_NOTE",
    "default_runner",
    "cap_output",
    "command_env",
    "run_command",
]
