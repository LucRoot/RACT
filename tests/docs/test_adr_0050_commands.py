"""B-150: the command lines ADR-0050 quotes as existing are in the CLI help.

Only the ``console`` blocks are checked (the ADR keeps the proposed
``ract verify`` in a ``text`` block, since it does not exist yet). For each
line, the verb and subcommand must exist and every ``--flag`` must appear in
that command's ``--help``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADR = (
    ROOT
    / "docs"
    / "ADRs"
    / "ADR-0050-rootknot-and-trace-attestation-and-ract-verify.md"
)


def _console_lines() -> list[str]:
    text = ADR.read_text(encoding="utf-8")
    blocks = re.findall(r"```console\n(.*?)```", text, flags=re.S)
    return [
        line.strip() for block in blocks for line in block.splitlines() if line.strip()
    ]


def _help(words: list[str]) -> str:
    done = subprocess.run(
        [sys.executable, "-m", "ract.cli", *words, "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
    )
    assert done.returncode == 0, (
        f"ract {' '.join(words)} --help failed: {done.stderr[-300:]}"
    )
    return done.stdout


def test_the_adr_quotes_some_commands() -> None:
    assert len(_console_lines()) >= 3


@pytest.mark.parametrize("line", _console_lines())
def test_each_quoted_command_exists(line: str) -> None:
    words = line.split()
    assert words[0] == "ract"
    command = [w for w in words[1:] if not w.startswith(("-", "<"))]
    flags = [w for w in words[1:] if w.startswith("--")]
    text = _help(command)
    for flag in flags:
        assert flag in text, f"{flag} is not in `ract {' '.join(command)} --help`"
