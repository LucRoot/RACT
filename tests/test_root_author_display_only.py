"""Display-marker (module_06 step 6) must live only under display code.

The audit gate is a boolean grep — the marker may appear in
``src/ract/cli.py`` (the ``ract --about`` reader) and
``src/ract/_about.py`` (the marker itself) and **nowhere else** in
``src/`` or ``tests/``. Anywhere else would reintroduce authorship as
an invariant, which SUBSTRATE §7 refuses.

The marker string is constructed at runtime (not written as a literal)
so the file itself is not counted as an occurrence by its own grep.
"""

from __future__ import annotations

import io
import subprocess
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PATH_TAILS = {"cli.py", "_about.py"}

# Constructed at runtime so this test file is not counted as an occurrence
# under its own grep.
_MARKER: str = "__root_" + "author__"


def _scan(root: Path) -> list[Path]:
    """Return every .py file under ``root`` that mentions the marker."""
    hits: list[Path] = []
    for p in root.rglob("*.py"):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if _MARKER in text:
            hits.append(p)
    return hits


def test_root_author_absent_from_invariant_code() -> None:
    """The grep assertion from module_06 step 6."""
    src_hits = _scan(REPO_ROOT / "src")
    tests_hits = _scan(REPO_ROOT / "tests")
    violators = [p for p in src_hits + tests_hits if p.name not in ALLOWED_PATH_TAILS]
    assert not violators, (
        f"{_MARKER} must appear only in cli.py or _about.py; found: "
        + ", ".join(str(p.relative_to(REPO_ROOT)) for p in violators)
    )


def test_ract_about_prints_and_returns_zero() -> None:
    """``ract --about`` prints the byline and exits zero."""
    from ract.cli import main

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--about"])
    output = buf.getvalue()
    assert rc == 0
    assert "Dr. Lucas Root" in output
    assert "RACT" in output


def test_root_author_is_display_only_via_grep() -> None:
    """Belt-and-braces: run git grep for the marker string.

    Uses ``git grep`` when available (respects .gitignore) and skips
    silently if git is not on PATH.
    """
    try:
        proc = subprocess.run(
            [
                "git",
                "grep",
                "-lI",
                _MARKER,
                "--",
                "src/",
                "tests/",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return
    if proc.returncode not in (0, 1):
        return
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    violators = [line for line in lines if Path(line).name not in ALLOWED_PATH_TAILS]
    assert not violators, violators


# RACT 0.4.0
