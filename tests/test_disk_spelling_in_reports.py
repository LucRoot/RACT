"""B-090 (H5): step lines and the unsigned list name a file as the disk spells it.

On Windows "Readme.md" and "README.md" are one file. When the disk holds
Readme.md and the plan says README.md, every report names Readme.md, as the
changed-files line already did.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from ract.session_events import EventStream
from ract.session_turn import TurnRequest, run_turn
from ract.workspace_path import on_disk_name
from tests.fixtures.fake_model_server import Scenario
from tests.test_session_turn import _repo

case_insensitive = pytest.mark.skipif(
    os.name != "nt", reason="one file under two spellings needs a case-insensitive disk"
)


def test_the_disk_spelling_is_returned(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "Readme.md").write_text("x", encoding="utf-8")
    assert on_disk_name(tmp_path, "docs/README.md") == "docs/Readme.md"
    assert on_disk_name(tmp_path, "docs/Readme.md") == "docs/Readme.md"


def test_a_missing_file_or_folder_keeps_the_given_name(tmp_path: Path) -> None:
    assert on_disk_name(tmp_path, "new.md") == "new.md"
    assert on_disk_name(tmp_path, "nowhere/new.md") == "nowhere/new.md"


@case_insensitive
def test_the_step_and_the_unsigned_list_name_the_disk_spelling(
    tmp_path: Path, fake_model_server: Any
) -> None:
    plan = {
        "assumption": "the readme needs a line",
        "confidence": 0.8,
        "steps": [
            {
                "action": "Add a usage line to README.md",
                "provider_hint": "local",
                "expected_artifact": "README.md",
            }
        ],
    }
    turns = [
        {"reply": {"kind": "text", "content": json.dumps(plan)}},
        {"reply": {"kind": "text", "content": "# calc\n\nUsage: add(a, b).\n"}},
    ]
    turns += [{"reply": {"kind": "text", "content": "Done."}}] * 3
    server = fake_model_server(Scenario.from_dict({"turns": turns}))
    ws = _repo(tmp_path, server.base_url)
    (ws / "README.md").rename(ws / "Readme.md")
    stream = EventStream(session="s-test")
    events: list[Any] = []
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="add a usage line",
        session_id="s-test",
        resume=False,
    )
    run_turn(stream, request, turn=1, cancel=threading.Event())
    steps = [e.data for e in events if e.kind == "step.finished"]
    finished = [e.data for e in events if e.kind == "turn.finished"][-1]
    assert finished["outcome"] == "done", finished
    assert [s["artifact"] for s in steps] == ["Readme.md"]
    assert finished["changed"] == ["Readme.md"]
    assert finished["provenance"]["unsigned_files"] in ([], ["Readme.md"])
