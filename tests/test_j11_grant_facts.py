"""J11 follow-up (operator order 2026-11-03 A6): the manager sees the grant.

The hosted J11 run planned around the grant because the manager is never told
one exists: the session's status line knows ("this grant lets RACT run:
tests") but the planning request does not, so a cautious model assumes the
no-grant branch of the manager prompt and answers by inspection. The facts
block puts the grant's rules in the planning request, next to the memory and
retrieval blocks, so the model plans the fix it could not plan before.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ract.session_events import EventStream
from ract.session_turn import TurnRequest, run_turn, tier3_facts_block


def _grant(holds: bool, rules: tuple[str, ...] = ("tests",)) -> Any:
    return SimpleNamespace(
        holds=holds,
        policy=SimpleNamespace(
            commands=SimpleNamespace(
                allow=[SimpleNamespace(id=rule) for rule in rules]
            )
        ),
    )


def test_facts_block_names_the_rules_when_the_grant_holds() -> None:
    block = tier3_facts_block(_grant(True))
    assert "signed grant" in block
    assert "tests" in block
    assert "asks" in block


def test_facts_block_names_every_rule() -> None:
    block = tier3_facts_block(_grant(True, ("tests", "build")))
    assert "tests" in block
    assert "build" in block


def test_facts_block_empty_without_a_grant() -> None:
    assert tier3_facts_block(_grant(False)) == ""
    assert tier3_facts_block(None) == ""


def test_facts_block_carries_no_key_material() -> None:
    block = tier3_facts_block(_grant(True))
    assert "PRIVATE" not in block
    assert "BEGIN" not in block
    assert "passphrase" not in block.lower()


def test_session_turn_passes_the_facts_to_the_run(
    monkeypatch: Any, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run_ract(config: Any, intent: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(is_ok=lambda: False, error="stopped for the test")

    monkeypatch.setattr("ract.ract_runner.run_ract", fake_run_ract)

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "ract.yaml").write_text(
        "project:\n  name: calc\n"
        "manager_provider: local\n"
        "providers:\n"
        "  local:\n"
        "    adapter: local_http\n"
        "    url: http://127.0.0.1:11434/v1\n"
        "    model: fake\n",
        encoding="utf-8",
    )
    stream = EventStream(session="s-j11facts")
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="run the tests",
        session_id=None,
        resume=False,
        tier3_facts="Tier 3 facts: a signed grant covers: tests.",
    )
    run_turn(stream, request, turn=1, cancel=threading.Event())

    assert captured.get("tier3_facts") == "Tier 3 facts: a signed grant covers: tests."
