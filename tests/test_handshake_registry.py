# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the HandshakeRegistry."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.handshake_registry import HandshakeRegistry


def test_add_and_list(tmp_path):
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "deploy", "push to prod")
    items = registry.entries()
    assert len(items) == 1
    assert items[0].id == "m1"
    assert items[0].status == "pending"


def test_pending_filters_status(tmp_path):
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "deploy", "push")
    registry.update_status("m1", "approved")
    registry.add("m2", "delete", "drop table")
    assert len(registry.pending()) == 1
    assert registry.pending()[0].id == "m2"


def test_update_status_unknown_raises(tmp_path):
    registry = HandshakeRegistry(tmp_path)
    with __import__("pytest").raises(KeyError):
        registry.update_status("missing", "approved")


# RACT 0.1.1 - Trust and Tooling
