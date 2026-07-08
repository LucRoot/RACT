# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ConfigEntry:
    key: str
    value: Any
    description: str = ""


class ConfigLoader:
    """Simple configuration loader for RootACT plans."""

    def __init__(self, root_dir: Optional[str] = None) -> None:
        self.root_dir = root_dir or os.getcwd()
        self._entries: Dict[str, ConfigEntry] = {}

    def load_from_file(self, path: str) -> None:
        """Load configuration from a JSON file."""
        full_path = os.path.abspath(path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Configuration file not found: {full_path}")

        with open(full_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        for item in raw_data:
            entry = ConfigEntry(
                key=item["key"],
                value=item["value"],
                description=item.get("description", ""),
            )
            self._entries[entry.key] = entry

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a configuration value by key."""
        entry = self._entries.get(key)
        if entry is not None:
            return entry.value
        return default

    def all(self) -> Dict[str, Any]:
        """Return all configuration entries."""
        return {key: entry.value for key, entry in self._entries.items()}

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)


# RACT 0.1.0 - Initial Public Release
