from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

import pytest

from rootact.cli_toggles import parse_cli_args
from rootact.session_config import SessionConfig


def test_cli_flags_map_to_config() -> None:
    args = parse_cli_args(
        ["--yolo", "--auto", "--reload", "--session", "abc", "--resume"]
    )
    cfg = SessionConfig(
        yolo=args.yolo,
        auto=args.auto,
        reload=args.reload,
        session_id=args.session_id,
        resume=args.resume,
    )
    assert cfg.yolo is True
    assert cfg.auto is True
    assert cfg.reload is True
    assert cfg.session_id == "abc"
    assert cfg.resume is True


def test_unknown_flags_raise_system_exit() -> None:
    with pytest.raises(SystemExit):
        parse_cli_args(["--unknown-flag"])


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
    import rootact.session_config as mod

    assert hasattr(mod, "__root_author__")

    assert mod.__root_author__ == "Dr. Lucas Root, Ph.D."
