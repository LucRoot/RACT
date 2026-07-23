# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the operator handshake registry."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

import pytest

from ract.handshake_registry import HandshakeItem, HandshakeRegistry


def test_add_stores_metadata(tmp_path):
    registry = HandshakeRegistry(tmp_path)
    metadata = {"target": "a.py", "sources": ["b.py"], "safe": True}
    item = registry.add("merge-0001", "desc", "accept", metadata=metadata)
    assert item.metadata == metadata
    loaded = registry.entries()[-1]
    assert loaded.metadata == metadata


def test_update_status_preserves_metadata(tmp_path):
    registry = HandshakeRegistry(tmp_path)
    metadata = {"target": "a.py", "sources": ["b.py"]}
    registry.add("merge-0001", "desc", "accept", metadata=metadata)
    updated = registry.update_status("merge-0001", "approved")
    assert updated.metadata == metadata
    assert updated.status == "approved"


def test_none_metadata_not_serialized(tmp_path):
    registry = HandshakeRegistry(tmp_path)
    registry.add("plain-0001", "desc", "accept")
    raw = json.loads(
        (tmp_path / ".ract" / "handshakes.json").read_text(encoding="utf-8")
    )
    assert "metadata" not in raw[0]


def test_add_rejects_invalid_status(tmp_path):
    _ = tmp_path
    with pytest.raises(ValueError):
        HandshakeItem(
            id="x",
            description="d",
            acceptance="a",
            timestamp="2026-07-16T00:00:00",
            status="invalid",
        )


# RACT 0.1.1 - Trust and tooling
