from __future__ import annotations

_SENTINEL = object()


class _SentinelType:
    """Sentinel for default arguments."""


_SENTINEL_DEFAULT: _SentinelType = _SentinelType()

import json
import shutil
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ract.manager import Plan, Step


@dataclass
class SessionState:
    intent: str
    plan: Plan
    artifacts: Dict[str, Any] = field(default_factory=dict)
    outcomes: List[str] = field(default_factory=list)


class _RACTJSONEncoder(json.JSONEncoder):
    """Serialize Plan and Step dataclasses transparently."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (Plan, Step)):
            return asdict(obj)
        return super().default(obj)


_PLAN_FIELDS = frozenset(f.name for f in fields(Plan))


def _decode_state(data: Any) -> Any:
    """Recursively restore Plan/Step dataclasses from deserialized JSON."""
    if isinstance(data, dict):
        # B-137 added Plan.planned: a plan is its required keys plus only
        # fields Plan has (an exact key set read a new plan back as a dict).
        keys = set(data.keys())
        if {"assumption", "confidence", "steps"} <= keys <= _PLAN_FIELDS:
            data["steps"] = [_decode_state(s) for s in data["steps"]]
            return Plan(**data)
        if {"action", "provider_hint", "expected_artifact"} <= set(data.keys()):
            return Step(**data)
        return {k: _decode_state(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_decode_state(item) for item in data]
    return data


# B-079 (decision X, D-059): the store lives under .ract/ with the rest of the
# workspace state. Releases before it kept sessions in .ract_sessions/.
DEFAULT_DIR = Path(".ract") / "sessions"
OLD_DEFAULT_DIR = Path(".ract_sessions")
_COPIED_MARK = ".moved-from-ract_sessions"


def copy_old_sessions(
    new_dir: Path = DEFAULT_DIR, old_dir: Path = OLD_DEFAULT_DIR
) -> list[str] | None:
    """Copy sessions from the old store into the new one, once (B-079).

    LR:: Returns None when there was nothing to do (no old folder, or the copy
    already ran), else the ids copied. A session already in the new store is
    kept. Only regular ``<id>.json`` files directly in the old folder, with a
    valid session id, are copied; links and a linked old folder are skipped.
    The old folder is left as it was. A mark in the new store makes it once.
    """
    from ract.undo_backup import require_name

    mark = new_dir / _COPIED_MARK
    if mark.exists() or not old_dir.is_dir() or old_dir.is_symlink():
        return None
    real_old = old_dir.resolve()
    if real_old.parent != old_dir.absolute().parent:
        return None
    new_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for path in sorted(old_dir.glob("*.json")):
        if path.is_symlink() or not path.is_file() or path.resolve().parent != real_old:
            continue
        try:
            require_name(path.stem, "session id")
        except ValueError:
            continue
        target = new_dir / path.name
        if target.exists():
            continue
        shutil.copy2(path, target)
        copied.append(path.stem)
    mark.write_text(
        f"Sessions were copied here from {old_dir} once; that folder was left as it was.\n",
        encoding="utf-8",
    )
    return copied


class SessionStoreError(Exception):
    """Base exception for session-store failures."""


class SessionCorruptedError(SessionStoreError):
    """Raised when a session file exists but cannot be parsed."""


class SessionStore:
    def __init__(
        self, base_dir: Path | str | _SentinelType = _SENTINEL_DEFAULT
    ) -> None:
        if isinstance(base_dir, _SentinelType):
            resolved: Path | str = DEFAULT_DIR
        else:
            resolved = base_dir
        self.base_dir = Path(resolved)
        from ract.workspace_state import check_state_path

        check_state_path(self.base_dir)  # B-213: never through a link
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        from ract.undo_backup import require_name

        return self.base_dir / f"{require_name(session_id, 'session id')}.json"

    def exists(self, session_id: str) -> bool:
        """Return True if a persisted session exists and is readable."""
        return self._path(session_id).is_file()

    def save(self, session_id: str, state: dict) -> None:
        from ract.redaction import redact_values
        from ract.workspace_state import check_state_path

        file_path = self._path(session_id)
        check_state_path(file_path)  # B-213: never through a link
        # B-201: the intent, the plan and the artifacts are model and user
        # text; a key in them is not written to the session file.
        encoded = json.loads(json.dumps(state, cls=_RACTJSONEncoder))
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(redact_values(encoded), f, indent=2)

    def load(self, session_id: str) -> dict:
        file_path = self._path(session_id)
        try:
            with file_path.open("r", encoding="utf-8") as f:
                return _decode_state(json.load(f))
        except FileNotFoundError as exc:
            raise KeyError(session_id) from exc
        except json.JSONDecodeError as exc:
            raise SessionCorruptedError(
                f"Session '{session_id}' is corrupted: {exc}"
            ) from exc

    def list_sessions(self) -> List[str]:
        return [p.stem for p in self.base_dir.glob("*.json") if p.is_file()]

    def backup(self, session_id: str, backup_dir: Path | str) -> dict[str, Any]:
        """Copy a session file into a timestamped backup subdirectory.

        Returns a dict with ``copied`` and ``missing`` filename lists.
        """
        source = self._path(session_id)
        target_dir = Path(backup_dir) / datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        missing: list[str] = []
        if source.is_file():
            shutil.copy2(source, target_dir / source.name)
            copied.append(source.name)
        else:
            missing.append(source.name)
        return {"copied": copied, "missing": missing, "backup_dir": str(target_dir)}

    def restore(self, session_id: str, backup_dir: Path | str) -> dict[str, Any]:
        """Copy a session file from a backup directory back to the store.

        Returns a dict with ``copied`` and ``missing`` filename lists.
        """
        source_dir = Path(backup_dir)
        source = source_dir / f"{session_id}.json"
        target = self._path(session_id)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        missing: list[str] = []
        if source.is_file():
            shutil.copy2(source, target)
            copied.append(source.name)
        else:
            missing.append(source.name)
        return {"copied": copied, "missing": missing}


# RACT 0.1.2 - Trust and tooling
