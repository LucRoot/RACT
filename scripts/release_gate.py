#!/usr/bin/env python3
"""Release gate for severity-1 journey defects (B-051).

Reads every ``docs/ux/*/defects.md`` under the root and lists each
severity-1 row that is not closed. It exits 0 only when every S1 row is
``fixed (...)`` or ``accepted (OPERATOR)``, and every table is well formed.
Severity 2 and 3 rows are not counted here.

A defects table is a markdown table whose header has ``Id`` and ``Sev``
cells. Its ``Status`` cell must hold one of these words, exactly:

- ``open``
- ``fixed (<commit subject or card id>)``
- ``blocked (<card id>, gated)``
- ``not testable today (<card id>)``
- ``accepted (OPERATOR)``

The script reads files only. Run it from any directory:

    python scripts/release_gate.py [--root <repository>]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent

_STATUS_RE = re.compile(
    r"^(?:"
    r"open"
    r"|accepted \(OPERATOR\)"
    r"|(?P<kind>fixed|blocked|not testable today) \((?P<detail>[^()]*)\)"
    r")$"
)


@dataclass
class Row:
    """One row of a defects table. ``status`` is None when the row has no Status cell."""

    id: str
    journey: str
    sev: str
    status: str | None
    line: int
    path: Path | None = None


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?", line.strip()))


def parse_defects(text: str) -> list[Row]:
    """Every row of every defects table in *text*, in file order."""
    lines = text.splitlines()
    rows: list[Row] = []
    i = 0
    while i < len(lines):
        header = _cells(lines[i]) if lines[i].lstrip().startswith("|") else []
        if "Id" in header and "Sev" in header and i + 1 < len(lines):
            if _is_separator(lines[i + 1]):
                status_col = header.index("Status") if "Status" in header else None
                j = i + 2
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    cells = _cells(lines[j])
                    status = None
                    if status_col is not None and len(cells) == len(header):
                        status = cells[status_col]
                    rows.append(
                        Row(
                            id=cells[header.index("Id")] if len(cells) > 0 else "?",
                            journey=cells[header.index("Journey")]
                            if "Journey" in header and len(cells) == len(header)
                            else "",
                            sev=cells[header.index("Sev")]
                            if len(cells) == len(header)
                            else "",
                            status=status,
                            line=j + 1,
                        )
                    )
                    j += 1
                i = j
                continue
        i += 1
    return rows


def validate(rows: list[Row]) -> list[str]:
    """Plain errors, each naming the row it is about. Empty when all rows are well formed."""
    errors: list[str] = []
    for row in rows:
        where = f"{row.id} (line {row.line})"
        if row.status is None:
            errors.append(f"{where}: no Status cell; the table needs a Status column")
            continue
        match = _STATUS_RE.match(row.status)
        if match is None:
            errors.append(f"{where}: status {row.status!r} is not an allowed status")
            continue
        if match.group("kind") and not match.group("detail").strip():
            errors.append(
                f"{where}: status {row.status!r} names nothing in the parentheses"
            )
    return errors


def is_closed(status: str | None) -> bool:
    return status is not None and (
        status.startswith("fixed (") or status == "accepted (OPERATOR)"
    )


def gate(root: Path) -> tuple[int, list[str]]:
    """Return the exit code and the lines to print for the tree under *root*."""
    lines: list[str] = []
    errors: list[str] = []
    open_s1: list[Row] = []
    for path in sorted((root / "docs" / "ux").glob("*/defects.md")):
        rows = parse_defects(path.read_text(encoding="utf-8"))
        shown = path.relative_to(root).as_posix()
        for message in validate(rows):
            errors.append(f"ERROR {shown}: {message}")
        for row in rows:
            if row.sev == "S1" and not is_closed(row.status):
                row.path = path
                open_s1.append(row)
                lines.append(
                    f"OPEN S1 {row.id} ({row.journey}) {row.status}  [{shown}]"
                )
    lines = errors + lines
    if errors or open_s1:
        lines.append(
            f"release gate: OPEN ({len(open_s1)} severity-1 row(s) not closed, "
            f"{len(errors)} table error(s))"
        )
        return 1, lines
    lines.append("release gate: clear (no severity-1 row is open or blocked)")
    return 0, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release gate for S1 defects.")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="repository root to read (default: the repository this script is in)",
    )
    args = parser.parse_args(argv)
    code, lines = gate(args.root.resolve())
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
