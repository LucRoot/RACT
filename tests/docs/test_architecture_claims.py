"""S-017: docs/ARCHITECTURE.md names only what the code has.

The termination contract must name every ``TerminationCause`` the loop can
return (a new T-cause without a mention drifts the doc into false), and the
event-trace section must name every shipped ``ract trace`` subverb. Both
checks follow the pattern of ``test_v7_03_tables.py``: read the doc, compare
against the code.
"""

from __future__ import annotations

import re
from pathlib import Path

from ract.core.loop import TerminationCause

ROOT = Path(__file__).resolve().parents[2]
ARCH = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
CLI_TRACE = (ROOT / "src" / "ract" / "trace" / "cli_trace.py").read_text(
    encoding="utf-8"
)


def test_termination_contract_names_every_cause():
    """The contract bullet must cover each TerminationCause (ranges expanded)."""
    bullet = ARCH.split("**Termination contract.**", 1)[1].split("\n", 1)[0]
    named: set[str] = set()
    for a, b in re.findall(r"T(\d+)–T(\d+)", bullet):
        named.update(str(n) for n in range(int(a), int(b) + 1))
    named.update(re.findall(r"T(\d+)", bullet))
    assert named == {str(m.value) for m in TerminationCause}, named


def test_every_trace_subverb_is_documented():
    """Each subparser the trace CLI ships must appear in the trace section."""
    shipped = set(re.findall(r'subparsers\.add_parser\(\s*"([\w-]+)"', CLI_TRACE))
    assert shipped, "no trace subverbs found in cli_trace.py"
    section = ARCH.split("## Event trace as the product", 1)[1].split("\n## ", 1)[0]
    undocumented = {v for v in shipped if f"ract trace {v} " not in section}
    assert not undocumented, sorted(undocumented)
