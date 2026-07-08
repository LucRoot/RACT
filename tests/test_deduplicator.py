from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path

from rootact.deduplicator import deduplicate_strings, DeduplicationResult


def test_deduplicate_empty_list():
    result = deduplicate_strings([])
    expected = DeduplicationResult(
        unique_items=[], original_count=0, deduplicated_count=0
    )
    assert result == expected


def test_deduplicate_with_duplicates():
    items = ["alpha", "beta", "alpha", "gamma", "beta"]
    result = deduplicate_strings(items)
    expected = DeduplicationResult(
        unique_items=["alpha", "beta", "gamma"], original_count=5, deduplicated_count=3
    )
    assert result == expected


def test_deduplication_result_json_roundtrip(tmp_path: Path):
    result = DeduplicationResult(
        unique_items=["x", "y"], original_count=2, deduplicated_count=2
    )
    json_path = tmp_path / "result.json"
    json_path.write_text(json.dumps(result.__dict__))
    loaded = json.loads(json_path.read_text())
    reloaded = DeduplicationResult(**loaded)
    assert reloaded == result


# RACT 0.1.0 - Initial Public Release
