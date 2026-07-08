# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Dict, IO, List, Optional


@dataclass
class Artifact:
    name: str
    path: str
    size_bytes: int
    checksum: str


@dataclass
class ArtifactStore:
    """Simple in-memory artifact store for RootACT.

    This utility tracks artifacts generated during a session by name and
    provides basic lookup capabilities. It is deliberately lightweight
    and has no external dependencies.
    """

    _artifacts: Dict[str, Artifact] = field(default_factory=dict)

    def add(self, artifact: Artifact) -> None:
        """Register a new artifact."""
        self._artifacts[artifact.name] = artifact

    def get(self, name: str) -> Optional[Artifact]:
        """Retrieve an artifact by name."""
        return self._artifacts.get(name)

    def list_names(self) -> List[str]:
        """Return a list of registered artifact names."""
        return list(self._artifacts.keys())

    def clear(self) -> None:
        """Remove all artifacts."""
        self._artifacts.clear()


# Temporary file handling utilities
class TemporaryFileManager:
    """Context manager for temporary files.

    Provides a simple way to create temporary files that are automatically
    cleaned up when closed. Used internally by RootACT components.
    """

    def __init__(self, suffix: str = "") -> None:
        self.suffix = suffix
        self.tempfile: Optional[IO[str]] = None

    def create(self) -> "TemporaryFileManager":
        """Create and open a temporary file."""
        self.tempfile = tempfile.NamedTemporaryFile(
            suffix=self.suffix, mode="w+", delete=False
        )
        return self

    def __enter__(self) -> "TemporaryFileManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.tempfile:
            self.tempfile.close()
            try:
                os.unlink(self.tempfile.name)
            except OSError:
                pass  # Ignore cleanup errors


# Simple checksum utility
def simple_checksum(data: bytes) -> str:
    """Generate a basic checksum for bytes data.

    This implementation uses a simple sum of byte values modulo a large prime.
    It is not cryptographically secure but sufficient for distinguishing
    different content in a local testing environment.
    """
    if not data:
        return "0" * 8
    return str(sum(data) % 1_000_000_007)


# Artifact serialization
def serialize_artifact(artifact: Artifact) -> str:
    """Serialize an artifact to a JSON string.

    This is used for logging and debugging purposes within RootACT.
    """
    return json.dumps(
        {
            "name": artifact.name,
            "path": artifact.path,
            "size_bytes": artifact.size_bytes,
            "checksum": artifact.checksum,
        }
    )


# Artifact deserialization
def deserialize_artifact(data: str) -> Artifact:
    """Deserialize a JSON string back into an Artifact.

    Used primarily for testing and configuration loading.
    """
    obj = json.loads(data)
    return Artifact(
        name=obj["name"],
        path=obj["path"],
        size_bytes=obj["size_bytes"],
        checksum=obj["checksum"],
    )


# RACT 0.1.0 - Initial Public Release
