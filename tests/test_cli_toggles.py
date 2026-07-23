from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

import pytest

from ract.cli_toggles import main, parse_cli_args


def _set_home(tmp_path, monkeypatch):
    home = str(tmp_path)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)


def test_parse_cli_args_parses_known_flags() -> None:
    args = parse_cli_args(
        ["--yolo", "--auto", "--reload", "--session", "abc", "--resume"]
    )
    assert args.yolo is True
    assert args.auto is True
    assert args.reload is True
    assert args.session_id == "abc"
    assert args.resume is True


def test_parse_cli_args_defaults() -> None:
    args = parse_cli_args([])
    assert args.yolo is False
    assert args.auto is False
    assert args.reload is False
    assert args.session_id is None
    assert args.resume is False


def test_unknown_flag_raises_system_exit() -> None:
    with pytest.raises(SystemExit):
        parse_cli_args(["--unknown"])


def test_main_returns_int() -> None:
    result = main([])
    assert isinstance(result, int)


def test_main_persists_yolo_auto_reload_session(tmp_path, monkeypatch) -> None:
    _set_home(tmp_path, monkeypatch)
    result = main(["--yolo", "--auto", "--reload", "--session", "xyz"])
    assert result == 0
    saved = json.loads((tmp_path / ".ract" / "session.json").read_text())
    assert saved["yolo"] is True
    assert saved["auto"] is True
    assert saved["reload"] is True
    assert saved["session_id"] == "xyz"


def test_main_resume_loads_existing_session(tmp_path, monkeypatch) -> None:
    _set_home(tmp_path, monkeypatch)
    session_path = tmp_path / ".ract" / "session.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps(
            {
                "yolo": True,
                "auto": False,
                "reload": False,
                "session_id": "old",
                "resume": False,
            }
        ),
        encoding="utf-8",
    )
    result = main(["--resume"])
    assert result == 0
    saved = json.loads(session_path.read_text())
    assert saved["session_id"] == "old"
    assert saved["resume"] is False


def test_main_resume_missing_session_exits(tmp_path, monkeypatch) -> None:
    _set_home(tmp_path, monkeypatch)
    with pytest.raises(SystemExit, match="No existing session to resume."):
        main(["--resume"])


def test_parse_cli_args_uses_default_empty_argv() -> None:
    args = parse_cli_args()
    assert args.yolo is False
    assert args.auto is False
    assert args.reload is False
    assert args.session_id is None
    assert args.resume is False


# RACT 0.1.1 - Trust and tooling
