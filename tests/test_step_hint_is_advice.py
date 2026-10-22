"""B-062: a failed step's hint is advice in words, never a category tag.

`Rooted.hint` holds a category word for many failures ("empty_output",
"approval", "mcp"). The session printed it as `  hint: empty_output` under
the step line, which reads as advice and says nothing; the real hint for the
turn followed on the next line.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ract.session_turn import TurnRequest, run_turn
from tests.fixtures.fake_model_server import Scenario
from tests.test_session_events_v2 import _stream
from tests.test_session_turn import _plan, _repo


def test_an_empty_reply_closes_the_step_without_a_tag_as_its_hint(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {"reply": {"kind": "text", "content": _plan("src/calc.py")}},
                    {"reply": {"kind": "text", "content": ""}},
                ]
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)
    stream, events = _stream()

    run_turn(
        stream,
        TurnRequest(
            config=ws / "ract.yaml", intent="fix add", session_id=None, resume=False
        ),
        turn=1,
        cancel=threading.Event(),
    )

    [finished] = [e for e in events if e.kind == "step.finished"]
    assert finished.data["outcome"] in {"failed", "refused"}
    hint = finished.data["hint"]
    assert hint is None or " " in hint.strip(), hint


def test_advice_keeps_sentences_and_drops_tags() -> None:
    from ract.executor.steps import _advice

    assert _advice("empty_output") is None
    assert _advice("approval") is None
    assert _advice("") is None
    assert _advice(None) is None
    sentence = "start your model server, or fix the provider url in ract.yaml"
    assert _advice(sentence) == sentence
