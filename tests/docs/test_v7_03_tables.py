"""V7-03: the stage map and the halt-cause table name only what the code has.

Reads the two tables from docs/EVENTS.md and checks each kind against the session
kinds (src/ract/session_events.py) and the trace kinds (the #### headings of
docs/EVENTS.md). Each halt-cause row that names an exit code must name a code the
turn path returns, and each T-cause must be a member of TerminationCause.
"""

from __future__ import annotations

import re
from pathlib import Path

from ract.core.loop import TerminationCause
from ract.session_events import KINDS, RESERVED_KINDS

ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "docs" / "EVENTS.md"
TRACE_HEADING = re.compile(r"^#### `([a-z_.]+)`", re.M)
TICK = re.compile(r"`([a-z_.]+)`")


def _section(title: str) -> str:
    text = EVENTS.read_text(encoding="utf-8")
    return text.split(f"## {title}", 1)[1].split("\n## ", 1)[0]


def _stage_map_kinds() -> set[str]:
    kinds: set[str] = set()
    for line in _section("Stage to event kind").splitlines():
        if (
            line.startswith("|")
            and not line.startswith("| Stage")
            and "---" not in line
        ):
            kinds.update(TICK.findall(line.split("|")[2] + line.split("|")[3]))
    return kinds


def test_every_kind_in_the_stage_map_is_registered():
    trace = set(TRACE_HEADING.findall(EVENTS.read_text(encoding="utf-8")))
    known = set(KINDS) | trace
    named = {k for k in _stage_map_kinds() if "." in k}
    assert named, "the stage map names no kinds"
    # Reserved names may appear in the map as "not emitted"; every other name must exist.
    assert (named - RESERVED_KINDS) <= known, sorted((named - RESERVED_KINDS) - known)


def test_every_t_cause_in_the_halt_table_exists():
    table = _section("Halt causes and exit codes")
    named = set(re.findall(r"Loop termination (T\d)", table))
    # TerminationCause values 1 to 8 are T1 to T8; the table must name each one.
    assert named == {f"T{m.value}" for m in TerminationCause if m.value <= 8}, named


def test_every_exit_code_in_the_halt_table_is_one_the_turn_path_returns():
    table = _section("Halt causes and exit codes")
    codes = {int(c) for c in re.findall(r"\| (\d) \|", table)}
    assert codes <= {0, 1, 2, 3, 4, 5, 6}, codes
