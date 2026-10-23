"""Extract and classify the ``ract`` commands in the user docs (B-076).

Nothing here runs a doc line through a shell. Commands are split with shlex
and started with an argv list; the parser help is read in-process.
"""

from __future__ import annotations

import io
import os
import re
import shlex
import subprocess
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

DOC_FILES = (
    "README.md",
    "docs/QUICKSTART.md",
    "docs/PROVIDER_SETUP.md",
    "docs/UPGRADING.md",
    "docs/SESSION_GUIDE.md",
)
FENCE_TAGS = {"bash", "sh", "console", "powershell"}
# Commands the scratch-project run may execute: an allowlist, not a denylist.
RUN_ALLOWLIST = (
    ("--version",),
    ("doctor",),
    ("trust", "--list"),
    ("setup", "--print-defaults"),
)
TOP_LEVEL_FLAGS = {"--version", "--help", "-h", "--plain", "--no-color"}
# Anything matching these is never run, and its flags are not read.
NEVER_WORDS = re.compile(r"\b(pip|rm|sudo|curl|wget|chmod|dd|mkfs)\b|git\s+push")
NON_LOOPBACK_URL = re.compile(r"https?://(?!127\.0\.0\.1|localhost|\[::1\])")
SHELL_META = re.compile(r"[;&|`<>]|\$\(")
COMMENT = re.compile(r"\s+#.*$")
PLACEHOLDER = re.compile(r"<[\w.\-/]+>")
QUOTED_INTENT = re.compile(r"^ract\s+[\"']")
FLAG = re.compile(r"^--[a-zA-Z][\w-]*")
MAIN = "import sys; from ract.cli import main; sys.exit(main(sys.argv[1:]))"


@dataclass(frozen=True)
class Block:
    file: str
    line: int
    command: str


@dataclass(frozen=True)
class Result:
    status: str  # "run", "flag-ok", "fail", "not-run"
    reason: str
    where: str


@dataclass
class Messages:
    scanned: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rows: list[tuple[str, int, str, str, str]] = field(default_factory=list)


def extract_blocks(path: Path) -> list[Block]:
    """Lines of shell-tagged fenced blocks that start with ``ract``."""
    blocks: list[Block] = []
    in_block = False
    tag = ""
    for number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw.strip()
        if stripped.startswith("```"):
            if in_block:
                in_block, tag = False, ""
            else:
                in_block, tag = True, stripped[3:].strip().lower()
            continue
        if not in_block or tag not in FENCE_TAGS:
            continue
        command = stripped[2:] if stripped.startswith("$ ") else stripped
        if command == "ract" or command.startswith("ract "):
            blocks.append(Block(path.name, number, command))
    return blocks


def _argv(command: str) -> list[str]:
    """Words of a doc line. A trailing # comment is dropped, as a shell would."""
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    return list(lexer)


def classify(command: str) -> str:
    """``run``, ``flag`` or ``never``. ``never`` wins over every other reading."""
    # A trailing comment and a <placeholder> are doc text, not shell syntax.
    body = PLACEHOLDER.sub("x", COMMENT.sub("", command))
    if NEVER_WORDS.search(body) or NON_LOOPBACK_URL.search(body):
        return "never"
    if SHELL_META.search(body):
        return "never"
    try:
        argv = _argv(command)
    except ValueError:
        return "never"
    if argv[:1] != ["ract"]:
        return "never"
    args = argv[1:]
    for allowed in RUN_ALLOWLIST:
        if tuple(args[: len(allowed)]) == allowed:
            return "run"
    return "flag"


_HELP: dict[str, str] = {}


def _help(*words: str) -> str | None:
    """``ract <words> --help`` from the real parser, cached. None for an unknown verb."""
    key = " ".join(words)
    if key in _HELP:
        return _HELP[key]
    from ract import cli

    if words and words[0] not in cli.CLI_VERBS:
        return None
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        try:
            cli.main([*words, "--help"])
        except SystemExit:
            pass
    _HELP[key] = buffer.getvalue()
    return _HELP[key]


def _headless_help() -> str:
    """The headless parser's help (``ract -p``), cached."""
    if "-p" not in _HELP:
        from ract import headless

        _HELP["-p"] = headless._parser().format_help()
    return _HELP["-p"]


def _check_flags(args: list[str], help_text: str, label: str, where: str) -> Result:
    for token in args:
        if FLAG.match(token):
            name = token.split("=", 1)[0]
            if name not in help_text:
                return Result("fail", f"flag {name} is not in {label} --help", where)
    return Result("flag-ok", "verb and flags exist", where)


def check_block(block: Block) -> Result:
    where = f"{block.file}:{block.line}: {block.command}"
    kind = classify(block.command)
    if kind == "never":
        return Result(
            "not-run",
            "never executed (install, delete, push, network or shell syntax)",
            where,
        )
    argv = _argv(block.command)[1:]
    if not argv:
        return Result("flag-ok", "bare ract", where)
    if kind == "run":
        return Result("run", "run in a scratch project", where)
    if argv[0] == "-p":
        return _check_flags(argv[1:], _headless_help(), "ract -p", where)
    if argv[0].startswith("-"):
        name = argv[0].split("=", 1)[0]
        if name in TOP_LEVEL_FLAGS:
            return Result("flag-ok", "top-level flag exists", where)
        return Result("fail", f"unknown top-level flag {name}", where)
    from ract import cli

    if argv[0] not in cli.CLI_VERBS:
        if QUOTED_INTENT.match(block.command):
            # A quoted intent runs as `ract run "..."` does.
            return _check_flags(argv[1:], _help("run") or "", "ract run", where)
        return Result("fail", f"unknown verb: {argv[0]}", where)
    help_text = _help(argv[0]) or ""
    if len(argv) > 1 and not argv[1].startswith("-"):
        # A subcommand, such as `conformance run`: its own help counts too.
        sub_help = _help(argv[0], argv[1])
        if sub_help:
            help_text += sub_help
    return _check_flags(argv[1:], help_text, f"ract {argv[0]}", where)


def _child_env() -> dict[str, str]:
    """The parent's environment, minus colour switches, RACT_* and any key or token.

    A doc command must not see the operator's keys, and must not pick up a
    RACT_* setting from the shell that runs the tests (G-133).
    """
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in {"NO_COLOR", "FORCE_COLOR"}:
            continue
        if key.startswith("RACT_") or key.endswith(("_KEY", "_TOKEN")):
            continue
        env[key] = value
    return env


def run_allowed(block: Block, workdir: Path, timeout: float = 120.0) -> Result:
    """Run one allowlisted command in ``workdir`` with no shell. Exit 0 is ``ran``."""
    where = f"{block.file}:{block.line}: {block.command}"
    argv = _argv(block.command)
    env = _child_env()
    proc = subprocess.run(
        [sys.executable, "-c", MAIN, *argv[1:]],
        cwd=workdir,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if proc.returncode == 0:
        return Result("ran", "exit 0", where)
    return Result("fail", f"exit {proc.returncode}", where)


def scan(paths) -> Messages:
    """Scan each doc. A missing doc is skipped with a message, never an error."""
    messages = Messages()
    for path in paths:
        path = Path(path)
        if not path.is_file():
            messages.skipped.append((str(path), "not in the repository; skipped"))
            continue
        messages.scanned.append(str(path))
        for block in extract_blocks(path):
            result = check_block(block)
            if result.status == "fail":
                messages.errors.append(f"{result.where}: {result.reason}")
            messages.rows.append(
                (block.file, block.line, block.command, result.status, result.reason)
            )
    return messages


def render_table(rows: list[tuple[str, int, str, str, str]]) -> str:
    """The generated ``docs/DOC_COMMANDS.md`` body, one row per doc command."""
    lines = [
        "# Commands in the user docs",
        "",
        "Generated by `tests/docs/test_doc_commands.py`. Do not edit by hand.",
        "",
        "| File | Line | Command | Status | Reason |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for file, line, command, status, reason in rows:
        cell = command.replace("|", "\\|")
        lines.append(f"| {file} | {line} | `{cell}` | {status} | {reason} |")
    return "\n".join(lines) + "\n"


def generate_table(root: Path, workdir: Path, prepare=None) -> str:
    """The whole table: scan the docs, run the run-class rows in ``workdir``, render.

    ``prepare(workdir)`` sets up the project (a config that points at the fake
    server) before the run-class commands run. Writes nothing.
    """
    messages = scan([root / name for name in DOC_FILES])
    if prepare is not None:
        prepare(workdir)
    rows = []
    for file, line, command, status, reason in messages.rows:
        if status == "run":
            result = run_allowed(Block(file, line, command), workdir)
            status, reason = result.status, result.reason
        rows.append((file, line, command, status, reason))
    return render_table(rows)


def main(argv: list[str]) -> int:
    """``python tests/docs/doc_commands.py --write`` regenerates docs/DOC_COMMANDS.md."""
    if argv != ["--write"]:
        print("usage: python tests/docs/doc_commands.py --write")
        return 2
    import tempfile

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from tests.fixtures.fake_model_server import FakeModelServer
    from tests.ux.run_baseline import _configure

    with (
        tempfile.TemporaryDirectory() as tmp,
        FakeModelServer("j1_first_run") as server,
    ):
        workdir = Path(tmp) / "project"
        workdir.mkdir()
        text = generate_table(
            root,
            workdir,
            prepare=lambda folder: _configure(folder, server.base_url, "fake-coder"),
        )
    (root / "docs" / "DOC_COMMANDS.md").write_text(text, encoding="utf-8", newline="\n")
    print("wrote docs/DOC_COMMANDS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
