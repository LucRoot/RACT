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
  ``.rack/`` / ``.ract/``.

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

``.ract_sessions/`` is NOT collapsed into ``.ract/sessions/`` in this
module -- it is a separate audit finding (Lens A N4) and touching it
would break every existing session on disk. Flagged for v0.6.

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

    The shim runs at most one syscall in each non-warning path and
    is safe to invoke on every CLI dispatch.
    """
    root_path = Path(root)
    modern = root_path / WORKSPACE_STATE_DIR_NAME
    legacy = root_path / LEGACY_STATE_DIR_NAME

    modern_exists = modern.exists()
    legacy_exists = legacy.exists()

    if modern_exists and legacy_exists:
        _LOG.warning(
            "workspace state migration: BOTH %s and %s exist at %s; "
            "preferring %s. Move any %s content by hand and delete "
            "the legacy directory to silence this warning.",
            WORKSPACE_STATE_DIR_NAME,
            LEGACY_STATE_DIR_NAME,
            root_path,
            WORKSPACE_STATE_DIR_NAME,
            LEGACY_STATE_DIR_NAME,
        )
        return "warned_both"

    if modern_exists:
        return "noop_already"

    if not legacy_exists:
        return "noop_fresh"

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


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A C2)
