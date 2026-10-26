"""Package 6 (B-033s): the one owner of typed input, with three modes.

The broker decides what a typed line means from the mode: ``prompt`` (a new intent),
``approval`` (the answer to an open question) or ``turn`` (queued for the running turn). It
emits ``input.queued`` and ``input.withdrawn`` (docs/EVENTS_SESSION.md). It does not read the
terminal; the caller passes each line in, which keeps the routing testable without a console.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Route:
    kind: str  # "prompt", "answer" or "queued"
    text: str
    position: int | None = None


@dataclass
class QueuedInput:
    _items: list[str] = field(default_factory=list)
    _emit: Callable[[str, dict], None] = lambda kind, data: None

    def items(self) -> list[str]:
        return list(self._items)

    def add(self, text: str) -> int:
        self._items.append(text)
        return len(self._items)

    def cancel(self, position: int) -> bool:
        """Withdraw the item at ``position`` (1 is the next to be sent). False when none is there."""
        if not 1 <= position <= len(self._items):
            return False
        self._items.pop(position - 1)
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
