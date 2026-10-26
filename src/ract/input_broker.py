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
