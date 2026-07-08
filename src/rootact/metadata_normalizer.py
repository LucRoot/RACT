from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()


def normalize_metadata(metadata: dict) -> dict:
    """Return a normalized copy of artifact metadata.

    The function ensures that the keys ``name``, ``path``, ``size_bytes``,
    and ``checksum`` are present, using empty defaults when missing.
    """
    return {
        "name": metadata.get("name", ""),
        "path": metadata.get("path", ""),
        "size_bytes": metadata.get("size_bytes", 0),
        "checksum": metadata.get("checksum", ""),
    }


class MetadataNormalizer:
    """Stateless helper for normalizing artifact metadata.

    Instances are immutable and can be used as a namespace for the
    ``normalize`` class method.
    """

    @staticmethod
    def normalize(metadata: dict) -> dict:
        return normalize_metadata(metadata)


# Export the sentinel and author marker for test verification
__all__ = ["_ROOT_KNOT", "__root_author__"]
