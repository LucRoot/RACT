# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


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
        target = Path(path)
        with target.open("r", encoding="utf-8") as f:
            return SessionConfig.from_dict(json.load(f))

    @staticmethod
    def _default_path() -> Path:
        return Path("~/.rootact/session.json").expanduser()


# RACT 0.1.0 - Initial Public Release
