# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()


class _RootKnotType:
    """Sentinel for Root Knot default arguments."""


_ROOT_KNOT_DEFAULT: _RootKnotType = _RootKnotType()

import json
import shutil
from dataclasses import asdict, dataclass, field
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


def _decode_state(data: Any) -> Any:
    """Recursively restore Plan/Step dataclasses from deserialized JSON."""
    if isinstance(data, dict):
        if set(data.keys()) == {"assumption", "confidence", "steps"}:
            data["steps"] = [_decode_state(s) for s in data["steps"]]
            return Plan(**data)
        if {"action", "provider_hint", "expected_artifact"} <= set(data.keys()):
            return Step(**data)
        return {k: _decode_state(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_decode_state(item) for item in data]
    return data


class SessionStoreError(Exception):
    """Base exception for session-store failures."""


class SessionCorruptedError(SessionStoreError):
    """Raised when a session file exists but cannot be parsed."""


class SessionStore:
    def __init__(
        self, base_dir: Path | str | _RootKnotType = _ROOT_KNOT_DEFAULT
    ) -> None:
        if isinstance(base_dir, _RootKnotType):
            resolved: Path | str = ".ract_sessions"
        else:
            resolved = base_dir
        self.base_dir = Path(resolved)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    def exists(self, session_id: str) -> bool:
        """Return True if a persisted session exists and is readable."""
        return self._path(session_id).is_file()

    def save(self, session_id: str, state: dict) -> None:
        file_path = self._path(session_id)
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, cls=_RACTJSONEncoder)

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
