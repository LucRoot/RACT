"""B-121 (hosted FOUND 3): a request about a failing test that ran no test is not 'done'.

On the hosted model a failing-test task fixed src/calc.py and the summary
headline said done, with "verified: RACT ran no tests this turn" below it.
Until slice (c) runs tests, such a turn says ``verified: no`` and ends with
"not verified: RACT cannot run tests yet (slice c)".
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from ract.session_events import EventStream, SessionEvent
from ract.session_render import PlainRenderer
from ract.session_turn import TurnRequest, run_turn
from ract.turn_summary import names_a_test
from tests.test_session_turn import _repo

LAST_LINE = "not verified: RACT cannot run tests yet (slice c)"


@pytest.mark.parametrize(
    "intent",
    [
        "tests/test_calc.py::test_add fails, fix it",
        "test_add is failing",
        "the test fails after my change",
        "fix the failing tests",
        "tests are red since yesterday",
        "make tests/test_calc.py pass",
    ],
)
def test_requests_that_name_a_test(intent: str) -> None:
    assert names_a_test(intent)


@pytest.mark.parametrize(
    "intent",
    ["fix add", "explain this project", "rename calc to arithmetic", "", "latest news"],
)
def test_requests_that_name_no_test(intent: str) -> None:
    assert not names_a_test(intent)


def _turn(ws: Path, intent: str) -> tuple[int, list[SessionEvent], str]:
    out: list[str] = []
    stream = EventStream(session="s-b121")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    stream.subscribe(PlainRenderer(out.append))
    request = TurnRequest(
        config=ws / "ract.yaml", intent=intent, session_id="s-b121", resume=False
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    return code, events, "".join(out)


def test_wrights_failing_test_task_is_not_verified(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)

    code, events, text = _turn(ws, "tests/test_calc.py::test_add fails, fix it")

    assert code == 0
    finished = events[-1].data
    assert finished["verification"] == {
        "status": "not-run",
        "runs": [],
        "claims": [],
        "test_named": True,
    }
    lines = [line.strip() for line in text.strip().splitlines()]
    assert "verified: no" in lines
    assert "verified: RACT ran no tests this turn" not in lines
    assert lines[-1] == LAST_LINE


def test_a_request_naming_no_test_keeps_the_plain_line(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)

    code, events, text = _turn(ws, "make add() add")

    assert code == 0
    assert "test_named" not in events[-1].data["verification"]
    assert "verified: RACT ran no tests this turn" in text
    assert LAST_LINE not in text
