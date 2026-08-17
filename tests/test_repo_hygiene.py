"""Repo hygiene lint (v0.3 Module 6).

Asserts the hygiene invariants the v0.3 spec requires:
  - no tracked JSON/JSONL fixtures at the repo root,
  - ``tests/fixtures/`` exists as the fixture convention,
  - runtime state dirs (``.ract/``, ``.rack/``, ``_BUILD/``) are gitignored.

These are cheap, fast gates that prevent the repo from regressing into the
"builder's dump" shape the v0.2.0 rebuild cleaned up.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Runtime state directories that must never be committed. Mirrors .gitignore.
RUNTIME_DIRS = (".ract", ".ract_sessions", ".rack", "_BUILD", ".venv")


def test_no_tracked_json_fixtures_at_repo_root() -> None:
    """No *.json or *.jsonl file may be tracked at the repo root.

    Project meta (pyproject.toml, ract.yaml) is allowed; tracked JSON at root
    is the hygiene tell this gate exists to prevent. Uses ``git ls-files`` so
    only tracked files are considered (untracked scratch is already ignored).
    """
    result = subprocess.run(
        ["git", "ls-files", "--", "*.json", "*.jsonl"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    root_level = [f for f in result.stdout.splitlines() if "/" not in f and f]
    assert not root_level, (
        "Tracked JSON/JSONL files at repo root violate the fixtures convention "
        f"(move to tests/fixtures/ or gitignore): {root_level}"
    )


def test_fixtures_directory_exists() -> None:
    """tests/fixtures/ is the canonical fixture location."""
    fixtures = REPO_ROOT / "tests" / "fixtures"
    assert fixtures.is_dir(), f"tests/fixtures/ must exist; got {fixtures}"
    # A .gitkeep so the convention directory is tracked even when empty.
    assert (fixtures / ".gitkeep").is_file(), (
        "tests/fixtures/.gitkeep must exist so the directory is tracked"
    )


def test_runtime_dirs_are_gitignored() -> None:
    """Runtime state directories must be gitignored."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for d in RUNTIME_DIRS:
        needle = f"{d}/"
        assert needle in gitignore, (
            f".gitignore must ignore runtime dir '{needle}' "
            "(runtime state never lives in the committed tree)"
        )


# RACT 0.3.0
