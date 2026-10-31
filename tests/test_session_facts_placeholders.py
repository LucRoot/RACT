"""Package 5 (handoff 9): session.started sends null, not "?", for a model or provider no config names.

The renderer used to read "?" as the placeholder (session_render.py _on_session_started). The event
carries None; the renderer prints "no model" and "no provider" from None alone.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ract.repl import ReplSession


def test_a_session_with_no_config_sends_null_model_and_provider(tmp_path: Path):
    session = ReplSession.__new__(ReplSession)
    # B-084: session.started carries the session id from the state.
    session.state = SimpleNamespace(
        config=tmp_path / "ract.yaml", dry_run=False, auto=False, session_id="s-1"
    )
    facts = session._session_facts()
    assert facts["model"] is None
    assert facts["provider"] is None
