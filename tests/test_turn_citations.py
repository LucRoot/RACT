"""B-037b: the turn summary says which file and line citations in the answer are true.

``turn.finished`` carries ``citations`` (counts and one item per citation) for a
turn with an answer, checked by the B-037a verifier against the repository; the
renderer prints one line with the counts and names each unverified citation.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ract.session_events import EventStream
from ract.session_turn import TurnRequest, run_turn
from tests.fixtures.fake_model_server import Scenario
from tests.test_session_turn import _repo
from tests.test_turn_summary import FINISHED, _render

ANSWER = "add() is at src/calc.py:1, and sub() is at src/calc.py:99."


def _turn(tmp_path: Path, fake_model_server: Any, reply: str) -> list[Any]:
    server = fake_model_server(
        Scenario.from_dict({"turns": [{"reply": {"kind": "text", "content": reply}}]})
    )
    ws = _repo(tmp_path, server.base_url)
    stream = EventStream(session="s-test")
    events: list[Any] = []
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="where are add and sub?",
        session_id="s-test",
        resume=False,
        ask=True,
    )
    run_turn(stream, request, turn=1, cancel=threading.Event())
    return events


def test_turn_finished_counts_the_answer_citations(
    tmp_path: Path, fake_model_server: Any
) -> None:
    events = _turn(tmp_path, fake_model_server, ANSWER)
    finished = [e.data for e in events if e.kind == "turn.finished"][-1]
    citations = finished["citations"]
    assert (
        citations["verified"],
        citations["unverified"],
        citations["not_checked"],
    ) == (
        1,
        1,
        0,
    )
    items = citations["items"]
    assert [(i["path"], i["lines"], i["status"]) for i in items] == [
        ("src/calc.py", "1", "verified"),
        ("src/calc.py", "99", "unverified"),
    ]
    assert "99" in items[1]["reason"]


def test_an_answer_with_no_citations_has_zero_counts(
    tmp_path: Path, fake_model_server: Any
) -> None:
    events = _turn(tmp_path, fake_model_server, "add() subtracts.")
    finished = [e.data for e in events if e.kind == "turn.finished"][-1]
    assert finished["citations"] == {
        "verified": 0,
        "unverified": 0,
        "not_checked": 0,
        "items": [],
    }


def test_a_failed_turn_has_no_citations(tmp_path: Path) -> None:
    from tests.test_session_turn import _request

    ws = _repo(tmp_path, "http://127.0.0.1:9/v1")  # nothing listens there
    stream = EventStream(session="s-test")
    events: list[Any] = []
    stream.subscribe(events.append)
    run_turn(stream, _request(ws), turn=1, cancel=threading.Event())
    finished = [e.data for e in events if e.kind == "turn.finished"][-1]
    assert finished["outcome"] == "failed"
    assert finished["citations"] is None


def test_the_summary_prints_the_counts_and_each_unverified_citation() -> None:
    citations = {
        "verified": 1,
        "unverified": 1,
        "not_checked": 0,
        "items": [
            {"path": "src/calc.py", "lines": "1", "status": "verified", "reason": ""},
            {
                "path": "src/calc.py",
                "lines": "99",
                "status": "unverified",
                "reason": "src/calc.py has 6 lines; line 99 does not exist",
            },
        ],
    }
    text = _render([("turn.finished", dict(FINISHED, citations=citations))])
    assert "citations: 1 verified, 1 unverified" in text
    assert "src/calc.py:99: src/calc.py has 6 lines; line 99 does not exist" in text


def test_no_citation_line_when_there_are_none() -> None:
    empty = {"verified": 0, "unverified": 0, "not_checked": 0, "items": []}
    for citations in (None, empty):
        text = _render([("turn.finished", dict(FINISHED, citations=citations))])
        assert "citations:" not in text


def test_a_hostile_reason_is_printed_escaped() -> None:
    citations = {
        "verified": 0,
        "unverified": 1,
        "not_checked": 0,
        "items": [
            {
                "path": "a" + chr(0x1B) + "[31m.py",
                "lines": "1",
                "status": "unverified",
                "reason": "no such file" + chr(0x202E),
            }
        ],
    }
    text = _render([("turn.finished", dict(FINISHED, citations=citations))])
    assert chr(0x1B) not in text and chr(0x202E) not in text
