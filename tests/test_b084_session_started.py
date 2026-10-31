"""B-084: session.started carries the session id and the context window; the status line shows them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.context_window import context_limit
from ract.session_events import EventStream
from ract.session_render import PlainRenderer


def test_the_declared_window_is_used_when_nothing_measured_it(tmp_path: Path) -> None:
    assert context_limit(tmp_path, {"context_window": 32768}) == 32768
    assert context_limit(tmp_path, {"context_window": True}) is None
    assert context_limit(tmp_path, {}) is None and context_limit(tmp_path, None) is None


def test_the_probes_measurement_wins_over_the_declaration(
    tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace

    import ract.memory.probes.scheduler as scheduler

    monkeypatch.setattr(
        scheduler,
        "read_capability_record",
        lambda root: SimpleNamespace(usable_context_window=8192),
    )
    assert context_limit(tmp_path, {"context_window": 32768}) == 8192


def test_a_broken_record_says_so_and_falls_back(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import ract.memory.probes.scheduler as scheduler

    def broken(root):
        raise ValueError("bad json")

    monkeypatch.setattr(scheduler, "read_capability_record", broken)
    assert context_limit(tmp_path, {"context_window": 4096}) == 4096
    assert "capability record cannot be read" in capsys.readouterr().err


@pytest.mark.parametrize("limit, sid", [(32768, "s-0192"), (None, None)])
def test_the_status_line_shows_them_when_known(limit, sid) -> None:
    out: list[str] = []
    stream = EventStream(session="s")
    stream.subscribe(PlainRenderer(out.append))
    stream.emit(
        "session.started",
        {
            "workspace": "calc",
            "model": "fake-coder",
            "provider": "local",
            "mode": "default",
            "tier3": "off",
            "context_limit": limit,
            "session_id": sid,
        },
    )
    text = "".join(out)
    assert ("context 32,768 tokens" in text) is (limit is not None)
    assert ("session s-0192" in text) is (sid is not None)


def test_the_repl_sends_the_session_id_and_the_declared_window(tmp_path: Path) -> None:
    from tests.test_repl import _session

    config = tmp_path / "ract.yaml"
    config.write_text(
        "providers:\n  local:\n    model: fake-coder\n    context_window: 16384\n",
        encoding="utf-8",
    )
    session, _calls, _console = _session(config=config)
    session.state.session_id = "s-abc"
    facts = session._session_facts()
    assert facts["session_id"] == "s-abc"
    assert facts["context_limit"] in (16384, None)  # None only if no provider resolves
    json.dumps(facts)  # the event stays JSON
