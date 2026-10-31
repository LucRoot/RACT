"""Git as tools: status, diff, log, add, commit, branch, worktree, push (B-115, B-024, ADR-0048 D8).

LR:: Every git call runs with ``-c core.fsmonitor=false``, ``-c
core.hooksPath=`` an empty folder, no pager and no color, no attributes
file from config and no signing, and diffs with ``--no-ext-diff
--no-textconv``, so repository configuration cannot start a program during
a read. The environment is the operator's without RACT's own names, the
never-pass-through names, or the variables that point git at another
repository or another config; prompts for credentials are off.

G-239: git runs only in a repository whose top folder is the project
(``GIT_CEILING_DIRECTORIES`` stops the search at the project), and a
repository whose own config defines a filter program, or whose attributes
name a filter the operator's config does not define, is refused. Output
is read as it comes and kept up to a cap.

``git_status``, ``git_diff`` and ``git_log`` are tier 0 and return capped,
structured results like the file tools. ``git_add``, ``git_commit``,
``git_branch`` and ``git_worktree`` are tier 2: the operator is asked once
per call with the exact command shown, quoted. Before a commit every staged
file is read whole from the index and scanned for secrets; a hit, a key or
environment file by name, or a scan that cannot run refuses the commit.
The question shows the staged files and the scan's result, and the commit
runs only if the staged change is still the one shown. Commit hooks are
repository code and run only when the grant's rule for ``git commit`` says
``git_hooks: true``. The commit uses the author and message the operator's
git config gives; RACT sets neither.

``git_push`` is tier 3: it needs a grant that holds, a rule for ``git
push``, a repository config that sets no transport or credential program,
and a signed handshake approval for the resolved push URL, the branch and
its commit; it is then asked (remote git always asks, D8) and runs through
``run_command`` like every tier-3 command. ``--yolo`` never runs it.
Nothing else reaches a remote: there is no fetch, pull or remote-changing
tool.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from ract import programs
from ract.core.threat_model import CapabilityTier
from ract.tools import ToolRefused, ToolResult, ToolSpec

_CAP = 64 * 1024
_TIMEOUT_S = 60
# LR:: G-239 C11: what one git call may print before it is stopped.
_READ_CAP = 4 * 1024 * 1024
# The most the commit scan reads from the index; a bigger change refuses.
_SCAN_CAP = 32 * 1024 * 1024
_ATTRIBUTES_CAP = 1024 * 1024
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
# Config scopes that come from the repository itself (and its includes).
_REPO_SCOPES = frozenset({"local", "worktree"})
_FILTER_KEY = re.compile(r"^filter\.(.+)\.(?:clean|smudge|process)$")
_FILTER_ATTR = re.compile(r"(?:^|\s)filter=(\S+)")
# LR:: G-239 B-push: keys that choose a transport, proxy, credential
# program or another URL. They belong in the operator's global config.
_PUSH_KEYS = re.compile(
    r"^(?:core\.(?:sshcommand|gitproxy|askpass)"
    r"|credential\.(?:.+\.)?helper"
    r"|remote\..+\.(?:receivepack|uploadpack|proxy|pushurl|vcs)"
    r"|url\..+\.(?:insteadof|pushinsteadof)"
    r"|https?\.(?:.+\.)?proxy"
    r"|protocol\.(?:.+\.)?allow)$"
)
# LR:: G-239 A9: shapes the commit scan adds to the shared redaction list.
# A bare AWS secret has 40 base64 characters with both cases and a digit,
# which a hex commit id never has.
_COMMIT_ONLY_PATTERNS = (
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}")),
    (
        "AWS-style secret key",
        re.compile(
            r"(?<![A-Za-z0-9/+=])(?=[A-Za-z0-9/+]*[A-Z])(?=[A-Za-z0-9/+]*[a-z])"
            r"(?=[A-Za-z0-9/+]*[0-9])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+=])"
        ),
    ),
)
_SSH_KEY_NAME = re.compile(r"^id_[a-z0-9]+$")


def _is_junction(path: Path) -> bool:
    """A junction or any other reparse point: a link ``is_symlink`` can miss."""
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    except OSError as exc:
        print(f"[git_tools] {path} could not be checked for a link: {exc}", flush=True)
        return True
    return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


_hooks_lock = threading.Lock()
_hooks_folder: Path | None = None


def _remove_hooks_folder(folder: Path) -> None:
    try:
        folder.rmdir()
    except FileNotFoundError:
        return
    except OSError as exc:
        print(f"[git_tools] the empty hooks folder stays: {exc}", flush=True)


def _no_hooks_dir() -> Path:
    """An empty folder for ``core.hooksPath``, so no hook can run.

    LR:: G-239 C10: the folder is this process's own, made by ``mkdtemp``
    (private to the user, a new name each time). Anything found in it, or a
    link in its place, refuses the call; RACT removes nothing it did not make.
    """
    global _hooks_folder
    with _hooks_lock:
        if _hooks_folder is None or not os.path.lexists(_hooks_folder):
            _hooks_folder = Path(tempfile.mkdtemp(prefix="ract-no-git-hooks-"))
            atexit.register(_remove_hooks_folder, _hooks_folder)
        folder = _hooks_folder
    if folder.is_symlink() or _is_junction(folder) or not folder.is_dir():
        raise ToolRefused(
            f"the empty hooks folder {folder} is a link or not a folder",
            "remove it by hand; RACT runs git only with no hooks",
        )
    try:
        found = sorted(entry.name for entry in os.scandir(folder))
    except OSError as exc:
        raise ToolRefused(
            f"the empty hooks folder {folder} cannot be read: {exc}",
            "check the temporary folder; RACT runs git only with no hooks",
        ) from exc
    if found:
        raise ToolRefused(
            f"the empty hooks folder {folder} holds {found[0]}, which RACT did not put there",
            "remove it by hand; RACT runs git only with no hooks",
        )
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
        # G-239 B: no attributes file named by config, no signing program.
        "-c",
        "core.attributesFile=",
        "-c",
        "commit.gpgSign=false",
        "-c",
        "tag.gpgSign=false",
        "-c",
        "push.gpgSign=false",
        "-c",
        "log.showSignature=false",
        "-c",
        "protocol.ext.allow=never",
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


@dataclass(frozen=True)
class _Done:
    """One git call: the exit code, the kept output, and whether a stream passed the cap."""

    returncode: int
    stdout: bytes
    stderr: bytes
    cut: bool = False


def _drain(pipe: Any, keep: bytearray, cap: int, over: threading.Event) -> None:
    """Read *pipe* into *keep* up to *cap* bytes; past it, set *over* and stop."""
    try:
        while True:
            chunk = pipe.read1(65536)
            if not chunk:
                return
            room = cap - len(keep)
            keep += chunk[: max(room, 0)]
            if len(chunk) > room:
                over.set()
                return
    except (OSError, ValueError) as exc:
        print(f"[git_tools] a git stream stopped being read: {exc}", flush=True)


def _feed(pipe: Any, data: bytes) -> None:
    try:
        pipe.write(data)
    except (OSError, ValueError) as exc:
        print(f"[git_tools] git's input was not written: {exc}", flush=True)
    finally:
        try:
            pipe.close()
        except (OSError, ValueError) as exc:
            print(f"[git_tools] git's input was not closed: {exc}", flush=True)


def _close(pipe: Any) -> None:
    try:
        if pipe is not None:
            pipe.close()
    except (OSError, ValueError) as exc:
        print(f"[git_tools] a git pipe was not closed: {exc}", flush=True)


def _run(
    root: Path, argv: list[str], *, stdin: bytes | None = None, cap: int = _READ_CAP
) -> _Done:
    """Run git in *root*, reading its output as it comes and keeping *cap* bytes.

    LR:: G-239 C11, the approach of ``run_command``: a stream that passes the
    cap stops the process and the result says ``cut``. G-239 C5: the search
    for a repository stops at the project, never in a folder above it.
    """
    env = git_env()
    real = Path(os.path.realpath(root))
    if real.parent != real:
        env["GIT_CEILING_DIRECTORIES"] = str(real.parent)
    try:
        # B-214: git_argv keeps the name "git" (it is shown and matched by
        # rules); the program started is git's full path.
        started = [programs.git(), *argv[1:]] if argv[:1] == ["git"] else argv
        popen = subprocess.Popen(
            started,
            cwd=root,
            env=env,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ToolRefused(
            f"git did not start: {exc}", "install git, or put it on PATH"
        ) from exc
    out, err = bytearray(), bytearray()
    over = threading.Event()
    threads = [
        threading.Thread(
            target=_drain, args=(popen.stdout, out, cap, over), daemon=True
        ),
        threading.Thread(
            target=_drain, args=(popen.stderr, err, cap, over), daemon=True
        ),
    ]
    if stdin is not None:
        threads.append(
            threading.Thread(target=_feed, args=(popen.stdin, stdin), daemon=True)
        )
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + _TIMEOUT_S
    stopped = ""
    while True:
        if over.is_set():
            stopped = "cap"
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stopped = "timeout"
            break
        try:
            popen.wait(timeout=min(0.1, remaining))
            break
        except subprocess.TimeoutExpired:
            continue
    if stopped:
        try:
            popen.kill()
        except OSError as exc:
            print(f"[git_tools] git was not stopped: {exc}", flush=True)
    for thread in threads:
        thread.join(5)
    _close(popen.stdout)
    _close(popen.stderr)
    try:
        popen.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        print(f"[git_tools] git was not reaped: {exc}", flush=True)
    if stopped == "timeout":
        raise ToolRefused(
            f"git did not finish in {_TIMEOUT_S} s", "try a narrower path"
        )
    code = popen.returncode if popen.returncode is not None else -1
    # Git can finish before the loop sees the cap: the flag is read last.
    return _Done(code, bytes(out), bytes(err), cut=over.is_set())


def _text(raw: bytes) -> str:
    from ract.session_events import safe_text

    return safe_text(raw.decode("utf-8", errors="replace"))


def _same_folder(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(
        os.path.realpath(b)
    )


def _config(root: Path) -> list[tuple[str, str, str]]:
    """``(scope, key, value)`` for every config entry git sees here, includes too."""
    done = _run(root, git_argv("config", "--list", "--show-scope", "--includes", "-z"))
    if done.returncode != 0 or done.cut:
        raise ToolRefused(
            f"git config could not be read: {_text(done.stderr)[:300]}",
            "check the repository's .git/config",
        )
    parts = done.stdout.split(b"\0")
    entries = []
    for scope, item in zip(parts[0::2], parts[1::2]):
        key, _sep, value = item.decode("utf-8", errors="replace").partition("\n")
        entries.append((scope.decode("ascii", errors="replace"), key, value))
    return entries


def _attribute_texts(root: Path, git_path: str) -> list[tuple[str, str]]:
    """``(name, text)`` for each attributes file git would read in *root*."""
    listed = _run(
        root,
        git_argv(
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            ":(glob)**/.gitattributes",
        ),
    )
    if listed.returncode != 0 or listed.cut:
        raise ToolRefused(
            f"the attributes files could not be listed: {_text(listed.stderr)[:300]}",
            "check the repository",
        )
    names = {".gitattributes"}
    names.update(
        raw.decode("utf-8", errors="replace")
        for raw in listed.stdout.split(b"\0")
        if raw
    )
    found: list[tuple[str, str]] = []
    info = Path(git_path)
    if not info.is_absolute():
        info = root / info
    for name, path in [(git_path, info)] + [(n, root / n) for n in sorted(names)]:
        if path.is_symlink() or not path.is_file():
            # Git reads no attributes file through a link; a missing one is
            # read from the index below.
            if name in names and not path.exists() and not path.is_symlink():
                blob = _run(root, git_argv("cat-file", "blob", f":{name}"))
                if blob.returncode == 0 and not blob.cut:
                    found.append((name, blob.stdout.decode("utf-8", "replace")))
            continue
        try:
            if path.stat().st_size > _ATTRIBUTES_CAP:
                raise ToolRefused(
                    f"the attributes file {name} is over 1 MiB",
                    "RACT reads attributes files whole before it runs git",
                )
            found.append((name, path.read_bytes().decode("utf-8", "replace")))
        except OSError as exc:
            raise ToolRefused(
                f"the attributes file {name} cannot be read: {exc}",
                "check the file",
            ) from exc
    return found


def _checked(root: Path) -> list[tuple[str, str, str]]:
    """Refuse a project that is not its own repository, or one with a filter program.

    LR:: G-239 C5: ``git rev-parse --show-toplevel`` must be the project.
    G-239 B-filters: a filter program runs on add, on status or diff with
    stale stat data and on checkout. The repository's own config may not
    define one, and its attributes may name only filters the operator's
    own config defines. Returns the config entries for the caller.
    """
    done = _run(
        root, git_argv("rev-parse", "--show-toplevel", "--git-path", "info/attributes")
    )
    lines = done.stdout.decode("utf-8", errors="replace").split("\n")
    if done.returncode != 0 or len(lines) < 2:
        raise ToolRefused(
            f"the project {root} is not a git repository of its own "
            "(git looks no higher than the project's folder)",
            "run git init in the project, or open RACT at the repository's top folder",
        )
    top, git_path = lines[0].strip(), lines[1].strip()
    if not _same_folder(top, root):
        raise ToolRefused(
            f"the git repository here starts at {top}, which is not the project {root}",
            "open RACT at the repository's top folder",
        )
    config = _config(root)
    own = sorted(
        {
            m.group(1)
            for s, k, _v in config
            if s in _REPO_SCOPES
            for m in [_FILTER_KEY.match(k)]
            if m
        }
    )
    if own:
        raise ToolRefused(
            f"the repository's own config defines the filter {own[0]}, a program git "
            "runs on add, status and checkout; RACT's git tools refuse this repository",
            "remove the filter from .git/config, or run git yourself",
        )
    trusted = {
        m.group(1)
        for s, k, _v in config
        if s in {"global", "system"}
        for m in [_FILTER_KEY.match(k)]
        if m
    }
    for name, text in _attribute_texts(root, git_path):
        for line in text.split("\n"):
            if line.lstrip().startswith("#"):
                continue
            for match in _FILTER_ATTR.finditer(line):
                if match.group(1) not in trusted:
                    raise ToolRefused(
                        f"{name} names filter={match.group(1)}, which your own git "
                        "config does not define; a filter runs a program on add, status "
                        "and checkout, so RACT's git tools refuse this repository",
                        "remove the filter= attribute, or run git yourself",
                    )
    return config


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


def blocked_name(path: str) -> str | None:
    """Why RACT never stages *path* by its name (G-239 A9), or None."""
    name = PurePosixPath(path.replace("\\", "/")).name.lower()
    if name == ".env" or (
        name.startswith(".env.")
        and not name.endswith((".example", ".sample", ".template"))
    ):
        return "an environment file"
    if name.endswith(".pem"):
        return "a PEM key or certificate file"
    if name.endswith(".key"):
        return "a key file"
    if _SSH_KEY_NAME.match(name):
        return "an SSH private key file"
    return None


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
    # What the question shows: the files this add would stage (G-239 D8).
    _shown: list[str] | None = PrivateAttr(default=None)

    check_paths = field_validator("paths")(classmethod(lambda cls, v: _inside(v)))


@dataclass(frozen=True)
class _Staged:
    """The staged change: ``(status, path, added, deleted)`` per file, and its digest."""

    files: tuple[tuple[str, str, str, str], ...]
    digest: str
    scanned: int


class CommitArgs(_Args):
    message: str = Field(min_length=1, max_length=2000)
    # The staged change the question showed (G-239 D8).
    _staged: _Staged | None = PrivateAttr(default=None)

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
    _checked(root)
    done = _run(
        root,
        git_argv(
            "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *args.paths
        ),
    )
    if done.returncode != 0 and not done.cut:
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
        text=text,
        facts={"entries": entries[:500], "count": len(entries)},
        truncated=done.cut,
    )


def git_diff(root: Path, args: DiffArgs) -> ToolResult:
    _checked(root)
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
    if done.returncode != 0 and not done.cut:
        raise ToolRefused(
            f"git diff failed: {_text(done.stderr)[:300]}", "is this a git repository?"
        )
    text = _text(done.stdout)
    return ToolResult(
        text=text or "no difference",
        facts={"staged": args.staged, "bytes": len(done.stdout)},
        truncated=done.cut or len(text.encode("utf-8")) > _CAP,
    )


def git_log(root: Path, args: LogArgs) -> ToolResult:
    _checked(root)
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
    if done.returncode != 0 and not done.cut:
        raise ToolRefused(
            f"git log failed: {_text(done.stderr)[:300]}", "is there a commit yet?"
        )
    commits = []
    # G-239 A7: lines end at a newline only, never at U+2028 or U+2029.
    for line in _text(done.stdout).split("\n"):
        parts = line.split("\t", 3)
        if len(parts) == 4:
            commits.append(dict(zip(("commit", "author", "date", "subject"), parts)))
    return ToolResult(
        text="\n".join("  ".join(c.values()) for c in commits) or "no commits",
        facts={"commits": commits},
        truncated=done.cut,
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


def question_lines(name: str, args: Any) -> list[str]:
    """What the tier-2 question shows: the command quoted, then what it would change.

    LR:: G-239 D8: the argv is quoted, so ``["a b"]`` and ``["a", "b"]`` read
    differently; a commit shows the staged files and the secret scan's result.
    """
    lines = [shlex.join(command_for(name, args))]
    shown = getattr(args, "_shown", None)
    if name == "git_add" and shown is not None:
        lines.append(f"it stages {len(shown)} file(s):")
        lines += [f"  {path}" for path in shown[:40]]
        if len(shown) > 40:
            lines.append(f"  ... {len(shown) - 40} more")
    staged = getattr(args, "_staged", None)
    if name == "git_commit" and staged is not None:
        lines.append(f"it commits {len(staged.files)} staged file(s):")
        for status, path, added, deleted in staged.files[:40]:
            lines.append(f"  {status} {path} (+{added} -{deleted})")
        if len(staged.files) > 40:
            lines.append(f"  ... {len(staged.files) - 40} more")
        lines.append(
            f"secret scan: no secret found in the {staged.scanned} staged file(s) it read whole"
        )
    return lines


def _to_stage(root: Path, paths: list[str]) -> list[str]:
    """The files ``git add -- paths`` would stage: changed, new and not ignored."""
    done = _run(
        root,
        git_argv(
            "ls-files",
            "-z",
            "--modified",
            "--others",
            "--exclude-standard",
            "--",
            *paths,
        ),
    )
    if done.returncode != 0 or done.cut:
        raise ToolRefused(
            f"git could not list what this add stages: {_text(done.stderr)[:300]}",
            "name files that exist",
        )
    return sorted(
        {
            raw.decode("utf-8", errors="replace")
            for raw in done.stdout.split(b"\0")
            if raw
        }
    )


def _refuse_blocked(paths: list[str], verb: str) -> None:
    for path in paths:
        why = blocked_name(path)
        if why is not None:
            raise ToolRefused(
                f"{path} is {why}; RACT does not {verb} it, nothing was {verb}d",
                "keep it out of the repository (add it to .gitignore), or "
                "commit it with git yourself if you mean to",
            )


def _prepare_add(root: Path, args: AddArgs) -> None:
    _checked(root)
    _refuse_blocked(list(args.paths), "stage")
    shown = _to_stage(root, list(args.paths))
    _refuse_blocked(shown, "stage")
    args._shown = shown


def git_add(root: Path, args: AddArgs) -> ToolResult:
    _prepare_add(root, args)
    done = _run(root, git_argv("add", "--", *args.paths))
    if done.returncode != 0:
        raise ToolRefused(
            f"git add failed: {_text(done.stderr)[:300]}", "name files that exist"
        )
    return ToolResult(
        text=f"staged: {', '.join(args.paths)}", facts={"paths": list(args.paths)}
    )


def _staged_files(root: Path) -> tuple[list[tuple[str, str, str, str]], bytes]:
    """``(status, path, mode, blob id)`` per staged file, and git's raw listing."""
    done = _run(
        root,
        git_argv(
            "diff",
            "--cached",
            "--raw",
            "-z",
            "--no-renames",
            "--no-abbrev",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
        ),
    )
    if done.returncode != 0 or done.cut:
        # G-239 A3: a scan that cannot run refuses the commit.
        raise ToolRefused(
            f"the secret scan could not list the staged files: {_text(done.stderr)[:300]}; "
            "nothing was committed",
            "see git's message",
        )
    parts = done.stdout.split(b"\0")
    files = []
    i = 0
    while i < len(parts) - 1:
        meta = parts[i].decode("ascii", errors="replace")
        if not meta.startswith(":"):
            i += 1
            continue
        fields = meta[1:].split()
        path = parts[i + 1].decode("utf-8", errors="replace")
        if len(fields) < 5:
            raise ToolRefused(
                f"the secret scan could not read git's listing near {path!r}; "
                "nothing was committed",
                "see git's message",
            )
        files.append((fields[4][:1], path, fields[1], fields[3]))
        i += 2
    return files, done.stdout


def _blobs(root: Path, ids: list[str]) -> dict[str, bytes]:
    """The staged blobs by id, read whole from the object store (no filter runs)."""
    if not ids:
        return {}
    done = _run(
        root,
        git_argv("cat-file", "--batch"),
        stdin=("\n".join(ids) + "\n").encode("ascii"),
        cap=_SCAN_CAP,
    )
    if done.cut:
        raise ToolRefused(
            "the staged change is over 32 MiB, more than the secret scan reads; "
            "nothing was committed",
            "commit large files with git yourself",
        )
    if done.returncode != 0:
        raise ToolRefused(
            f"the secret scan could not read the staged files: {_text(done.stderr)[:300]}; "
            "nothing was committed",
            "see git's message",
        )
    data, pos, blobs = done.stdout, 0, {}
    for blob_id in ids:
        end = data.find(b"\n", pos)
        header = data[pos:end].decode("ascii", errors="replace").split()
        if end < 0 or len(header) != 3 or header[0] != blob_id:
            raise ToolRefused(
                f"the secret scan could not read the staged blob {blob_id}; "
                "nothing was committed",
                "see git's message",
            )
        size = int(header[2])
        blobs[blob_id] = data[end + 1 : end + 1 + size]
        pos = end + 1 + size + 1
    return blobs


def _decoded(raw: bytes) -> str:
    """A blob as text: UTF-16 by its mark, otherwise UTF-8 with errors replaced."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _scan_blob(path: str, raw: bytes) -> list[tuple[str, int, str]]:
    from ract import egress_scan

    hits = []
    # G-239 A7: lines end at a newline only.
    for number, line in enumerate(_decoded(raw).split("\n"), start=1):
        _out, counts = egress_scan.scan_text(line)
        for kind, pattern in _COMMIT_ONLY_PATTERNS:
            found = len(pattern.findall(line))
            if found:
                counts[kind] = counts.get(kind, 0) + found
        if counts:
            hits.append((path, number, egress_scan.describe(counts)))
    return hits


def _staged_view(root: Path) -> tuple[_Staged, list[tuple[str, int, str]]]:
    """The staged change and the secrets in it.

    LR:: G-239 A1, A2: each staged file is read whole from the index as bytes
    (``git cat-file``: no diff prefixes to parse, no "Binary files differ",
    no attributes and no filter), and every line is scanned. A9: a key or
    environment file is refused by its name.
    """
    files, raw = _staged_files(root)
    if not files:
        raise ToolRefused("nothing is staged", "git_add the files first")
    kept = [f for f in files if f[0] != "D"]
    _refuse_blocked([path for _s, path, _m, _b in kept], "commit")
    # A submodule entry is a commit id, not a file.
    readable = [f for f in kept if f[2] != "160000"]
    blobs = _blobs(root, sorted({blob for _s, _p, _m, blob in readable}))
    hits: list[tuple[str, int, str]] = []
    for _status, path, _mode, blob in readable:
        hits += _scan_blob(path, blobs[blob])
    counts = _run(
        root,
        git_argv(
            "diff",
            "--cached",
            "--numstat",
            "-z",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
        ),  # fmt: skip
    )
    numstat: dict[str, tuple[str, str]] = {}
    if counts.returncode == 0 and not counts.cut:
        for item in counts.stdout.split(b"\0"):
            fields = item.decode("utf-8", errors="replace").split("\t", 2)
            if len(fields) == 3:
                numstat[fields[2]] = (fields[0], fields[1])
    rows = tuple(
        (status, path, *numstat.get(path, ("?", "?"))) for status, path, _m, _b in files
    )
    view = _Staged(rows, hashlib.sha256(raw).hexdigest(), len(readable))
    return view, hits


def staged_secrets(root: Path) -> list[tuple[str, int, str]]:
    """``(file, line, kind)`` for each secret in the staged files, read whole.

    A scan that cannot run raises ``ToolRefused`` (G-239 A3).
    """
    return _staged_view(root)[1]


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


def _clean_view(root: Path) -> _Staged:
    view, hits = _staged_view(root)
    if hits:
        where = "; ".join(f"{f}:{n} ({kind})" for f, n, kind in hits[:10])
        raise ToolRefused(
            f"the staged change holds a secret: {where}; nothing was committed",
            "unstage the file or remove the secret; only the operator at the terminal "
            "can commit it anyway, with git itself",
        )
    return view


def _prepare_commit(root: Path, args: CommitArgs) -> None:
    _checked(root)
    _message_secrets(args.message)  # before the question, as the files are
    args._staged = _clean_view(root)


def _message_secrets(message: str) -> None:
    """D-145: the commit message is scanned like a staged file; a hit refuses."""
    hits = _scan_blob("the commit message", message.encode("utf-8"))
    if hits:
        where = "; ".join(f"line {n} ({kind})" for _f, n, kind in hits[:10])
        raise ToolRefused(
            f"the commit message holds a secret: {where}; nothing was committed",
            "write the message without the value",
        )


def git_commit(root: Path, args: CommitArgs) -> ToolResult:
    _checked(root)
    _message_secrets(args.message)
    view = _clean_view(root)
    if args._staged is not None and args._staged.digest != view.digest:
        raise ToolRefused(
            "the staged change is not the one the question showed; nothing was committed",
            "ask again",
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


def _prepare_checked(root: Path, args: Any) -> None:
    _checked(root)
    if isinstance(args, WorktreeArgs) and args.action == "add" and args.name:
        _worktree_destination(root, args.name)


def git_branch(root: Path, args: BranchArgs) -> ToolResult:
    _checked(root)
    done = _run(root, git_argv("branch", "--", args.name))
    if done.returncode != 0:
        raise ToolRefused(
            f"git branch failed: {_text(done.stderr)[:300]}", "pick a new name"
        )
    return ToolResult(text=f"created branch {args.name}", facts={"branch": args.name})


def _worktree_destination(root: Path, name: str) -> Path:
    """``.ract/worktrees/<name>``, refused when a link or junction is on its path (G-239 C6)."""
    path = Path(root)
    for part in (".ract", "worktrees", *PurePosixPath(name).parts):
        path = path / part
        if path.is_symlink() or _is_junction(path):
            raise ToolRefused(
                f"{path.relative_to(root).as_posix()} is a link; a worktree is made "
                "only in a real folder inside the project",
                "remove the link",
            )
    probe = path
    while not os.path.lexists(probe) and probe != probe.parent:
        probe = probe.parent
    real_root = os.path.normcase(os.path.realpath(root))
    real = os.path.normcase(os.path.realpath(probe))
    if os.path.commonpath([real_root, real]) != real_root:
        raise ToolRefused(
            f"{path.relative_to(root).as_posix()} resolves outside the project",
            "remove the link",
        )
    return path


def git_worktree(root: Path, args: WorktreeArgs) -> ToolResult:
    _checked(root)
    if args.action == "list":
        done = _run(root, git_argv("worktree", "list", "--porcelain"))
        return ToolResult(
            text=_text(done.stdout) or "no worktrees", facts={}, truncated=done.cut
        )
    if not args.name:
        raise ToolRefused("a worktree needs a name", "give name")
    _worktree_destination(root, args.name)
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


def push_handshake_id(url: str, branch: str, head: str) -> str:
    """``git-push:<resolved URL>:<branch>:<commit>``: one approval, one URL, one commit (G-239 B-push)."""
    return f"git-push:{url}:{branch}:{head}"


def push_target(root: Path, remote: str, branch: str) -> tuple[str, str]:
    """The resolved push URL (credentials redacted) and the branch's commit id."""
    from ract.redaction import redact

    url = _run(root, git_argv("remote", "get-url", "--push", remote))
    lines = _text(url.stdout).strip().split("\n")
    if url.returncode != 0 or len(lines) != 1 or not lines[0]:
        raise ToolRefused(
            f"not run, because git has no push URL for the remote {remote}",
            "add the remote with git yourself",
        )
    head = _run(
        root,
        git_argv("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}"),
    )
    sha = _text(head.stdout).strip()
    if head.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", sha):
        raise ToolRefused(
            f"not run, because there is no local branch {branch}",
            "push a branch that exists",
        )
    return redact(lines[0]), sha


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
    config = _checked(root)
    # G-239 B-push: the repository may not choose the transport or the URL.
    set_here = sorted(
        {
            key
            for scope, key, _v in config
            if scope in _REPO_SCOPES and _PUSH_KEYS.match(key)
        }
    )
    if set_here:
        raise ToolRefused(
            f"not run, because the repository's own config sets {', '.join(set_here)}, "
            "which can run a program or change where a push goes",
            "remove it from .git/config; put transport and credential settings in your "
            "global git config",
        )
    url, head = push_target(root, args.remote, args.branch)
    handshake = push_handshake_id(url, args.branch, head)
    if not HandshakeRegistry(ctx.project).is_approved(handshake):
        raise ToolRefused(
            f"not run, because the handshake {handshake} is not approved with your signature",
            f"`ract handshakes approve {handshake}` at a terminal, then ask again",
        )
    # D8 applies to the push too: fsmonitor off and an empty hooks folder,
    # unless the grant's push rule says git_hooks: true.
    hardening = git_argv(hooks=bool(getattr(rule, "git_hooks", False)))[1:-1]
    return run_under_rule(
        root,
        ctx,
        rule,
        ["git", *hardening, "push", args.remote, args.branch],
        args.reason,
        kind="push",
        refused_hint="push only a named remote and branch",
        notes=[
            f"this sends commits to the remote {args.remote}",
            f"the push URL is {url}",
            f"the branch {args.branch} is at {head}",
            # G-243: what the approval covers, and what a repository may not set.
            "the approval covers this URL and this commit only; a later commit "
            "asks again",
            "a pushurl or credential.helper in the repository's own .git/config "
            "refuses the push; keep them in your global git config",
        ],
    )


def _spec(
    name: str,
    tier: CapabilityTier,
    model: type[BaseModel],
    run,
    mutates: bool,
    prepare=None,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        tier=tier,
        args_model=model,
        mutates=mutates,
        result_cap_bytes=_CAP,
        run=run,
        prepare=prepare,
    )


GIT_TOOLS = (
    _spec("git_status", CapabilityTier.TIER_0_READ, PathsArgs, git_status, False),
    _spec("git_diff", CapabilityTier.TIER_0_READ, DiffArgs, git_diff, False),
    _spec("git_log", CapabilityTier.TIER_0_READ, LogArgs, git_log, False),
    _spec("git_add", CapabilityTier.TIER_2_ENV, AddArgs, git_add, True, _prepare_add),
    _spec(
        "git_commit",
        CapabilityTier.TIER_2_ENV,
        CommitArgs,
        git_commit,
        True,
        _prepare_commit,
    ),
    _spec(
        "git_branch",
        CapabilityTier.TIER_2_ENV,
        BranchArgs,
        git_branch,
        True,
        _prepare_checked,
    ),
    _spec(
        "git_worktree",
        CapabilityTier.TIER_2_ENV,
        WorktreeArgs,
        git_worktree,
        True,
        _prepare_checked,
    ),
    _spec("git_push", CapabilityTier.TIER_3_EXTERNAL, PushArgs, git_push, True),
)

__all__ = [
    "GIT_TOOLS",
    "blocked_name",
    "command_for",
    "git_argv",
    "git_env",
    "push_handshake_id",
    "push_target",
    "question_lines",
    "staged_secrets",
]
