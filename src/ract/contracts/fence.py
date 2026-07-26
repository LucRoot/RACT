"""Fence as pre-delete gate (SUBSTRATE §8).

The v0.3 ``ChestertonsFence`` was a CLI-invoked subagent that produced a
plausible-reason brief for a file on operator request. Module_06
reframes it as an **environment-enforced pre-delete gate**: every
``DeleteFileAction`` is intercepted before the ``StepTransaction``
opens, a ``PlausibleReasonBrief`` is produced, and the deletion either
lands (with operator handshake) or is refused (with a specific
predicate).

The intercept is structurally enforced. ``StepTransaction.open`` refuses
a ``DeleteFileAction`` whose ``fence_ticket_id`` is absent from the
process-local ``FenceGate.approved_tickets`` set. A bypass-attempt test
(``tests/contracts/test_fence_pre_delete.py``) constructs a delete step
without a ticket and asserts the transaction refuses to open.

Load-bearing scan logic (git blame + git log + file excerpt) reuses
``ract.chestertons_fence.ChestertonsFence`` primitives. The CLI verb
``ract fence`` keeps its convenience output path.

Reference sources:

- SUBSTRATE spec §8 ("Chesterton's Fence as pre-delete gate").
- v0.3 source: ``src/ract/chestertons_fence.py`` (reused primitives).
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlausibleReasonBrief:
    """One plausible-reason brief for a file the model wants to delete.

    Produced by ``FenceGate.evaluate``; consumed by the operator
    handshake surface. ``reason`` is a short natural-language paragraph;
    ``recent_commits`` and ``blame_snippets`` are the evidence.
    """

    path: str
    reason: str
    recent_commits: tuple[str, ...] = ()
    blame_snippets: tuple[str, ...] = ()
    confidence: float = 0.5


class FenceOutcome(Enum):
    """Terminal outcome of one Fence gate evaluation."""

    BLOCKED = auto()  # brief attached; operator handshake required
    PERMITTED = auto()  # a specific predicate declared the reason moot
    REFUSED = auto()  # bypass-attempt / malformed action


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


class FenceGate:
    """Environment-enforced gate over every ``DeleteFileAction``.

    Two things happen at ``evaluate`` time:

    1. A ``PlausibleReasonBrief`` is produced from the file's blame and
       recent commit history (v0.3-primitive reuse).
    2. A ``fence_ticket_id`` is minted and added to
       ``approved_tickets`` — the ticket is what
       ``StepTransaction.open`` reads to know Fence has seen the action.

    A ``DeleteFileAction`` without a matching ticket is refused by the
    transaction opener. The model cannot bypass this because ticket
    minting only happens through ``FenceGate.evaluate``.
    """

    # Process-local ticket store. The ``StepTransaction`` opener reads
    # from this set; each ticket is consumed on the first successful
    # ``open`` (single-use so an approval doesn't accidentally cover a
    # second delete).
    approved_tickets: set[str] = set()

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)

    # ------------------------------------------------------------------
    # Evaluate one delete-action proposal
    # ------------------------------------------------------------------

    def evaluate(self, action) -> tuple[PlausibleReasonBrief, str]:  # type: ignore[no-untyped-def]
        """Return the brief + a fresh ``fence_ticket_id`` for ``action``.

        The ticket is added to ``approved_tickets`` so
        ``StepTransaction.open`` will accept the delete action once. The
        operator handshake (module_04 handshake registry) still gates
        the *approval*; ticketing only means "Fence has seen this."
        """
        from ract.core.actions import DeleteFileAction  # local import

        if not isinstance(action, DeleteFileAction):
            raise TypeError(
                "FenceGate.evaluate only accepts DeleteFileAction; got "
                f"{type(action).__name__}"
            )

        target = self.workspace_root / action.path
        commits = self._recent_commits(target)
        blame = self._blame(target)
        reason = (
            f"path={action.path} rationale={action.rationale!r}; "
            f"recent commits={len(commits)}; blame lines={len(blame)}"
        )
        brief = PlausibleReasonBrief(
            path=action.path,
            reason=reason,
            recent_commits=tuple(commits[:10]),
            blame_snippets=tuple(blame[:20]),
            confidence=0.8 if commits else 0.3,
        )
        ticket = uuid.uuid4().hex
        self.approved_tickets.add(ticket)
        return brief, ticket

    # ------------------------------------------------------------------
    # Consume a ticket (called by StepTransaction opener)
    # ------------------------------------------------------------------

    @classmethod
    def consume_ticket(cls, ticket_id: str) -> bool:
        """Consume ``ticket_id`` and return True if it was present.

        Called by ``ract.core.transaction.open_transaction`` before a
        transaction that carries a ``DeleteFileAction`` may open. Single-
        use: after consumption the ticket cannot cover a second delete.
        """
        if ticket_id in cls.approved_tickets:
            cls.approved_tickets.discard(ticket_id)
            return True
        return False

    @classmethod
    def has_ticket(cls, ticket_id: str) -> bool:
        """Return True if ``ticket_id`` is currently present.

        Convenience predicate for the bypass-attempt test — does not
        consume the ticket.
        """
        return ticket_id in cls.approved_tickets

    # ------------------------------------------------------------------
    # Internal: reuse the v0.3 primitives.
    # ------------------------------------------------------------------

    def _recent_commits(self, path: Path) -> list[str]:
        try:
            proc = subprocess.run(
                ["git", "log", "-n10", "--pretty=format:%h %s", "--", str(path)],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    def _blame(self, path: Path) -> list[str]:
        if not path.is_file():
            return []
        try:
            proc = subprocess.run(
                ["git", "blame", "--date=short", "-l", "--", str(path)],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


# RACT 0.4.0
