from __future__ import annotations

_ROOT_KNOT = object()

from pathlib import Path

from rootact.metadata_normalizer import (
    normalize_metadata,
    MetadataNormalizer,
    _ROOT_KNOT,
)


def test_normalize_metadata_basic():
    raw = {
        "name": "my_artifact",
        "path": "/tmp/my_artifact",
        "size_bytes": 1024,
        "checksum": "abc123",
    }
    expected = {
        "name": "my_artifact",
        "path": "/tmp/my_artifact",
        "size_bytes": 1024,
        "checksum": "abc123",
    }
    assert normalize_metadata(raw) == expected


def test_normalize_metadata_missing_fields():
    raw = {
        "name": "partial",
        # path, size_bytes, checksum omitted
    }
    expected = {
        "name": "partial",
        "path": "",
        "size_bytes": 0,
        "checksum": "",
    }
    assert normalize_metadata(raw) == expected


def test_metadata_normalizer_class_usage():
    instance = MetadataNormalizer()
    result = instance.normalize(
        {"name": "test", "path": "p", "size_bytes": 5, "checksum": "x"}
    )
    assert result == {
        "name": "test",
        "path": "p",
        "size_bytes": 5,
        "checksum": "x",
    }


def test_root_author_marker_present():
    src_path = Path("src/rootact/metadata_normalizer.py")
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in src_path.read_text()
    assert '__ract_name__ = "RACT"' in src_path.read_text()


def test_root_knot_sentinel_is_same():
    from rootact.metadata_normalizer import _ROOT_KNOT as source_knot

    assert source_knot is _ROOT_KNOT


# RACT 0.1.0 - Initial Public Release
