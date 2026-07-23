# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for SessionConfig persistence."""

from __future__ import annotations

from pathlib import Path

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from ract.session_config import SessionConfig


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


def test_session_config_serialization(tmp_path: Path) -> None:
    cfg = SessionConfig(yolo=True, session_id="test123")
    file_path = tmp_path / "session_test123.json"
    cfg.save(file_path)
    loaded = SessionConfig.from_file(file_path)
    assert loaded.yolo is True
    assert loaded.session_id == "test123"


def test_resume_loads_existing_session(tmp_path: Path) -> None:
    existing = SessionConfig(session_id="resume_test", resume=True)
    file_path = tmp_path / "session_resume_test.json"
    existing.save(file_path)
    restored = SessionConfig.from_file(file_path)
    assert restored.session_id == "resume_test"
    assert restored.resume is True


def test_defaults_are_sensible() -> None:
    default = SessionConfig()
    assert default.yolo is False
    assert default.auto is False
    assert default.reload is False
    assert default.session_id is None
    assert default.resume is False


def test_author_marker_present() -> None:
    import ract.session_config as mod

    assert hasattr(mod, "__root_author__")

    assert mod.__root_author__ == "Dr. Lucas Root, Ph.D."


def test_default_path_expands_user() -> None:
    path = SessionConfig._default_path()
    assert isinstance(path, Path)
    assert not str(path).startswith("~")
    assert path.name == "session.json"
    assert path.parent.name == ".ract"


# RACT 0.1.1 - Trust and tooling
