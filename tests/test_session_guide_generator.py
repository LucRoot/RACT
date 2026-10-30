"""B-089: the session guide is written by tools/build_session_guide.py, not by hand.

The committed docs/SESSION_GUIDE.md must equal the generator's output, so a sample or a
known issue edited by hand fails here. The generator reads files only: it must build the
guide with the network closed.
"""

from __future__ import annotations

import importlib.util
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "build_session_guide.py"
GUIDE = ROOT / "docs" / "SESSION_GUIDE.md"


def _generator():
    spec = importlib.util.spec_from_file_location("build_session_guide", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_committed_guide_is_the_generator_output():
    built = _generator().build()
    committed = GUIDE.read_text(encoding="utf-8")
    assert committed == built, (
        "docs/SESSION_GUIDE.md differs from tools/build_session_guide.py output: "
        "run `python tools/build_session_guide.py` and commit the result"
    )


def test_the_guide_has_no_unfilled_placeholder():
    assert "{{" not in GUIDE.read_text(encoding="utf-8")


def test_the_generator_needs_no_network(monkeypatch: pytest.MonkeyPatch):
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the guide generator opened a network connection")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert _generator().build().startswith("# Session guide")
