# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"


class _RootKnotType:
    """Sentinel for Root Knot default arguments."""


_ROOT_KNOT: _RootKnotType = _RootKnotType()

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from rootact.manager import Plan, Step


@dataclass
class SessionState:
    intent: str
    plan: Plan
    artifacts: Dict[str, Any] = field(default_factory=dict)
    outcomes: List[str] = field(default_factory=list)


class _RootActJSONEncoder(json.JSONEncoder):
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
    def __init__(self, base_dir: Path | str | _RootKnotType = _ROOT_KNOT) -> None:
        if isinstance(base_dir, _RootKnotType):
            resolved: Path | str = ".rootact_sessions"
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
            json.dump(state, f, indent=2, cls=_RootActJSONEncoder)

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


# RACT 0.1.1 - Trust and Tooling
