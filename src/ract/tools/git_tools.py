"""Git as tools: status, diff, log, add, commit, branch, worktree, push (B-115, B-024, ADR-0048 D8).

LR:: Every git call runs with ``-c core.fsmonitor=false``, ``-c
core.hooksPath=`` an empty folder, no pager and no color, and diffs with
``--no-ext-diff --no-textconv``, so repository configuration cannot start a
program during a read. The environment is the operator's without RACT's own
names, the never-pass-through names, or the variables that point git at
another repository or another config; prompts for credentials are off.

``git_status``, ``git_diff`` and ``git_log`` are tier 0 and return capped,
structured results like the file tools. ``git_add``, ``git_commit``,
``git_branch`` and ``git_worktree`` are tier 2: the operator is asked once
per call with the exact command shown. Before a commit the staged diff is
scanned for secrets; a hit refuses the commit and names the file and line.
Commit hooks are repository code and run only when the grant's rule for
``git commit`` says ``git_hooks: true``. The commit uses the author and
message the operator's git config gives; RACT sets neither.

``git_push`` is tier 3: it needs a grant that holds, a rule for ``git
push``, and a signed handshake approval for that remote and branch; it is
then asked (remote git always asks, D8) and runs through ``run_command``
like every tier-3 command. ``--yolo`` never runs it. Nothing else reaches a
remote: there is no fetch, pull or remote-changing tool.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ract.core.threat_model import CapabilityTier
from ract.tools import ToolRefused, ToolResult, ToolSpec

_CAP = 64 * 1024
_TIMEOUT_S = 60
# Variables that would point git at another repository, config or program.
_GIT_REDIRECTS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_COUNT",
    "GIT_EXEC_PATH",
    "GIT_EXTERNAL_DIFF",
    "GIT_PAGER",
    "GIT_EDITOR",
    "GIT_SSH",
    "GIT_SSH_COMMAND",
    "GIT_ASKPASS",
    "GIT_PROXY_COMMAND",
)


def _no_hooks_dir() -> Path:
    """An empty folder for ``core.hooksPath``, so no hook can run."""
    folder = Path(tempfile.gettempdir()) / "ract-no-git-hooks"
    folder.mkdir(exist_ok=True)
    for entry in folder.iterdir():
        # The folder must stay empty: anything put there is removed first.
        try:
            entry.unlink()
        except OSError as exc:
            raise ToolRefused(
                f"the empty hooks folder holds {entry.name} and it cannot be removed: {exc}",
                "remove it by hand; RACT runs git only with no hooks",
            ) from exc
    return folder


def git_argv(*args: str, hooks: bool = False) -> list[str]:
    """``git`` with D8's hardening, then *args*."""
    argv = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.pager=cat",
        "-c",
        "color.ui=false",
        "-c",
        "diff.external=",
    ]
    if not hooks:
        argv += ["-c", f"core.hooksPath={_no_hooks_dir().as_posix()}"]
    return [*argv, "--no-pager", *args]


def git_env(source: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for git: the operator's, minus RACT's and the redirects."""
    from ract.security.sandbox_env import NEVER_PASSTHROUGH

    env = {
        k: v
        for k, v in (os.environ if source is None else source).items()
        if k not in NEVER_PASSTHROUGH
        and not k.upper().startswith("RACT_")
        and k.upper() not in _GIT_REDIRECTS
        and not k.upper().startswith("GIT_CONFIG_KEY_")
        and not k.upper().startswith("GIT_CONFIG_VALUE_")
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run(
    root: Path, argv: list[str], *, stdin: bytes | None = None
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            cwd=root,
            env=git_env(),
            input=stdin,
            capture_output=True,
            timeout=_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolRefused(
            f"git did not finish in {_TIMEOUT_S} s", "try a narrower path"
        ) from exc
    except OSError as exc:
        raise ToolRefused(
            f"git did not start: {exc}", "install git, or put it on PATH"
        ) from exc


def _text(raw: bytes) -> str:
    from ract.session_events import safe_text

    return safe_text(raw.decode("utf-8", errors="replace"))


def _inside(paths: list[str]) -> list[str]:
    for path in paths:
        posix = path.replace("\\", "/")
        if (
            not path
            or path.startswith("-")
            or "\x00" in path
            or len(path) > 300
            or PurePosixPath(posix).is_absolute()
            or ":" in posix
            or ".." in PurePosixPath(posix).parts
        ):
            raise ValueError(f"{path!r} is not a path inside the project")
    return paths


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathsArgs(_Args):
    paths: list[str] = Field(default_factory=list, max_length=64)

    check_paths = field_validator("paths")(classmethod(lambda cls, v: _inside(v)))


class DiffArgs(PathsArgs):
    staged: bool = False


class LogArgs(PathsArgs):
    max_count: int = Field(default=10, ge=1, le=50)


class AddArgs(_Args):
    paths: list[str] = Field(min_length=1, max_length=64)

    check_paths = field_validator("paths")(classmethod(lambda cls, v: _inside(v)))


class CommitArgs(_Args):
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def _no_nul(cls, message: str) -> str:
        if "\x00" in message:
            raise ValueError("the message has a NUL character")
        return message


_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")


def _ref(name: str) -> str:
    if not _REF.match(name) or ".." in name or name.endswith((".lock", "/", ".")):
        raise ValueError(f"{name!r} is not a branch name RACT will create")
    return name


class BranchArgs(_Args):
    name: str

    check_name = field_validator("name")(classmethod(lambda cls, v: _ref(v)))


class WorktreeArgs(_Args):
    action: str = Field(pattern=r"^(list|add)$")
    name: str = ""

    @field_validator("name")
    @classmethod
    def _name(cls, name: str) -> str:
        return _ref(name) if name else name


class PushArgs(_Args):
    remote: str
    branch: str
    reason: str = Field(default="", max_length=500)

    check_remote = field_validator("remote")(classmethod(lambda cls, v: _ref(v)))
    check_branch = field_validator("branch")(classmethod(lambda cls, v: _ref(v)))


# ---------------------------------------------------------------- tier 0


def git_status(root: Path, args: PathsArgs) -> ToolResult:
    done = _run(
        root,
        git_argv(
            "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *args.paths
        ),
    )
    if done.returncode != 0:
        raise ToolRefused(
            f"git status failed: {_text(done.stderr)[:300]}",
            "is this a git repository?",
        )
    entries = []
    for raw in done.stdout.split(b"\0"):
        if len(raw) > 3:
            entries.append(
                {"status": raw[:2].decode("ascii", "replace"), "path": _text(raw[3:])}
            )
    text = "\n".join(f"{e['status']} {e['path']}" for e in entries) or "nothing changed"
    return ToolResult(
        text=text, facts={"entries": entries[:500], "count": len(entries)}
    )


def git_diff(root: Path, args: DiffArgs) -> ToolResult:
    done = _run(
        root,
        git_argv(
            "diff",
            *(["--cached"] if args.staged else []),
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "--",
            *args.paths,
        ),
    )
    if done.returncode != 0:
        raise ToolRefused(
            f"git diff failed: {_text(done.stderr)[:300]}", "is this a git repository?"
        )
    text = _text(done.stdout)
    return ToolResult(
        text=text or "no difference",
        facts={"staged": args.staged, "bytes": len(done.stdout)},
        truncated=len(text.encode("utf-8")) > _CAP,
    )


def git_log(root: Path, args: LogArgs) -> ToolResult:
    done = _run(
        root,
        git_argv(
            "log",
            "--no-color",
            f"-n{args.max_count}",
            "--date=short",
            "--format=%h%x09%an%x09%ad%x09%s",
            "--",
            *args.paths,
        ),
    )
    if done.returncode != 0:
        raise ToolRefused(
            f"git log failed: {_text(done.stderr)[:300]}", "is there a commit yet?"
        )
    commits = []
    for line in _text(done.stdout).splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            commits.append(dict(zip(("commit", "author", "date", "subject"), parts)))
    return ToolResult(
        text="\n".join("  ".join(c.values()) for c in commits) or "no commits",
        facts={"commits": commits},
    )


# ---------------------------------------------------------------- tier 2


def command_for(name: str, args: Any) -> list[str]:
    """The exact git command a tier-2 git tool would run (shown when it asks)."""
    if name == "git_add":
        return ["git", "add", "--", *args.paths]
    if name == "git_commit":
        return ["git", "commit", "-m", args.message]
    if name == "git_branch":
        return ["git", "branch", "--", args.name]
    if name == "git_worktree":
        if args.action == "list":
            return ["git", "worktree", "list", "--porcelain"]
        return [
            "git",
            "worktree",
            "add",
            "-b",
            f"ract/{args.name}",
            f".ract/worktrees/{args.name}",
        ]
    raise KeyError(name)


def git_add(root: Path, args: AddArgs) -> ToolResult:
    done = _run(root, git_argv("add", "--", *args.paths))
    if done.returncode != 0:
        raise ToolRefused(
            f"git add failed: {_text(done.stderr)[:300]}", "name files that exist"
        )
    return ToolResult(
        text=f"staged: {', '.join(args.paths)}", facts={"paths": list(args.paths)}
    )


def staged_secrets(root: Path) -> list[tuple[str, int, str]]:
    """``(file, line, kind)`` for each secret in the staged diff's added lines."""
    from ract import egress_scan

    done = _run(
        root,
        git_argv(
            "diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-color", "-U0"
        ),
    )
    hits: list[tuple[str, int, str]] = []
    path, line_no = "", 0
    for line in _text(done.stdout).splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_no = int(match.group(1)) if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            _text_out, counts = egress_scan.scan_text(line[1:])
            if counts:
                hits.append((path, line_no, egress_scan.describe(counts)))
            line_no += 1
    return hits


def _hooks_allowed() -> bool:
    """D8: commit hooks run only when the grant's rule for ``git commit`` says so."""
    from ract.policy import tier3

    ctx = tier3.current()
    policy = getattr(getattr(ctx, "grant", None), "policy", None)
    if ctx is None or not ctx.grant.holds or policy is None:
        return False
    return any(
        list(rule.argv[:2]) == ["git", "commit"] and rule.git_hooks
        for rule in policy.commands.allow
    )


def git_commit(root: Path, args: CommitArgs) -> ToolResult:
    if not _run(root, git_argv("diff", "--cached", "--quiet")).returncode:
        raise ToolRefused("nothing is staged", "git_add the files first")
    hits = staged_secrets(root)
    if hits:
        where = "; ".join(f"{f}:{n} ({kind})" for f, n, kind in hits[:10])
        raise ToolRefused(
            f"the staged change holds a secret: {where}; nothing was committed",
            "unstage the file or remove the secret; only the operator at the terminal "
            "can commit it anyway, with git itself",
        )
    hooks = _hooks_allowed()
    done = _run(
        root,
        git_argv("commit", "-F", "-", hooks=hooks),
        stdin=args.message.encode("utf-8"),
    )
    if done.returncode != 0:
        raise ToolRefused(
            f"git commit failed: {_text(done.stderr)[:300]}", "see git's message"
        )
    head = _run(root, git_argv("rev-parse", "--short", "HEAD"))
    return ToolResult(
        text=f"committed {_text(head.stdout).strip()}"
        + (" (hooks ran)" if hooks else " (no hooks)"),
        facts={"commit": _text(head.stdout).strip(), "hooks": hooks},
    )


def git_branch(root: Path, args: BranchArgs) -> ToolResult:
    done = _run(root, git_argv("branch", "--", args.name))
    if done.returncode != 0:
        raise ToolRefused(
            f"git branch failed: {_text(done.stderr)[:300]}", "pick a new name"
        )
    return ToolResult(text=f"created branch {args.name}", facts={"branch": args.name})


def git_worktree(root: Path, args: WorktreeArgs) -> ToolResult:
    if args.action == "list":
        done = _run(root, git_argv("worktree", "list", "--porcelain"))
        return ToolResult(text=_text(done.stdout) or "no worktrees", facts={})
    if not args.name:
        raise ToolRefused("a worktree needs a name", "give name")
    done = _run(
        root,
        git_argv(
            "worktree", "add", "-b", f"ract/{args.name}", f".ract/worktrees/{args.name}"
        ),
    )
    if done.returncode != 0:
        raise ToolRefused(
            f"git worktree add failed: {_text(done.stderr)[:300]}", "pick a new name"
        )
    return ToolResult(
        text=f"worktree .ract/worktrees/{args.name} on branch ract/{args.name}",
        facts={"path": f".ract/worktrees/{args.name}", "branch": f"ract/{args.name}"},
    )


# ---------------------------------------------------------------- tier 3


def push_handshake_id(remote: str, branch: str) -> str:
    return f"git-push:{remote}:{branch}"


def git_push(root: Path, args: PushArgs) -> ToolResult:
    from ract.handshake_registry import HandshakeRegistry
    from ract.tools.tests_tool import run_under_rule, tier3_context

    ctx = tier3_context()
    rules = list(ctx.grant.policy.commands.allow)
    rule = next((r for r in rules if list(r.argv[:2]) == ["git", "push"]), None)
    if rule is None:
        raise ToolRefused(
            "not run, because the grant has no rule for git push",
            "add an allow rule with argv [git, push] to .ract/policy.yaml and sign it",
        )
    handshake = push_handshake_id(args.remote, args.branch)
    if not HandshakeRegistry(ctx.project).is_approved(handshake):
        raise ToolRefused(
            f"not run, because the handshake {handshake} is not approved with your signature",
            f"`ract handshakes approve {handshake}` at a terminal, then ask again",
        )
    return run_under_rule(
        root,
        ctx,
        rule,
        ["git", "push", args.remote, args.branch],
        args.reason,
        kind="push",
        refused_hint="push only a named remote and branch",
        notes=[f"this sends commits to the remote {args.remote}"],
    )


def _spec(
    name: str, tier: CapabilityTier, model: type[BaseModel], run, mutates: bool
) -> ToolSpec:
    return ToolSpec(
        name=name,
        tier=tier,
        args_model=model,
        mutates=mutates,
        result_cap_bytes=_CAP,
        run=run,
    )


GIT_TOOLS = (
    _spec("git_status", CapabilityTier.TIER_0_READ, PathsArgs, git_status, False),
    _spec("git_diff", CapabilityTier.TIER_0_READ, DiffArgs, git_diff, False),
    _spec("git_log", CapabilityTier.TIER_0_READ, LogArgs, git_log, False),
    _spec("git_add", CapabilityTier.TIER_2_ENV, AddArgs, git_add, True),
    _spec("git_commit", CapabilityTier.TIER_2_ENV, CommitArgs, git_commit, True),
    _spec("git_branch", CapabilityTier.TIER_2_ENV, BranchArgs, git_branch, True),
    _spec("git_worktree", CapabilityTier.TIER_2_ENV, WorktreeArgs, git_worktree, True),
    _spec("git_push", CapabilityTier.TIER_3_EXTERNAL, PushArgs, git_push, True),
)

__all__ = [
    "GIT_TOOLS",
    "command_for",
    "git_argv",
    "git_env",
    "push_handshake_id",
    "staged_secrets",
]
