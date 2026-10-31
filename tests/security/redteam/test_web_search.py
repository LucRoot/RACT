"""B-027 red team: ``web_search`` has no provider, so it never sends anything."""

from __future__ import annotations

from pathlib import Path

from tests.security.redteam._world import build, call


def test_web_search_refuses_with_a_hint(tmp_path: Path, monkeypatch) -> None:
    world = build(tmp_path, monkeypatch)
    rooted, asked, _runner = call(world, "web_search", {"query": "anything"})
    assert not rooted.is_ok() and "no provider" in rooted.error and asked == []
