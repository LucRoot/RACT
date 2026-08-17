"""Fence intercepts every DeleteFileAction before the transaction opens."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ract.contracts.fence import FenceGate, PlausibleReasonBrief
from ract.core.actions import DeleteFileAction, WriteFileAction
from ract.core.transaction import UnfencedDeleteError, new_step_id, open_transaction


def _fresh_ws() -> Path:
    return Path(tempfile.mkdtemp())


def test_all_delete_actions_pass_through_fence() -> None:
    """A ``DeleteFileAction`` handed to ``FenceGate.evaluate`` gets a brief
    and a ticket; the ticket is what ``open_transaction`` consumes."""
    ws = _fresh_ws()
    (ws / "target.txt").write_text("body")
    gate = FenceGate(ws)
    action = DeleteFileAction(path="target.txt", rationale="cleanup")
    brief, ticket = gate.evaluate(action)
    assert isinstance(brief, PlausibleReasonBrief)
    assert brief.path == "target.txt"
    assert FenceGate.has_ticket(ticket)


def test_transaction_refuses_unfenced_delete() -> None:
    """Structural intercept: ``open_transaction`` refuses a delete action
    that has not passed through Fence (module_06 step 8)."""
    action = DeleteFileAction(path="hazardous.py", rationale="looks unused")
    with pytest.raises(UnfencedDeleteError):
        open_transaction(
            step_id=new_step_id(),
            parent_snapshot="a" * 40,
            worktree_path=Path("."),
            actions=(action,),
            fence_ticket_id=None,
        )


def test_transaction_admits_fenced_delete_once() -> None:
    """A ticket from ``FenceGate.evaluate`` admits the delete exactly once."""
    ws = _fresh_ws()
    (ws / "target.txt").write_text("body")
    gate = FenceGate(ws)
    action = DeleteFileAction(path="target.txt", rationale="cleanup")
    _, ticket = gate.evaluate(action)
    txn = open_transaction(
        step_id=new_step_id(),
        parent_snapshot="b" * 40,
        worktree_path=ws,
        actions=(action,),
        fence_ticket_id=ticket,
    )
    assert txn.step_id is not None
    # Second open with the same ticket must be refused: single-use.
    with pytest.raises(UnfencedDeleteError):
        open_transaction(
            step_id=new_step_id(),
            parent_snapshot="c" * 40,
            worktree_path=ws,
            actions=(action,),
            fence_ticket_id=ticket,
        )


def test_transaction_permits_non_delete_action_without_ticket() -> None:
    """The gate only fires on DeleteFileAction; other actions are free-pass."""
    write_action = WriteFileAction(path="new.py", content="", rationale="new module")
    txn = open_transaction(
        step_id=new_step_id(),
        parent_snapshot="d" * 40,
        worktree_path=Path("."),
        actions=(write_action,),
    )
    assert txn.step_id is not None


# RACT 0.4.0
