# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for SessionConfig persistence."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.session_config import SessionConfig


def test_session_config_defaults():
    cfg = SessionConfig()
    assert cfg.yolo is False
    assert cfg.auto is False
    assert cfg.reload is False
    assert cfg.session_id is None
    assert cfg.resume is False


def test_session_config_round_trip(tmp_path):
    original = SessionConfig(yolo=True, session_id="abc", resume=True)
    path = tmp_path / "session.json"
    original.save(path)
    loaded = SessionConfig.from_file(path)
    assert loaded == original


def test_session_config_from_dict():
    data = {
        "yolo": True,
        "auto": False,
        "reload": True,
        "session_id": "x",
        "resume": False,
    }
    cfg = SessionConfig.from_dict(data)
    assert cfg.yolo is True
    assert cfg.reload is True
    assert cfg.session_id == "x"


def test_session_config_to_dict():
    cfg = SessionConfig(session_id="s1")
    assert cfg.to_dict() == {
        "yolo": False,
        "auto": False,
        "reload": False,
        "session_id": "s1",
        "resume": False,
    }


# RACT 0.1.1 - Trust and Tooling
