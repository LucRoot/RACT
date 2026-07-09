from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.cli_toggles import main, parse_cli_args


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


# RACT 0.1.1 - Trust and Tooling
