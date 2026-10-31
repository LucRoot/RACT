"""Command matching for tier 3 (ADR-0048 D4): refuse, ask, or match a rule.

LR:: A command the model asks for is classified before anything runs.
Some commands no rule can allow (the hard floor): shells and inline code
(``sh``, ``bash -lc``, ``python -c``, ``node -e``), privilege changes,
RACT governance from inside a run, package publishing; runners that pick
their command at run time (``xargs``, ``find -exec``) never match either.
A deny rule refuses. An argv whose name is not plain ASCII is refused (a
look-alike ``pуtest`` is not ``pytest``). ``argv[0]`` is resolved through a
``PATH`` with the project's folders removed, so a ``./pytest`` shim planted
in the repository does not satisfy a ``pytest`` rule; a path naming a file
in the project runs repository code and says so. Wrappers (``env``,
``nice``, ``nohup``, ``timeout``, ``time``, ``stdbuf``, ``ionice``) are
stripped and the inner command is matched. Global options before a
subcommand (``git -c``, ``git -C``, ``npm --prefix``) and known output or
execution flags (``git show --output``, ``--upload-pack``, ``--ext-diff``)
never match an allow rule; remote git always asks. A ``.bat`` or ``.cmd``
target runs through ``cmd.exe``, which reparses its arguments, so it runs
only when every argument is plain. Everything else asks in ``ask`` mode;
``matches`` names the allow rule it fits, for the prompt and for the
``allowlist`` mode of slice (d).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ract.policy.grant import Policy

Outcome = Literal["refused", "asks", "matches"]

_WRAPPERS = {"env", "nice", "nohup", "timeout", "time", "stdbuf", "ionice"}
_NEVER = {
    "xargs": "runs a command chosen at run time",
    "parallel": "runs a command chosen at run time",
    "watch": "runs a command chosen at run time",
    "script": "runs a command chosen at run time",
    "sudo": "changes privilege",
    "doas": "changes privilege",
    "su": "changes privilege",
    "runas": "changes privilege",
    "pkexec": "changes privilege",
}
_SHELLS = {"sh", "bash", "zsh", "fish", "dash", "ksh", "cmd", "powershell", "pwsh"}
# G-214 M1: how each interpreter takes code on its command line. A token
# among the interpreter's own options (before -m, --, or the script) that
# matches the pattern is inline code; clustered and attached forms included.
_EVAL = {
    "python": re.compile(r"^(-[A-Za-z]*c|--command)"),
    "pypy": re.compile(r"^(-[A-Za-z]*c|--command)"),
    "py": re.compile(r"^(-[A-Za-z]*c|--command)"),
    "node": re.compile(r"^(-[A-Za-z]*[eEp]|--eval|--print)"),
    "bun": re.compile(r"^(-[A-Za-z]*[ep]|--eval|--print)"),
    "perl": re.compile(r"^-[A-Za-z]*[eE]"),
    "ruby": re.compile(r"^-[A-Za-z]*e"),
    "php": re.compile(r"^-[A-Za-z]*r"),
    "lua": re.compile(r"^-[A-Za-z]*e"),
    "rscript": re.compile(r"^-[A-Za-z]*e"),
    "osascript": re.compile(r"^-[A-Za-z]*e"),
}
# Options that take the next token as their value (``python -X utf8 -c``).
_VALUE_OPTIONS = {
    "python": {"-X", "-W", "-Q"},
    "pypy": {"-X", "-W", "-Q"},
    "py": {"-X", "-W", "-Q"},
    "node": {"-r", "--require", "--import", "--loader"},
    "bun": {"-r", "--preload"},
}
# Programs whose argument is itself code, whatever its options.
_ALWAYS_CODE = {"awk", "gawk", "mawk", "nawk", "sed"}
_GOVERNANCE = {"policy", "handshakes", "intent", "operator-queue", "config", "provider"}
_PUBLISH = [
    ("twine", "upload"),
    ("npm", "publish"),
    ("cargo", "publish"),
    ("poetry", "publish"),
    ("uv", "publish"),
    ("gh", "release"),
]
_SUBCOMMAND_TOOLS = {
    "git",
    "npm",
    "pnpm",
    "yarn",
    "pip",
    "uv",
    "cargo",
    "go",
    "dotnet",
    "docker",
    "kubectl",
}
# G-239 D12: the plumbing that talks to a remote asks too; ``archive``
# asks when it names ``--remote``.
_REMOTE_GIT = {
    "push",
    "pull",
    "fetch",
    "clone",
    "ls-remote",
    "remote",
    "submodule",
    "send-pack",
    "fetch-pack",
    "http-push",
    "http-fetch",
    "upload-pack",
    "receive-pack",
}
_DANGEROUS_FLAGS = {
    "--output",
    "--upload-pack",
    "--receive-pack",
    "--ext-diff",
    "--exec",
}
_FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir", "-delete"}
_PLAIN_ARG = re.compile(r"^[A-Za-z0-9_./:=@+-]+$")


@dataclass(frozen=True)
class Match:
    """How a command fares: refused, asks, or matches a rule, and why."""

    outcome: Outcome
    reason: str
    argv: tuple[str, ...] = ()
    executable: str | None = None
    rule_id: str | None = None
    repository_code: bool = False
    notes: tuple[str, ...] = field(default=())
    # G-215 C3: the executable's SHA-256 when it was resolved, so the run can
    # refuse a file that changed between the classification and the spawn.
    executable_sha256: str | None = None


def file_digest(path: str) -> str | None:
    """The SHA-256 of the file at *path*, read in chunks, or None if it cannot be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1_048_576), b""):
                digest.update(chunk)
    except OSError as exc:
        print(f"[matcher] the executable was not hashed: {exc}", flush=True)
        return None
    return digest.hexdigest()


def _name(arg: str) -> str:
    """The command name as matched: the base name, lower case, without ``.exe``.

    A versioned or windowed interpreter is its family (``python3.12``,
    ``pythonw``, ``pypy3`` are ``python`` and ``pypy``; G-214 M1).
    """
    base = Path(arg.replace("\\", "/")).name.lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return re.sub(r"^(python|pypy)[0-9.]*w?$", r"\1", base)


def inline_code(name: str, args: list[str]) -> bool:
    """True when *args* give interpreter *name* code to run on the command line (M1)."""
    if name in _ALWAYS_CODE:
        return True
    if name == "deno":
        return next((a for a in args if not a.startswith("-")), "") == "eval"
    pattern = _EVAL.get(name)
    if pattern is None:
        return False
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        if token in ("-m", "--") or not token.startswith("-"):
            return False  # the module, the end of options, or the script
        if pattern.match(token):
            return True
        if token in _VALUE_OPTIONS.get(name, set()):
            skip = True
    return False


def wrapped_code(args: list[str]) -> str | None:
    """A shell or inline interpreter anywhere after ``argv[0]`` (M2); its name, or None."""
    for i, token in enumerate(args):
        if token.startswith("-"):
            continue
        name = _name(token)
        if name in _SHELLS:
            return name
        if name in _EVAL or name in {"deno"} | _ALWAYS_CODE:
            if inline_code(name, args[i + 1 :]):
                return name
    return None


def _inside(path: Path, roots: list[Path]) -> bool:
    real = Path(os.path.realpath(path))
    for root in roots:
        try:
            real.relative_to(Path(os.path.realpath(root)))
            return True
        except ValueError:
            continue
    return False


def resolve_executable(name: str, path_env: str, outside: list[Path]) -> str | None:
    """*name* on *path_env*, as an absolute path outside every folder in *outside* (M3).

    Walks the PATH itself with PATHEXT on Windows: ``shutil.which`` looks in
    the current folder first there, so a ``pytest.cmd`` the model wrote into
    the step worktree would be chosen. The current folder is never searched,
    and a result inside the project or the worktree (through a link too) is
    never returned.
    """
    if os.name == "nt":
        exts = [
            e for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e
        ]
        names = [name] if Path(name).suffix else [name + e for e in exts]
    else:
        names = [name]
    for entry in path_env.split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue  # a relative PATH entry means the current folder: never
        for candidate in names:
            full = Path(entry) / candidate
            if not full.is_file():
                continue
            if os.name != "nt" and not os.access(full, os.X_OK):
                continue
            if _inside(full, outside):
                continue
            return str(full.absolute())
    return None


def _strip_wrappers(argv: list[str]) -> tuple[list[str], list[str], str | None]:
    """The inner command, the ``VAR=value`` names set, or a refusal reason."""
    names: list[str] = []
    while argv and _name(argv[0]) in _WRAPPERS:
        wrapper = _name(argv[0])
        rest = argv[1:]
        if wrapper == "env":
            while rest and "=" in rest[0] and not rest[0].startswith("-"):
                names.append(rest[0].split("=", 1)[0])
                rest = rest[1:]
            if rest and rest[0].startswith("-"):
                return [], names, "env options change the environment (env -i, -u, -S)"
        elif wrapper == "timeout":
            while rest and rest[0].startswith("-"):
                rest = rest[1:]
            rest = rest[1:]  # the duration
        else:
            while rest and rest[0].startswith("-"):
                rest = rest[1:]
                if (
                    wrapper in {"nice", "ionice"}
                    and rest
                    and rest[0].lstrip("-").isdigit()
                ):
                    rest = rest[1:]
        argv = rest
    return argv, names, None


def _scrubbed_path(project: Path, path_env: str | None) -> str:
    """``PATH`` without the project and every folder inside it (D4)."""
    root = os.path.normcase(os.path.realpath(project))
    kept = []
    for entry in (
        path_env if path_env is not None else os.environ.get("PATH", "")
    ).split(os.pathsep):
        if not entry:
            continue
        real = os.path.normcase(os.path.realpath(entry))
        if real == root or real.startswith(root + os.sep):
            continue
        kept.append(entry)
    return os.pathsep.join(kept)


def _prefix(rule: list[str], argv: list[str]) -> bool:
    if len(rule) > len(argv):
        return False

    def is_path(arg: str) -> bool:
        return "/" in arg or "\\" in arg

    # A path in the project matches only a rule that names that path (D4: a
    # planted ./pytest is not pytest); a bare name matches only a bare name.
    if is_path(rule[0]) != is_path(argv[0]):
        return False
    if is_path(argv[0]):
        if os.path.normpath(rule[0]).lower() != os.path.normpath(argv[0]).lower():
            return False
    elif _name(rule[0]) != _name(argv[0]):
        return False
    return all(a == b for a, b in zip(rule[1:], argv[1 : len(rule)]))


def classify(
    argv: list[str] | tuple[str, ...],
    policy: Policy | None,
    project: Path | str,
    *,
    model_written: frozenset[str] = frozenset(),
    path_env: str | None = None,
    also_outside: tuple[Path, ...] = (),
) -> Match:
    """Refuse, ask or match *argv* under *policy* for the project at *project* (D4)."""
    project = Path(project)
    original = tuple(str(a) for a in argv)
    if not original or not original[0]:
        return Match("refused", "the command is empty", original)
    if any("\x00" in a for a in original):
        return Match("refused", "an argument holds a NUL character", original)
    inner, env_names, why = _strip_wrappers(list(original))
    if why:
        return Match("refused", why, original)
    if not inner:
        return Match("refused", "the wrapper names no command", original)
    if not inner[0].isascii():
        return Match(
            "refused",
            f"{inner[0]!r} is not a plain ASCII name (a look-alike is not the command)",
            original,
        )
    name = _name(inner[0])
    args = inner[1:]

    # ---- the hard floor: no rule allows these in argv mode
    if name in _NEVER:
        return Match("refused", f"{name} never matches: it {_NEVER[name]}", original)
    if name in _SHELLS:
        return Match(
            "refused", f"{name} is a shell: shells run only in shell mode", original
        )
    if inline_code(name, args):
        # Only the interpreter's own options count, up to -m or the script:
        # ``python -m pytest -c conf.ini`` is pytest's -c.
        return Match(
            "refused", f"{name} with inline code runs only in shell mode", original
        )
    wrapped = wrapped_code(args)
    if wrapped:
        return Match(
            "refused",
            f"a wrapped {wrapped} with inline code or a shell runs only in shell mode",
            original,
        )
    if name == "find" and _FIND_EXEC & set(args):
        return Match(
            "refused", "find with -exec, -ok or -delete never matches", original
        )
    is_ract = (
        name == "ract"
        or (name in {"python", "py"} and args[:2] == ["-m", "ract"])
        or (name in {"python", "py"} and args[:2] == ["-m", "ract.cli"])
    )
    ract_args = args[2:] if name != "ract" else args
    if is_ract and ract_args and ract_args[0] in _GOVERNANCE:
        return Match(
            "refused", "RACT's own governance is not run from inside a run", original
        )
    for tool, sub in _PUBLISH:
        if name == tool and sub in args[:2]:
            return Match("refused", f"{tool} {sub} publishes a package", original)

    # ---- executable resolution through a PATH without the project
    in_repo = "/" in inner[0] or "\\" in inner[0]
    if in_repo:
        candidate = (project / inner[0]).resolve()
        try:
            candidate.relative_to(project.resolve())
        except ValueError:
            return Match("refused", f"{inner[0]} is outside the project", original)
        if not candidate.is_file():
            return Match(
                "refused", f"{inner[0]} does not exist in the project", original
            )
        executable = str(candidate)
    else:
        found = resolve_executable(
            inner[0], _scrubbed_path(project, path_env), [project, *also_outside]
        )
        if found is None:
            return Match(
                "refused",
                f"{inner[0]} is not found on PATH outside the project",
                original,
            )
        executable = found
    if Path(executable).suffix.lower() in {".bat", ".cmd"} and not all(
        _PLAIN_ARG.match(a) for a in args
    ):
        return Match(
            "refused",
            f"{Path(executable).name} runs through cmd.exe, which reparses arguments; "
            "an argument here is not plain. hint: use shell mode",
            original,
            executable,
        )

    # ---- deny rules win
    if policy is not None:
        for rule in policy.commands.deny:
            if _prefix(rule.argv, inner):
                return Match(
                    "refused", f"denied by the rule {rule.argv}", original, executable
                )

    notes: list[str] = []
    if in_repo:
        notes.append("it runs repository code")
    asks_because: str | None = None
    if name == "git" and args:
        sub = next((a for a in args if not a.startswith("-")), "")
        if args[0].startswith("-"):
            asks_because = "git global options change what the subcommand does"
        elif sub in _REMOTE_GIT or (
            sub == "archive"
            and any(a == "--remote" or a.startswith("--remote=") for a in args)
        ):
            asks_because = "remote git always asks"
    elif name in _SUBCOMMAND_TOOLS and args and args[0].startswith("-"):
        asks_because = f"{name} global options change what the subcommand does"
    if asks_because is None and any(
        a.split("=", 1)[0] in _DANGEROUS_FLAGS for a in args
    ):
        asks_because = "an output or execution flag changes what the command does"
    if asks_because is None and (
        name in {"pytest", "py.test"}
        or (name in {"python", "python3", "py"} and args[:2] == ["-m", "pytest"])
    ):
        plugin = next((args[i + 1] for i, a in enumerate(args[:-1]) if a == "-p"), None)
        if plugin and (project / (plugin.replace(".", "/") + ".py")).is_file():
            asks_because = "pytest -p loads a plugin from the project"
    written = [a for a in args if a.replace("\\", "/") in model_written]
    if asks_because is None and written:
        asks_because = f"it names a file written in this session ({written[0]})"

    if policy is not None and asks_because is None:
        for allow in policy.commands.allow:
            if not _prefix(allow.argv, inner):
                continue
            if any(n not in allow.env_extra for n in env_names):
                asks_because = "it sets an environment variable the rule does not name"
                break
            return Match(
                "matches",
                f"the rule {allow.id}",
                original,
                executable,
                allow.id,
                in_repo,
                tuple(notes),
                file_digest(executable),
            )
    return Match(
        "asks",
        asks_because or "no rule matches it",
        original,
        executable,
        None,
        in_repo,
        tuple(notes),
        file_digest(executable),
    )


__all__ = ["Match", "classify", "file_digest"]
