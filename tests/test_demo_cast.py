"""Tests that the demo asciicast file exists and is valid."""

from __future__ import annotations


import json
from pathlib import Path


def test_demo_cast_exists_and_has_events():
    cast_path = Path("docs/demo.cast")
    assert cast_path.exists(), "docs/demo.cast should exist"
    lines = cast_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 3, "cast file should have header plus at least two events"
    header = json.loads(lines[0])
    assert header.get("version") == 2
    events = [json.loads(line) for line in lines[1:] if line.strip()]
    assert any(len(event) >= 3 and event[1] == "o" for event in events)
