"""B-133: no long dash in the tracked README and the top-level docs.

The wording rule: no em-dash (U+2014) in user-facing text. This test reads README.md and the
top-level docs/*.md. The decision log, the ADRs and the CHANGELOG history are not read here.
The planted case proves the check itself finds a dash (red first, then green on the real files).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH = "—"


def long_dashes(paths: list[Path]) -> list[str]:
    """``file:line`` for every line of *paths* that carries a long dash."""
    return [
        f"{path.name}:{number}"
        for path in paths
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if DASH in line
    ]


def tracked_docs() -> list[Path]:
    return [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def test_no_long_dash_in_the_readme_or_the_docs() -> None:
    found = long_dashes(tracked_docs())
    assert not found, f"long dashes in user-facing docs: {found[:10]}"


def test_the_check_finds_a_planted_dash(tmp_path: Path) -> None:
    planted = tmp_path / "README.md"
    planted.write_text(
        f"A sentence {DASH} with a dash.\nA clean line.\n", encoding="utf-8"
    )
    assert long_dashes([planted]) == ["README.md:1"]
