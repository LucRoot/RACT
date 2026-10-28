"""The queue of lines typed during a turn, as data and text (B-033a and B-033b, PREPARED).

Pure: no import from the input handling and no event kinds. Nothing here reads a key
or emits an event; the BUILDER wires it when B-033s lands. Each function takes data and
returns data or text. Text is folded by terminal columns (`ract.cell_wrap`), so 80, 60
and 40 columns are the same code path.

Rich output carries `[dim]` and `[/dim]` around the queued tag; plain output has none.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ract.cell_wrap import wrap_cells


@dataclass(frozen=True)
class QueuedLine:
    """One line typed during a turn: an id that never repeats, and the text."""

    id: int
    text: str


@dataclass(frozen=True)
class QueueModel:
    """The queued lines in the order they were typed. Ids count up and are not reused."""

    items: tuple[QueuedLine, ...] = ()
    next_id: int = 1
    _cleared: tuple[str, ...] = field(default=(), repr=False)

    def append(self, text: str) -> QueueModel:
        """A new model with ``text`` queued last."""
        line = QueuedLine(self.next_id, text)
        return QueueModel(self.items + (line,), self.next_id + 1, self._cleared)

    def take_last(self) -> tuple[QueueModel, QueuedLine | None]:
        """Up: the last queued line goes back to the operator for editing (B-033 item 7)."""
        if not self.items:
            return self, None
        return QueueModel(self.items[:-1], self.next_id, self._cleared), self.items[-1]

    def drop(self, position: int) -> tuple[QueueModel, QueuedLine]:
        """Remove the line at 1-based ``position``. Raises ``QueueError`` when there is none."""
        if not self.items:
            raise QueueError("the queue is empty; nothing to drop")
        if not 1 <= position <= len(self.items):
            raise QueueError(
                f"no queued line {position}; the queue has {len(self.items)} "
                f"({', '.join(str(i + 1) for i in range(len(self.items)))})"
            )
        removed = self.items[position - 1]
        rest = self.items[: position - 1] + self.items[position:]
        return QueueModel(rest, self.next_id, self._cleared), removed


class QueueError(ValueError):
    """A bad request to the queue: say what happened and what to do next."""


def indicator(count: int, *, rich: bool = False) -> str:
    """The count shown while a turn runs: ``1 queued`` or ``2 queued``; nothing when empty."""
    if count <= 0:
        return ""
    text = f"{count} queued"
    return f"[dim]{text}[/dim]" if rich else text


def list_lines(model: QueueModel, width: int, *, rich: bool = False) -> list[str]:
    """``/queue`` with no argument: a heading, then one numbered line per queued item."""
    dim_open, dim_close = ("[dim]", "[/dim]") if rich else ("", "")
    if not model.items:
        return wrap_cells(
            "queue is empty; lines you type while a turn runs appear here", width
        )
    lines = [f"queue ({len(model.items)}):"]
    for position, item in enumerate(model.items, start=1):
        head = f"  {position}. "
        body = f"{item.text}  {dim_open}queued{dim_close}"
        folded = wrap_cells(body, width, initial_indent=head, subsequent_indent="     ")
        lines.extend(folded)
    return lines


def drop_message(
    model: QueueModel, argument: str, width: int
) -> tuple[QueueModel, list[str]]:
    """``/queue drop <n>``: the new model and the lines to show. A bad request changes nothing."""
    text = argument.strip()
    if not text:
        message = "usage: /queue drop <n>; /queue lists the numbers"
        return model, wrap_cells(message, width)
    try:
        position = int(text)
    except ValueError:
        message = f"'{text}' is not a number; usage: /queue drop <n>"
        return model, wrap_cells(message, width)
    try:
        new_model, removed = model.drop(position)
    except QueueError as exc:
        return model, wrap_cells(str(exc), width)
    message = f"dropped {removed.id}: {removed.text}"
    return new_model, wrap_cells(message, width)
