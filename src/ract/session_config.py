from __future__ import annotations


import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class SessionConfigUnreadable(Exception):
    """``session.json`` is not a session config; the message says why."""


_MAX_BYTES = 64 * 1024
_BOOLS = ("yolo", "auto", "reload", "resume")


@dataclass
class SessionConfig:
    yolo: bool = False
    auto: bool = False
    reload: bool = False
    session_id: str | None = None
    resume: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SessionConfig":
        return SessionConfig(**data)

    def save(self, path: Path | str | None = None) -> None:
        target = Path(path) if path is not None else self._default_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def from_file(path: Path | str) -> "SessionConfig":
        """The config in *path*; SessionConfigUnreadable when it is not one.

        LR:: A file that was not JSON, or was a list or a number, raised
        JSONDecodeError or TypeError out of the reader (B-075, S-035). The
        shape is closed: an object with only the known keys, booleans for
        the switches and text or null for the session id. A missing file
        or a directory still raises OSError.
        """
        target = Path(path)
        with target.open("rb") as f:
            raw = f.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise SessionConfigUnreadable(f"{target} is larger than {_MAX_BYTES} bytes")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise SessionConfigUnreadable(f"{target} is not JSON") from None
        if not isinstance(data, dict):
            raise SessionConfigUnreadable(f"{target} is not a JSON object")
        unknown = sorted(set(data) - {*_BOOLS, "session_id"})
        if unknown:
            raise SessionConfigUnreadable(f"{target} has unknown keys {unknown}")
        if any(not isinstance(data[k], bool) for k in _BOOLS if k in data):
            raise SessionConfigUnreadable(
                f"{target} has a switch that is not true or false"
            )
        session_id = data.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise SessionConfigUnreadable(f"{target} has a session id that is not text")
        return SessionConfig.from_dict(data)

    @staticmethod
    def _default_path() -> Path:
        return Path("~/.ract/session.json").expanduser()


# RACT v0.6.0 - Interactive Session
