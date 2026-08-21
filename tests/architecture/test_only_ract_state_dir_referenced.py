"""Architecture gate: no ``.rack/`` string literals outside the migration shim.

v0.5.1 wiring module_10 (Lens A C2) unified workspace state on ``.ract/``.
Every code path that reads / writes workspace state must use the canonical
directory. Legitimate references to ``.rack/`` are limited to:

- :mod:`ract.workspace_state` -- the migration shim itself owns the
  legacy directory name as a string constant.
- ``src/ract/core/intent_recompile.py`` -- the ``skip_dirs`` set that
  filters both ``.rack`` (legacy) and ``.ract`` (canonical) from the
  workspace snapshot walker. Keeping the legacy entry keeps pre-
  migration workspaces from tripping the snapshot on stale state.
- Docstrings / comments that document the migration or historical
  behavior (words like ``pre-module_10``, ``legacy``, ``migration``,
  ``was``, ``prior state``).

Any other occurrence is a wiring gap that would silently split the
workspace state again.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "ract"

# Files that legitimately mention ``.rack`` (see module docstring above).
ALLOWED_FILES = {
    SRC_ROOT / "workspace_state.py",
    SRC_ROOT / "core" / "intent_recompile.py",
}

# Substrings on a line that mark the reference as documentation or
# migration context (comment / docstring). If the line matches, the
# `.rack` occurrence is tolerated.
CONTEXT_MARKERS = (
    "module_10",
    "migration",
    "migrate",
    "legacy",
    "pre-module",
    "was ",
    "prior state",
    "backward",
    "back-compat",
    "backward-compat",
    "backward compat",
    "old ",
    ".rack/`` (v",  # historical docstring narrating the migration
    "LEGACY_STATE_DIR",
    "WORKSPACE_STATE_DIR",
)


def _line_is_documentation_context(line: str) -> bool:
    lower = line.lower()
    return any(marker.lower() in lower for marker in CONTEXT_MARKERS)


def test_no_rack_literal_outside_migration_shim() -> None:
    """Every ``.rack`` string literal lives in an allowed file or is a docstring."""
    violations: list[str] = []
    pattern = re.compile(r"\.rack\b")
    for py_file in SRC_ROOT.rglob("*.py"):
        if py_file in ALLOWED_FILES:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if not pattern.search(line):
                continue
            if _line_is_documentation_context(line):
                continue
            violations.append(f"{py_file.relative_to(SRC_ROOT.parent.parent)}:{i}: {line.strip()}")
    assert not violations, (
        "unmigrated `.rack` references in src/ract/ (v0.5.1 module_10 Lens A C2 gate):\n"
        + "\n".join(violations)
    )


def test_workspace_state_dir_constant_is_ract() -> None:
    """The canonical directory constant is ``.ract`` -- guards against typo drift."""
    from ract.workspace_state import LEGACY_STATE_DIR_NAME, WORKSPACE_STATE_DIR_NAME

    assert WORKSPACE_STATE_DIR_NAME == ".ract"
    assert LEGACY_STATE_DIR_NAME == ".rack"


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A C2 regression)
