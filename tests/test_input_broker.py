"""Package 6 (B-033s): one owner of typed input, with three modes.

prompt: a line is a new intent. approval: a line answers the open question (only then).
turn: a line is queued and shown (input.queued); cancel withdraws it (input.withdrawn).
A line queued during a turn never answers an approval, even when it reads "y".
"""

from __future__ import annotations

from ract.input_broker import InputBroker


def _broker():
    events: list[tuple[str, dict]] = []
    broker = InputBroker(emit=lambda kind, data: events.append((kind, data)))
    return broker, events


def test_prompt_mode_routes_a_line_as_an_intent():
    broker, events = _broker()
    route = broker.feed("add a greeting")
    assert route.kind == "prompt" and route.text == "add a greeting"
    assert events == []


def test_approval_mode_routes_a_line_as_the_answer_and_closes_the_question():
    broker, _ = _broker()
    broker.open_question("approval", "Apply step 1 to src/calc.py? [y/N]")
    route = broker.feed("y")
    assert route.kind == "answer" and route.text == "y"
    assert broker.mode == "prompt"


def test_turn_mode_queues_a_line_and_emits_input_queued():
    broker, events = _broker()
    broker.start_turn()
    route = broker.feed("also add a test")
    assert route.kind == "queued" and route.position == 1
    assert events == [("input.queued", {"text": "also add a test", "position": 1})]
    assert broker.queue.items() == ["also add a test"]


def test_a_queued_line_that_reads_y_does_not_answer_an_approval():
    broker, _ = _broker()
    broker.start_turn()
    route = broker.feed("y")
    assert route.kind == "queued"
    assert broker.queue.items() == ["y"]


def test_cancel_withdraws_a_queued_item_and_emits_input_withdrawn():
    broker, events = _broker()
    broker.start_turn()
    broker.feed("first")
    broker.feed("second")
    assert broker.queue.cancel(1) is True
    assert ("input.withdrawn", {"position": 1}) in events
    assert broker.queue.items() == ["second"]


def test_cancel_with_a_bad_position_is_refused():
    broker, _ = _broker()
    broker.start_turn()
    assert broker.queue.cancel(3) is False
    assert broker.queue.cancel(0) is False


def test_the_queue_is_the_prepared_queue_model_so_the_view_reads_it():
    from ract.ui import queue_view as qv

    broker, _ = _broker()
    broker.start_turn()
    broker.feed("first")
    broker.feed("second")
    assert [line.text for line in broker.queue.model.items] == ["first", "second"]
    lines = qv.list_lines(broker.queue.model, 80)
    assert any("second" in line for line in lines)


def test_cancel_uses_the_model_drop_and_keeps_ids_stable():
    broker, _ = _broker()
    broker.start_turn()
    broker.feed("first")
    broker.feed("second")
    broker.queue.cancel(1)
    assert [line.id for line in broker.queue.model.items] == [2]


def test_a_turn_reader_feeds_typed_lines_into_the_broker_until_eof():

    from ract.input_broker import TurnReader

    broker, events = _broker()
    broker.start_turn()
    lines = iter(["first", "second"])

    def read_line() -> str:
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    reader = TurnReader(broker, read_line)
    reader.start()
    reader.join(timeout=5)
    assert not reader.is_alive()
    assert broker.queue.items() == ["first", "second"]
    assert [kind for kind, _ in events] == ["input.queued", "input.queued"]


def test_take_first_removes_the_next_queued_line_for_the_next_turn_without_withdrawing_it():
    broker, events = _broker()
    broker.start_turn()
    broker.feed("a")
    broker.feed("b")
    assert broker.queue.take_first() == "a"
    assert broker.queue.items() == ["b"]
    assert not any(kind == "input.withdrawn" for kind, _ in events)
    assert broker.queue.take_first() == "b"
    assert broker.queue.take_first() is None


def test_the_repl_takes_a_queued_line_before_it_reads_the_console():
    from ract.repl import ReplSession

    broker, _ = _broker()
    broker.start_turn()
    broker.feed("queued during the turn")
    session = ReplSession.__new__(ReplSession)
    session._broker = broker
    assert session._take_queued() == "queued during the turn"
    assert session._take_queued() is None
    session._broker = None
    assert session._take_queued() is None


class _Console:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, text="", **_):
        self.lines.append(str(text))


def test_the_queue_command_lists_and_drops_the_queued_lines():
    from ract.repl import ReplSession

    broker, events = _broker()
    broker.start_turn()
    broker.feed("first line")
    broker.feed("second line")
    console = _Console()
    session = ReplSession.__new__(ReplSession)
    session._broker = broker
    session._console = console
    session._cmd_queue([])
    assert any("first line" in line for line in console.lines)
    assert any("second line" in line for line in console.lines)
    console.lines.clear()
    session._cmd_queue(["drop", "1"])
    assert broker.queue.items() == ["second line"]
    assert ("input.withdrawn", {"position": 1}) in events
    assert any(
        "second line" in line or "dropped" in line.lower() for line in console.lines
    )


def test_a_queued_line_is_held_after_an_interrupt_until_the_operator_types():
    from ract.repl import ReplSession

    broker, _ = _broker()
    broker.start_turn()
    broker.feed("queued before the stop")
    session = ReplSession.__new__(ReplSession)
    session._broker = broker
    session._queue_held = True
    assert session._take_queued() is None
    session._queue_held = False
    assert session._take_queued() == "queued before the stop"


def test_red_team_a_turn_starting_while_an_approval_is_open_does_not_answer_it():
    # A new turn while a question is open must not let the next typed line answer that question.
    broker, _ = _broker()
    broker.open_question("approval", "Apply step 1? [y/N]")
    broker.start_turn()
    route = broker.feed("y")
    assert route.kind == "queued"


def test_red_team_ending_a_turn_while_an_approval_is_open_does_not_answer_it():
    broker, _ = _broker()
    broker.open_question("approval", "Apply step 1? [y/N]")
    broker.end_turn()
    route = broker.feed("y")
    assert route.kind == "prompt"


def test_the_console_reader_reads_no_key_while_an_approval_question_is_open():
    # BUILDER review of B-033s: the approval prompt reads its answer with input().
    # Type-ahead polls the same console; while the question is open it must not take
    # the keys, or the answer "y" is queued as a new request and input() waits on.
    from ract.input_broker import ConsoleLineSource

    keys = list("y\r")
    taken: list[str] = []

    def getwch() -> str:
        taken.append(keys.pop(0))
        return taken[-1]

    open_question = [True]
    source = ConsoleLineSource(
        lambda: bool(keys), getwch, paused=lambda: open_question[0]
    )
    assert source.poll() is None
    assert taken == []
    open_question[0] = False
    assert source.poll() == "y"


def test_type_ahead_in_the_repl_pauses_on_the_approval_question(monkeypatch):
    import os
    import sys

    import pytest

    if os.name != "nt":
        pytest.skip("type-ahead reads the Windows console")
    import msvcrt

    from ract import question_gate
    from ract.repl import ReplSession

    monkeypatch.setenv("RACT_TYPE_AHEAD", "1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(msvcrt, "kbhit", lambda: False)
    session = ReplSession.__new__(ReplSession)
    session._events = None
    ahead = session._start_type_ahead(1)
    try:
        assert ahead is not None
        assert ahead._source._paused is question_gate.question_open
    finally:
        ahead.stop()
        ahead.join(timeout=1)
