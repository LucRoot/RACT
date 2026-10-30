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

import os
import re
import shutil
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
_INLINE = {
    "python": {"-c"},
    "python3": {"-c"},
    "py": {"-c"},
    "node": {"-e", "--eval", "-p", "--print"},
    "perl": {"-e", "-E"},
    "ruby": {"-e"},
    "deno": {"eval"},
}
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
_REMOTE_GIT = {"push", "pull", "fetch", "clone", "ls-remote", "remote", "submodule"}
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


def _name(arg: str) -> str:
    """The command name as matched: the base name, lower case, without ``.exe``."""
    base = Path(arg.replace("\\", "/")).name.lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


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
    if name in _INLINE:
        # Only the interpreter's own options count: those before -m or the
        # script (``python -m pytest -c conf.ini`` is pytest's -c).
        own: list[str] = []
        for a in args:
            if a == "-m" or not a.startswith("-"):
                if name == "deno":
                    own.append(a)  # deno's subcommand: ``deno eval``
                break
            own.append(a)
        if any(a in _INLINE[name] for a in own):
            return Match(
                "refused", f"{name} with inline code runs only in shell mode", original
            )
    if name == "find" and _FIND_EXEC & set(args):
        return Match(
            "refused", "find with -exec, -ok or -delete never matches", original
        )
    is_ract = (
        name == "ract"
        or (name in {"python", "python3", "py"} and args[:2] == ["-m", "ract"])
        or (name in {"python", "python3", "py"} and args[:2] == ["-m", "ract.cli"])
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
        found = shutil.which(inner[0], path=_scrubbed_path(project, path_env))
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
        elif sub in _REMOTE_GIT:
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
        for rule in policy.commands.allow:
            if not _prefix(rule.argv, inner):
                continue
            if any(n not in rule.env_extra for n in env_names):
                asks_because = "it sets an environment variable the rule does not name"
                break
            return Match(
                "matches",
                f"the rule {rule.id}",
                original,
                executable,
                rule.id,
                in_repo,
                tuple(notes),
            )
    return Match(
        "asks",
        asks_because or "no rule matches it",
        original,
        executable,
        None,
        in_repo,
        tuple(notes),
    )


__all__ = ["Match", "classify"]
