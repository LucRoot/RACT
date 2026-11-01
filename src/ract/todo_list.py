"""The to-do list a model writes during a run, and the harness keeps (B-177, first slice).

Pure: no file read on import, no event, no clock. The list changes only through ``apply_todo_facts``,
which the harness calls with the facts a ``todo`` tool call returns, and through ``tick``, which the
harness calls with evidence (a check that passed). A model's claim that an item is done never ticks it:
it is kept as the model's claim and the view says so; the item stays open until the harness has evidence.
The view uses the plan checklist's markers (B-053a). Item text is shown with control characters as
escapes (``visible_text``), so nothing a model writes can hide itself on a terminal.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ract.cell_wrap import wrap_cells
from ract.session_events import visible_text

MAX_ITEM_CHARS = 200
ORIGINS = ("model", "plan")
STATES = ("open", "done", "dropped")
MARKERS = {"open": "[ ]", "claim": "[?]", "done": "[x]", "dropped": "[-]"}
SAVE_NAME = "todo.json"


@dataclass
class TodoItem:
    """One item. ``evidence`` is set only by ``tick``, from a check that passed."""

    id: int
    text: str
    origin: str = "model"
    state: str = "open"
    model_claim: bool = False
    evidence: str | None = None


@dataclass
class TodoList:
    """The items, in the order they were added."""

    items: list[TodoItem] = field(default_factory=list)
    next_id: int = 1

    def add(self, text: str, origin: str = "model") -> TodoItem:
        if origin not in ORIGINS:
            raise ValueError(f"origin must be one of {ORIGINS}, not {origin!r}")
        clean = " ".join(visible_text(text).split())[:MAX_ITEM_CHARS]
        if not clean:
            raise ValueError("an item needs some text")
        item = TodoItem(id=self.next_id, text=clean, origin=origin)
        self.items.append(item)
        self.next_id += 1
        return item

    def get(self, item_id: int) -> TodoItem:
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(f"no to-do item {item_id}")

    def claim_done(self, item_id: int) -> TodoItem:
        """The model says an item is done. This labels the claim; it ticks nothing."""
        item = self.get(item_id)
        if item.state == "open":
            item.model_claim = True
        return item

    def tick(self, item_id: int, evidence: str) -> TodoItem:
        """Harness only: a check that passed ticks the item. The evidence names that check."""
        if not evidence.strip():
            raise ValueError("evidence must name the check that passed")
        item = self.get(item_id)
        if item.state == "dropped":
            raise ValueError(f"item {item_id} was dropped; it cannot be ticked")
        item.state = "done"
        item.evidence = " ".join(visible_text(evidence).split())[:MAX_ITEM_CHARS]
        return item

    def drop(self, item_id: int) -> TodoItem:
        item = self.get(item_id)
        if item.state == "done":
            raise ValueError(f"item {item_id} is done; it stays on the list as done")
        item.state = "dropped"
        return item

    def counts(self) -> dict[str, int]:
        out = {state: 0 for state in STATES}
        for item in self.items:
            out[item.state] += 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"next_id": self.next_id, "items": [asdict(item) for item in self.items]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TodoList":
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("the to-do file has no item list")
        items = [TodoItem(**item) for item in data["items"]]
        for item in items:
            if item.state not in STATES or item.origin not in ORIGINS:
                raise ValueError(f"item {item.id} has an unknown state or origin")
        return cls(items=items, next_id=int(data.get("next_id", len(items) + 1)))


def apply_todo_facts(todo: TodoList, facts: dict[str, Any]) -> str:
    """Apply the operation a ``todo`` tool call returned. The model has no ``done``: only ``tick`` ticks."""
    op = facts.get("todo_op") or {}
    kind = op.get("op")
    if kind == "add":
        item = todo.add(str(op.get("text", "")), origin="model")
        return f"added item {item.id}"
    if kind == "claim_done":
        item = todo.claim_done(int(op["id"]))
        return f"item {item.id}: the model's claim is shown; it stays open until a check passes"
    if kind == "drop":
        item = todo.drop(int(op["id"]))
        return f"dropped item {item.id}"
    raise ValueError(f"unknown to-do operation {kind!r}")


def save(todo: TodoList, folder: Path) -> Path:
    """Write the list to ``folder/todo.json`` through a temporary file, so a crash leaves the old list."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / SAVE_NAME
    temp = folder / (SAVE_NAME + ".tmp")
    temp.write_text(json.dumps(todo.to_dict(), indent=2), encoding="utf-8")
    temp.replace(target)
    return target


def load(folder: Path) -> TodoList:
    """The saved list, or an empty one when none was saved. A file that does not parse is an error."""
    target = folder / SAVE_NAME
    if not target.exists():
        return TodoList()
    return TodoList.from_dict(json.loads(target.read_text(encoding="utf-8")))


def todo_lines(todo: TodoList, width: int) -> list[str]:
    """The list as lines of at most ``width`` columns, in the checklist's markers, in plain words."""
    counts = todo.counts()
    head = (
        f"to-do list: {counts['open']} open, {counts['done']} done, "
        f"{counts['dropped']} dropped"
    )
    out = wrap_cells(head, width)
    if not todo.items:
        out += wrap_cells("nothing on the list yet", width)
    for item in todo.items:
        if item.state == "done":
            marker = MARKERS["done"]
        elif item.state == "dropped":
            marker = MARKERS["dropped"]
        elif item.model_claim:
            marker = MARKERS["claim"]
        else:
            marker = MARKERS["open"]
        out += wrap_cells(
            f"{marker} {item.id}. {item.text}", width, subsequent_indent="    "
        )
        if item.state == "done":
            out += wrap_cells(
                f"checked: {item.evidence}",
                width,
                initial_indent="    ",
                subsequent_indent="    ",
            )
        elif item.state == "dropped":
            out += wrap_cells(
                "dropped", width, initial_indent="    ", subsequent_indent="    "
            )
        elif item.model_claim:
            out += wrap_cells(
                "model says done, not checked: stays open until a check passes",
                width,
                initial_indent="    ",
                subsequent_indent="    ",
            )
    return out
