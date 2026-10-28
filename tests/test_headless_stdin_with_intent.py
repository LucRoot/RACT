"""Adjudication row 16: `ract -p "<intent>"` must not wait on an open stdin.

Reproduced 2026-10-26 (scratchpad probe): with an intent on the command line and
stdin inherited from a parent that never closes it, the run hung. The read happens
in headless run logic (`src/ract/headless.py`, `run_headless`, the `_read_stdin`
call), which is B-035's area, so the fix is a handoff, not a change here. This test
pins the defect as an expected failure until the handoff lands.
"""

from __future__ import annotations

import pytest

from ract import headless


class _OpenStdin:
    """Stands in for an inherited stdin: not a terminal, and a read that would block."""

    def __init__(self) -> None:
        self.reads = 0

    def isatty(self) -> bool:
        return False

    def read(self) -> str:
        self.reads += 1
        return ""


@pytest.mark.xfail(
    strict=True,
    reason="headless.run_headless reads stdin even when an intent is given (B-035 handoff)",
)
def test_an_intent_on_the_command_line_does_not_read_stdin(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stdin = _OpenStdin()
    headless.run_headless(
        ["-p", "add a greeting", "--config", "missing.yaml"],
        stdin=stdin,
    )
    assert stdin.reads == 0
