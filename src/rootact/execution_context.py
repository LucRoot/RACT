from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ExecutionContext:
    """Simple deterministic context for storing temporary data during plan execution."""

    _store: Dict[str, str] = field(default_factory=dict)

    def set(self, key: str, value: str) -> None:
        """Store a string value under the given key."""
        self._store[key] = value

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a stored value; return *default* if the key is missing."""
        return self._store.get(key, default)

    def clear(self) -> None:
        """Reset all stored values."""
        self._store.clear()

    def write_to_file(self, path: str) -> None:
        """Persist the current store as JSON to *path* (creates/overwrites)."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._store, f, indent=2)

    def read_from_file(self, path: str) -> None:
        """Load a JSON store from *path*, replacing the current contents."""
        with open(path, "r", encoding="utf-8") as f:
            self._store = json.load(f)

    def __len__(self) -> int:
        return len(self._store)

    def __bool__(self) -> bool:
        return bool(self._store)
