# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass
from typing import Dict, Set


@dataclass
class TrackedArtifact:
    """Immutable representation of an artifact stored in the tracker."""

    identifier: str
    checksum: str
    path: str


class ArtifactTracker:
    """Simple in-memory registry for artifact checksums and paths.

    This utility allows RootACT to record newly generated artifacts and later
    verify their presence or absence without persisting to disk.
    """

    def __init__(self) -> None:
        self._registry: Dict[str, TrackedArtifact] = {}

    def register(self, artifact: TrackedArtifact) -> None:
        """Register a new artifact; overwrites if identifier already exists."""
        self._registry[artifact.identifier] = artifact

    def get(self, identifier: str) -> TrackedArtifact | None:
        """Retrieve an artifact by its identifier, or ``None`` if absent."""
        return self._registry.get(identifier)

    def contains(self, identifier: str) -> bool:
        """Return ``True`` if the identifier has been registered."""
        return identifier in self._registry

    def list_identifiers(self) -> Set[str]:
        """Return a set of all registered artifact identifiers."""
        return set(self._registry.keys())
