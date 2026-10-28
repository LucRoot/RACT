"""J3 on the fake server: a question is answered after the model reads the code (B-011a).

A real ``ract -p --ask`` process. The scripted model first asks for ``read_file`` on
``src/calc.py``, then answers from what it read. The workspace also holds a ``.env``
that no request may carry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.fixtures.fake_model_server import Scenario
from tests.test_headless import _ract
from tests.test_session_turn import _repo

ANSWER = "add() is wrong: line 2 returns a - b, so it subtracts."


def test_j3_the_answer_cites_the_file_the_model_read(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {
                        "reply": {
                            "kind": "text",
                            "content": json.dumps(
                                {
                                    "tool": "read_file",
                                    "arguments": {"path": "src/calc.py"},
                                }
                            ),
                        }
                    },
                    {
                        "reply": {
                            "kind": "text",
                            "content": json.dumps({"final": ANSWER}),
                        }
                    },
                ]
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)
    (ws / ".env").write_text("TOKEN=never-leave-the-machine\n", encoding="utf-8")

    result = _ract(
        ws, "-p", "--ask", "is add() correct?", "--output-format", "stream-json"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    kinds = [e["kind"] for e in events]
    assert "tool.call.started" in kinds and "tool.call.finished" in kinds
    started = next(e["data"] for e in events if e["kind"] == "tool.call.started")
    assert started["tool"] == "read_file" and started["tier"] == "T0"
    text = "".join(
        e["data"].get("text", "") for e in events if e["kind"] == "agent.text.delta"
    )
    assert ANSWER in text
    requests = server.chat_requests
    assert len(requests) == 2
    assert "return a - b" in json.dumps(requests[1].body)
    assert "never-leave-the-machine" not in json.dumps([r.body for r in requests])
