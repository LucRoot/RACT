"""Build docs/SESSION_GUIDE.md from its template, the captures and the known-issues list (B-089).

Inputs, all in the repository:

- ``docs/ux/guide/SESSION_GUIDE.template.md``: the guide's prose, with one
  ``{{sample <capture> <first> <last>}}`` per sample block and ``{{known_issues}}``.
- ``docs/ux/guide/<capture>``: the captures. A sample is the capture's lines
  ``first`` to ``last`` (1-based, inclusive), copied as they are.
- ``docs/ux/guide/known_issues.md``: the known-issues bullets.

Output: ``docs/SESSION_GUIDE.md``. The generator reads only these files; it runs no
ract command, opens no socket and calls no model, so a reader can rebuild the guide
offline. Run ``python tools/build_session_guide.py`` from the repository root after
editing a capture, the template or the known issues.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE_DIR = ROOT / "docs" / "ux" / "guide"
TEMPLATE = GUIDE_DIR / "SESSION_GUIDE.template.md"
KNOWN_ISSUES = GUIDE_DIR / "known_issues.md"
OUTPUT = ROOT / "docs" / "SESSION_GUIDE.md"

SAMPLE = re.compile(r"\{\{sample (\S+) (\d+) (\d+)\}\}")


def _sample(name: str, first: int, last: int) -> str:
    lines = (GUIDE_DIR / name).read_text(encoding="utf-8").split("\n")
    if not 1 <= first <= last <= len(lines):
        raise ValueError(f"{name}: lines {first} to {last} are outside the capture")
    return "```text\n" + "\n".join(lines[first - 1 : last]) + "\n```"


def build() -> str:
    """The guide as text, with a trailing newline."""
    text = TEMPLATE.read_text(encoding="utf-8")
    text = SAMPLE.sub(
        lambda m: _sample(m.group(1), int(m.group(2)), int(m.group(3))), text
    )
    issues = KNOWN_ISSUES.read_text(encoding="utf-8").rstrip("\n")
    text = text.replace("{{known_issues}}", issues)
    if "{{" in text:
        raise ValueError("the template has a placeholder the generator does not know")
    return text if text.endswith("\n") else text + "\n"


def main() -> int:
    OUTPUT.write_text(build(), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
