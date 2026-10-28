"""BUILDER review of H4: a plan of answer steps reports every step once.

H4 holds a step's ``step.finished`` until its files are applied. A plan of
answer steps only writes nothing, and the substrate hands it to the executor
in one call. With the hold on, each finished step replaced the one held
before it, so only the last step was ever reported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.fixtures.fake_model_server import Scenario
from tests.test_headless import _ract
from tests.test_session_turn import _repo


def _plan(*actions: str) -> str:
    return json.dumps(
        {
            "assumption": "a",
            "confidence": 0.9,
            "steps": [
                {"action": a, "provider_hint": "local", "expected_artifact": ""}
                for a in actions
            ],
        }
    )


def test_every_answer_step_is_reported_once_and_done(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {
                        "reply": {
                            "kind": "text",
                            "content": _plan("Explain add", "Explain sub"),
                        }
                    },
                    {"reply": {"kind": "text", "content": "add returns a minus b."}},
                    {"reply": {"kind": "text", "content": "sub returns a minus b."}},
                ]
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "explain add and sub", "--output-format", "stream-json")

    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    finished = [e["data"] for e in events if e["kind"] == "step.finished"]
    assert [(d["n"], d["outcome"]) for d in finished] == [(1, "done"), (2, "done")]
