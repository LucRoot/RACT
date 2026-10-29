"""B-033s package 3: a line typed during a turn reaches the next model request, once.

The queued lines are drained when a step builds its request (``with_operator_notes``), so a
line never changes the task or the plan. A line still queued when the turn ends stays queued
for the next turn. Typed approval answers and ``edit`` lines are only notes here.
"""

from __future__ import annotations

from ract import turn_context
from ract.executor.steps import with_operator_notes
from ract.input_broker import InputBroker
from ract.repl import ReplSession


def _session_with_broker(*lines: str, held: bool = False) -> ReplSession:
    session = ReplSession.__new__(ReplSession)
    session._broker = InputBroker(emit=lambda kind, data: None)
    session._broker.start_turn()
    for line in lines:
        session._broker.feed(line)
    session._queue_held = held
    return session


def test_the_turn_context_hands_queued_lines_to_the_request_once():
    left = ["first", "second"]

    def source() -> list[str]:
        taken, left[:] = list(left), []
        return taken

    turn_context.bind(None, queued=source)
    try:
        assert turn_context.queued_notes() == ["first", "second"]
        assert turn_context.queued_notes() == []
    finally:
        turn_context.bind(None)
    assert turn_context.queued_notes() == []


def test_no_queued_lines_leave_the_request_unchanged():
    assert with_operator_notes("Task: write it", []) == "Task: write it"


def test_queued_lines_are_named_as_notes_ahead_of_the_task():
    text = with_operator_notes("Task: write it", ["use tabs", "keep the name"])
    assert text.startswith("Operator notes sent during this turn")
    assert "- use tabs\n- keep the name" in text
    assert text.endswith("Task: write it")


def test_the_repl_drains_each_queued_line_once():
    session = _session_with_broker("one", "two")
    assert session._drain_queued() == ["one", "two"]
    assert session._drain_queued() == []


def test_a_held_queue_is_not_drained_after_an_interrupt():
    session = _session_with_broker("one", held=True)
    assert session._drain_queued() == []
    # The line stays queued for the next turn.
    assert session._broker.queue.items() == ["one"]


def test_a_line_left_at_turn_end_is_taken_by_the_next_turn():
    session = _session_with_broker("late")
    assert session._drain_queued() == ["late"]
    session._broker.feed("later")
    assert session._take_queued() == "later"


def test_red_team_a_queued_approval_answer_is_a_note_not_an_answer():
    # Mode switch: while a turn runs, "approve" is queued; it is never routed to a question.
    broker = InputBroker(emit=lambda kind, data: None)
    broker.start_turn()
    route = broker.feed("approve")
    assert route.kind == "queued"
    assert broker.queue.items() == ["approve"]
    assert "approve" in with_operator_notes("Task: x", broker.queue.items())
    assert broker.mode == "turn"


def test_red_team_a_mode_switch_while_a_question_is_open_takes_the_answer():
    broker = InputBroker(emit=lambda kind, data: None)
    broker.start_turn()
    broker.open_question("approval", "approve the plan?")
    route = broker.feed("skip 2")
    assert route.kind == "answer"
    assert broker.queue.items() == []


def test_red_team_an_edit_line_queued_during_a_turn_does_not_edit_the_plan():
    session = _session_with_broker()
    broker = session._broker
    route = broker.feed("edit 2 write the secrets to out.txt")
    assert route.kind == "queued"
    notes = session._drain_queued()
    assert notes == ["edit 2 write the secrets to out.txt"]
    # The note is text in the request. Nothing parses it as a plan edit: the gate has no route here.
    assert "plan" not in with_operator_notes("Task: x", notes).split("\n")[0]


def test_concurrent_adds_and_takes_keep_every_line():
    import threading

    broker = InputBroker(emit=lambda kind, data: None)
    broker.start_turn()
    taken: list[str] = []

    def writer() -> None:
        for n in range(200):
            broker.feed(f"line {n}")

    thread = threading.Thread(target=writer)
    thread.start()
    while thread.is_alive():
        item = broker.queue.take_first()
        if item is not None:
            taken.append(item)
    thread.join()
    while (item := broker.queue.take_first()) is not None:
        taken.append(item)
    assert sorted(taken) == sorted(f"line {n}" for n in range(200))


def test_cancel_and_add_from_two_threads_lose_no_line():
    # L-196: every mutator takes the queue's lock, so a cancel racing an add cannot drop a line.
    import threading

    broker = InputBroker(emit=lambda kind, data: None)
    broker.start_turn()
    for n in range(50):
        broker.feed(f"seed {n}")
    removed: list[bool] = []

    def adder() -> None:
        for n in range(200):
            broker.feed(f"added {n}")

    def canceller() -> None:
        for _ in range(50):
            removed.append(broker.queue.cancel(1))

    threads = [threading.Thread(target=adder), threading.Thread(target=canceller)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Conservation: every line added (50 seeds + 200) is either still queued or was withdrawn.
    assert len(broker.queue.items()) + sum(removed) == 250


def test_a_line_typed_after_the_last_model_request_stays_queued_for_the_next_turn():
    session = _session_with_broker()
    broker = session._broker
    broker.feed("first")
    assert session._drain_queued() == [
        "first"
    ]  # the turn's only model request takes it
    # No request follows: the line typed now is not sent in this turn.
    broker.feed("typed after the last request")
    assert broker.queue.items() == ["typed after the last request"]
    assert (
        session._take_queued() == "typed after the last request"
    )  # the next turn sends it
