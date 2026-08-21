"""Bare group-verb prints help and exits 0 (Lens A M7).

v0.5.1 wiring module_10: ``ract retrieval`` / ``ract memory`` /
``ract plan`` used to return exit 1 after printing help. That broke
CI capability probes like ``ract retrieval 2>/dev/null || echo
"no retrieval"``. The regression now expects exit 0.
"""

from __future__ import annotations

import contextlib
import io

from ract.cli import main
from ract.memory.cli_memory import memory_command


def _capture(fn, *args) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = fn(*args)
    return code, buf.getvalue()


def test_bare_retrieval_exits_zero() -> None:
    code, out = _capture(main, ["retrieval"])
    assert code == 0
    assert "retrieval" in out.lower() or "usage" in out.lower()


def test_bare_plan_exits_zero() -> None:
    code, out = _capture(main, ["plan"])
    assert code == 0


def test_bare_memory_exits_zero() -> None:
    code, out = _capture(memory_command, [])
    assert code == 0


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A M7 regression)
