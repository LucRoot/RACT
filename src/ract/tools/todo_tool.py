"""The ``todo`` tool: a model adds an item, claims one done, or drops one (B-177, first slice).

Tier 0 and not mutating: the call changes no file. It returns facts (``todo_op``); the harness applies
them with ``ract.todo_list.apply_todo_facts``. The tool is defined here but NOT registered yet: the
registry would offer it to a model before the harness applies its facts (the wiring is the next slice).
A ``done`` operation does not exist: only a passing check ticks an item (``TodoList.tick``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ract.core.threat_model import CapabilityTier
from ract.tools import ToolRefused, ToolResult, ToolSpec

TODO_CAP_BYTES = 4096
MAX_TEXT_CHARS = 400


class TodoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["add", "claim_done", "drop"]
    text: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    id: int | None = Field(default=None, ge=1)


def run_todo(root: Path, args: TodoArgs) -> ToolResult:
    """Validate the operation and return it as facts. Nothing is written here."""
    if args.op == "add":
        if not args.text or not args.text.strip():
            raise ToolRefused("add needs the text of the item", "say what the item is")
        op: dict[str, object] = {"op": "add", "text": args.text}
        text = "to-do: the item is added; the list shows it as open"
    else:
        if args.id is None:
            raise ToolRefused(
                f"{args.op} needs the item number", "give the id from the list"
            )
        op = {"op": args.op, "id": args.id}
        if args.op == "claim_done":
            text = "to-do: your claim is shown as yours; the item stays open until a check passes"
        else:
            text = "to-do: the item is dropped"
    return ToolResult(text=text, facts={"todo_op": op})


TODO_TOOL = ToolSpec(
    "todo",
    CapabilityTier.TIER_0_READ,
    TodoArgs,
    False,
    TODO_CAP_BYTES,
    run_todo,
)
