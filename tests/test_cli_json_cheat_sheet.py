"""Tests for the RACT CLI JSON cheat sheet accuracy."""

from __future__ import annotations


import contextlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


def _extract_commands(md_path: Path):
    text = md_path.read_text(encoding="utf-8")
    commands = []
    for line in text.splitlines():
        if not line.startswith("| `ract "):
            continue
        # Extract the backtick-quoted command in the first cell.
        m = re.search(r"`((?:ract|ract)\s+[^`]+)`", line)
        if not m:
            continue
        commands.append(m.group(1))
    return commands


def _run(args):
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_in_process(args):
    """``ract <args>`` through the CLI's ``main`` in this process (B-152).

    Each subprocess start costs about 1.4 s of imports; the help text and the
    exit code are the same either way, and the module entry itself is checked
    once by ``test_the_cli_module_starts_as_a_program``.
    """
    from ract import cli

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(args))
        except SystemExit as exc:  # argparse ends --help and usage errors this way
            code = (
                exc.code
                if isinstance(exc.code, int)
                else (0 if exc.code is None else 1)
            )
    return SimpleNamespace(
        returncode=code or 0, stdout=out.getvalue(), stderr=err.getvalue()
    )


def test_the_cli_module_starts_as_a_program():
    result = _run(["--help"])
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()


def test_cli_json_cheat_sheet_lists_at_least_fifteen_commands():
    cheat_sheet = Path(__file__).parent.parent / "docs" / "cli_json_cheat_sheet.md"
    commands = _extract_commands(cheat_sheet)
    assert len(commands) >= 15, f"only {len(commands)} commands documented"


def test_cli_json_cheat_sheet_commands_exist():
    cheat_sheet = Path(__file__).parent.parent / "docs" / "cli_json_cheat_sheet.md"
    commands = _extract_commands(cheat_sheet)
    assert commands
    failures = []
    for cmd in commands:
        tokens = cmd.split()[1:]  # drop the 'ract'/'ract' prefix
        # Try the command's own help to confirm it is wired.
        result = _run_in_process([*tokens, "--help"])
        output = result.stdout + result.stderr
        # A few commands (skills list) are manually parsed and don't expose --help,
        # so also accept a successful JSON invocation when --json is present.
        if result.returncode != 0 and "--json" in cmd:
            json_result = _run([*tokens])
            if json_result.returncode == 0:
                try:
                    json.loads(json_result.stdout)
                    continue
                except json.JSONDecodeError:
                    pass
        if "--json" in cmd and "--json" not in output:
            # Some parsers put --json on a parent parser (e.g. mcp, retrieval);
            # accept if the help succeeded at all.
            if result.returncode != 0:
                failures.append(
                    f"{cmd}: help failed rc={result.returncode}\n{output[:200]}"
                )
        elif result.returncode not in (0, 1):
            failures.append(f"{cmd}: unexpected rc={result.returncode}\n{output[:200]}")
    assert not failures, "\n".join(failures)
