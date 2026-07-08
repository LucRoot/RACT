# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RootAct use-case catalog."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "rootact_use_cases.jsonl"


def test_catalog_exists_and_is_valid_jsonl():
    path = _catalog_path()
    assert path.exists(), "rootact_use_cases.jsonl should exist"
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    assert len(entries) >= 20, "catalog should contain at least 20 use cases"


def test_catalog_has_accepted_and_rejected_entries():
    path = _catalog_path()
    statuses = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            statuses.append(entry.get("status"))
            assert "title" in entry
            assert "description" in entry
            assert entry["status"] in ("accepted", "rejected")
    assert "accepted" in statuses


# RACT 0.1.0 - Initial Public Release
