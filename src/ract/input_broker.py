"""Package 6 (B-033s): the one owner of typed input, with three modes.

The broker decides what a typed line means from the mode: ``prompt`` (a new intent),
``approval`` (the answer to an open question) or ``turn`` (queued for the running turn). It
emits ``input.queued`` and ``input.withdrawn`` (docs/EVENTS_SESSION.md). It does not read the
terminal; the caller passes each line in, which keeps the routing testable without a console.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ract.ui.queue_view import QueueError, QueueModel


@dataclass(frozen=True)
class Route:
    kind: str  # "prompt", "answer" or "queued"
    text: str
    position: int | None = None


@dataclass
class QueuedInput:
    """The queued lines, held as the prepared ``QueueModel`` (package J) so the view reads them."""

    _emit: Callable[[str, dict], None] = lambda kind, data: None
    model: QueueModel = field(default_factory=QueueModel)

    def items(self) -> list[str]:
        return [line.text for line in self.model.items]

    def add(self, text: str) -> int:
        self.model = self.model.append(text)
        return len(self.model.items)

    def take_first(self) -> str | None:
        """Remove and return the next queued line for the next turn (no event: it is sent, not withdrawn)."""
        if not self.model.items:
            return None
        text = self.model.items[0].text
        self.model, _ = self.model.drop(1)
        return text

    def cancel(self, position: int) -> bool:
        """Withdraw the item at ``position`` (1 is the next to be sent). False when none is there."""
        try:
            self.model, _ = self.model.drop(position)
        except QueueError:
            return False
        self._emit("input.withdrawn", {"position": position})
        return True


class InputBroker:
    def __init__(self, emit: Callable[[str, dict], None]) -> None:
        self.mode = "prompt"
        self._question: str | None = None
        self._emit = emit
        self.queue = QueuedInput(_emit=emit)

    def start_turn(self) -> None:
        self.mode = "turn"

    def end_turn(self) -> None:
        self.mode = "prompt"

    def open_question(self, mode: str, question: str) -> None:
        if mode != "approval":
            raise ValueError(f"unknown question mode: {mode}")
        self.mode = "approval"
        self._question = question

    def feed(self, text: str) -> Route:
        if self.mode == "approval":
            self.mode = "prompt"
            self._question = None
            return Route("answer", text)
        if self.mode == "turn":
            position = self.queue.add(text)
            self._emit("input.queued", {"text": text, "position": position})
            return Route("queued", text, position)
        return Route("prompt", text)


class TurnReader(threading.Thread):
    """Reads typed lines during a turn and feeds each one to the broker.

    ``read_line`` blocks until a line arrives and raises ``EOFError`` at the end of input; the
    thread then ends. The reader is a daemon: a read that is still blocked when the turn ends
    does not hold the process open (the console read cannot be interrupted from here).
    """

    def __init__(self, broker: InputBroker, read_line: Callable[[], str]) -> None:
        super().__init__(name="ract-input-reader", daemon=True)
        self._broker = broker
        self._read_line = read_line

    def run(self) -> None:
        while True:
            try:
                line = self._read_line()
            except EOFError:
                return
            self._broker.feed(line)


class ConsoleLineSource:
    """Assembles typed lines from a polled console, without a blocking read (package 6).

    ``kbhit`` says whether a key is waiting and ``getwch`` returns it (msvcrt on Windows, injected
    in tests). ``poll()`` reads at most the waiting keys and returns a line when Enter arrives, or
    None. Ctrl-C sets ``stopped`` and returns no line.

    While ``paused()`` is true it reads no key at all: an approval question reads its answer from
    the same console with ``input()``, and a key taken here would be queued as a new request
    instead of answering (BUILDER review of B-033s).
    """

    _ENTER = (chr(13), chr(10))
    _BACKSPACE = (chr(8), chr(127))
    _CTRL_C = chr(3)

    def __init__(
        self,
        kbhit: Callable[[], bool],
        getwch: Callable[[], str],
        on_ctrl_c: Callable[[], None] | None = None,
        paused: Callable[[], bool] | None = None,
    ) -> None:
        self._kbhit = kbhit
        self._getwch = getwch
        self._on_ctrl_c = on_ctrl_c
        self._paused = paused if paused is not None else (lambda: False)
        self._chars: list[str] = []
        self.stopped = False

    def poll(self) -> str | None:
        while not self.stopped and not self._paused() and self._kbhit():
            key = self._getwch()
            if key == self._CTRL_C:
                self.stopped = True
                if self._on_ctrl_c is not None:
                    self._on_ctrl_c()
                return None
            if key in self._ENTER:
                line = "".join(self._chars)
                self._chars.clear()
                return line
            if key in self._BACKSPACE:
                if self._chars:
                    self._chars.pop()
                continue
            self._chars.append(key)
        return None


class TypeAhead(threading.Thread):
    """Polls a ConsoleLineSource during a turn and feeds each line to the broker (package 6).

    ``stop()`` ends the loop; the thread is a daemon, and the loop checks the stop flag between polls,
    so it never blocks on the console.
    """

    def __init__(
        self, broker: InputBroker, source: Any, interval: float = 0.05
    ) -> None:
        super().__init__(name="ract-type-ahead", daemon=True)
        self._broker = broker
        self._source = source
        self._interval = interval
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            line = self._source.poll()
            if line is not None:
                self._broker.feed(line)
            self._halt.wait(self._interval)

    def stop(self) -> None:
        self._halt.set()
