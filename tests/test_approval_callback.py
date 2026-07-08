# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.approval_callback import (
    auto_approval_callback,
    console_approval_callback,
    yolo_approval_callback,
)
from rootact.manager import Step


def test_yolo_approval_callback_always_true() -> None:
    step = Step(action="delete", provider_hint="code", expected_artifact="x")
    assert yolo_approval_callback(step) is True


def test_auto_approval_callback_blocks_risky_action() -> None:
    step = Step(action="delete file", provider_hint="code", expected_artifact="x")
    assert auto_approval_callback(step) is False


def test_auto_approval_callback_allows_safe_action() -> None:
    step = Step(action="write tests", provider_hint="code", expected_artifact="x")
    assert auto_approval_callback(step) is True


def test_console_approval_callback_accepts_yes(monkeypatch) -> None:
    step = Step(action="write", provider_hint="code", expected_artifact="x")
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    assert console_approval_callback(step) is True


def test_console_approval_callback_rejects_no(monkeypatch) -> None:
    step = Step(action="write", provider_hint="code", expected_artifact="x")
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    assert console_approval_callback(step) is False


def test_console_approval_callback_rejects_eof(monkeypatch) -> None:
    step = Step(action="write", provider_hint="code", expected_artifact="x")
    monkeypatch.setattr(
        "builtins.input", lambda _prompt: (_ for _ in ()).throw(EOFError)
    )
    assert console_approval_callback(step) is False


# RACT 0.1.0 - Initial Public Release
