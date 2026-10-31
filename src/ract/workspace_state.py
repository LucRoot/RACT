"""Canonical workspace-state directory + `.rack` -> `.ract` migration shim.

v0.5.1 wiring module_10 (Lens A C2 CRITICAL closure).

Prior state (audited): workspace state fragmented across three roots:

- ``.ract/`` -- memory init (``cli_memory.py``), intent recompile
  (``core/intent_recompile.py:227-234``).
- ``.rack/`` -- rootknot SQLite (``core/provenance.py``), sandbox +
  ALM keys (``security/keys.py``, ``security/alm_verifier_key.py``),
  failure records (``memory/failure_records.py``), probe scheduler
  record (``memory/probes/scheduler.py``), repo fingerprint
  (``memory/repo_fingerprint.py``), historical docstrings.
- ``.ract_sessions/`` -- session store (``cli.py``); already outside
  ``.rack/`` / ``.ract/``. Moved to ``.ract/sessions/`` by B-079 (see below).

Module_10 unifies on ``.ract/`` (matches the package name, the CLI
entry point, and the docs the operator reads first). The three
non-``.ract/`` state hierarchies migrate to:

- ``.ract/rootknots.db`` (was ``.rack/rootknots.db``)
- ``.ract/sandbox/`` (was ``.rack/sandbox/``)
- ``.ract/alm/`` (was ``.rack/alm/``)
- ``.ract/failures/`` (was ``.rack/failures/``)
- ``.ract/probes/`` (was ``.rack/probes/``)
- ``.ract/fingerprint/`` (was ``.rack/fingerprint/``)
- ``.ract/index/`` (implicit; ``.rack/index/`` never actually existed
  because ``cli_memory.py`` was already writing to ``.ract/memory/``).

``.ract_sessions/`` was left out of this module (Lens A N4). B-079 moved
the ``ract session ...`` default to ``.ract/sessions/``; sessions found in
``.ract_sessions/`` are copied there once (``session_store.copy_old_sessions``)
and the old folder is left as it was.

Migration shim (``migrate_rack_to_ract``):

- If ``.ract/`` already exists, no-op (the operator has already
  migrated OR is on a fresh ``.ract/``-only install).
- If ``.rack/`` exists and ``.ract/`` does not, rename in place
  (``os.rename`` is atomic on Windows + POSIX for same-filesystem
  moves; ``.rack/`` and ``.ract/`` are always siblings under the
  workspace root).
- If BOTH exist, WARN + prefer ``.ract/`` (never merge blindly --
  the operator must resolve).
- If neither exists, no-op (fresh workspace; the caller will
  create ``.ract/`` on first write).

The shim is idempotent and safe to call on every CLI entry.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

_LOG = logging.getLogger(__name__)

# Canonical name of the workspace-state directory. Kept as a module
# constant so callers can reference it without hardcoding the string
# literal (which would trip the module_10 architecture grep-gate).
WORKSPACE_STATE_DIR_NAME: str = ".ract"

# Legacy name; retained so the migration shim and one-shot cleanup
# jobs have a symbol to reference. New code MUST NOT write to this
# location.
LEGACY_STATE_DIR_NAME: str = ".rack"


def workspace_state_dir(root: Path | str) -> Path:
    """Return the canonical workspace-state directory under ``root``.

    Always ``<root>/.ract/``. The path may or may not exist yet;
    callers that write MUST call ``mkdir(parents=True, exist_ok=True)``
    on the returned path (or the specific subdirectory they need).
    """
    return Path(root) / WORKSPACE_STATE_DIR_NAME


class StateDirRefused(OSError):
    """A folder of RACT's state, or the file written there, is a link (B-213)."""


def check_state_path(path: Path | str) -> None:
    """Refuse a write at *path* when ``.ract`` or a folder under it is a link.

    LR:: ``.ract`` is in the workspace, so a cloned repository can ship it,
    or a folder in it, as a link or a junction (B-213). The memory arena
    refused such a file on load and wrote through it on save, so the write
    landed outside the project. Every writer of RACT's state calls this with
    the file it is about to write: ``.ract`` itself, each folder below it on
    the way, and the file must each be no link, junction or other reparse
    point. A path with no ``.ract`` part is not RACT's state and is left as
    it is. Raises ``StateDirRefused`` with a plain sentence.
    """
    from ract.workspace_path import _is_link_or_junction

    parts = Path(path).parts
    folded = [part.casefold() for part in parts]
    if WORKSPACE_STATE_DIR_NAME not in folded:
        return
    start = folded.index(WORKSPACE_STATE_DIR_NAME)
    for end in range(start + 1, len(parts) + 1):
        current = Path(*parts[:end])
        if _is_link_or_junction(current):
            raise StateDirRefused(
                f"{current} is a link or a junction, and RACT does not write its "
                "state through one; remove it and RACT makes a plain folder"
            )


def legacy_state_dir(root: Path | str) -> Path:
    """Return the legacy (pre-module_10) workspace-state directory.

    Exists only for the migration shim + tests that assert the
    pre-migration surface no longer receives writes.
    """
    return Path(root) / LEGACY_STATE_DIR_NAME


def migrate_rack_to_ract(root: Path | str) -> str:
    """Migrate ``<root>/.rack/`` -> ``<root>/.ract/`` in place.

    Returns one of ``"migrated"``, ``"noop_fresh"``, ``"noop_already"``,
    or ``"warned_both"``. The return value lets the CLI print a
    one-line diagnostic on the migration path and stay silent on the
    no-op paths.

    - ``"migrated"``: ``.rack/`` was renamed to ``.ract/``.
    - ``"noop_fresh"``: neither directory existed. First-run.
    - ``"noop_already"``: only ``.ract/`` existed. Already migrated.
    - ``"warned_both"``: both existed. ``.ract/`` is preferred; the
      caller must resolve ``.rack/`` manually. WARN emitted.
    - ``"skipped_not_a_folder"``: ``.rack`` is a file, a link or a
      junction. It is left as it is and a WARN says so (B-075b): a
      repository can ship it, and renaming it would make a file or a
      link to somewhere else the state folder.

    The shim runs at most one syscall in each non-warning path and
    is safe to invoke on every CLI dispatch.
    """
    root_path = Path(root)
    modern = root_path / WORKSPACE_STATE_DIR_NAME
    legacy = root_path / LEGACY_STATE_DIR_NAME

    modern_exists = modern.exists()
    legacy_exists = legacy.exists()

    if modern_exists and legacy_exists:
        # SP Q2 [PARTIAL] amendment: the WARN alone is easy to miss
        # in noisy CI logs, and silent divergence is the exact
        # failure mode Lens A C2 flagged. Emit an ALLCAPS stderr
        # one-liner in addition to the logger so any operator eye
        # on the shell notices immediately. The migration still
        # refuses to touch either directory automatically -- merging
        # blindly could delete real state.
        msg = (
            f"workspace state migration: BOTH {WORKSPACE_STATE_DIR_NAME} "
            f"and {LEGACY_STATE_DIR_NAME} exist at {root_path}; "
            f"preferring {WORKSPACE_STATE_DIR_NAME}. Move any "
            f"{LEGACY_STATE_DIR_NAME} content by hand and delete the "
            "legacy directory to silence this warning."
        )
        _LOG.warning(msg)
        import sys as _sys

        print(
            f"[ract] WARN: {msg}",
            file=_sys.stderr,
        )
        return "warned_both"

    if modern_exists:
        return "noop_already"

    if not legacy_exists:
        return "noop_fresh"

    if not _is_plain_folder(legacy):
        msg = (
            f"workspace state migration: {LEGACY_STATE_DIR_NAME} at {root_path} "
            "is not a folder (a file or a link); it was left as it is and "
            f"nothing was moved to {WORKSPACE_STATE_DIR_NAME}."
        )
        _LOG.warning(msg)
        import sys as _sys

        print(f"[ract] WARN: {msg}", file=_sys.stderr)
        return "skipped_not_a_folder"

    # Only legacy exists -- rename in place.
    try:
        os.rename(legacy, modern)
    except OSError as exc:  # pragma: no cover - rare cross-fs corner
        _LOG.warning(
            "workspace state migration: failed to rename %s -> %s: %s",
            legacy,
            modern,
            exc,
        )
        return "warned_both"
    _LOG.info(
        "workspace state migrated: %s -> %s",
        legacy,
        modern,
    )
    return "migrated"


def _is_plain_folder(path: Path) -> bool:
    """True when *path* is a directory itself: no file, no symlink, no junction.

    A junction is not a symlink to ``is_symlink`` on Python 3.11, so the
    resolved path must also be the path itself.
    """
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        return path.resolve() == path.absolute().resolve().parent / path.name
    except OSError as exc:
        _LOG.warning("workspace state migration: cannot resolve %s: %s", path, exc)
        return False


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A C2)
