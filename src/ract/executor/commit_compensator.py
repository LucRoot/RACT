"""Rollback compensators for git commits made inside a SubstrateLoop.

SUBSTRATE §7 hardening: a loop that commits mid-run cannot revert past
the commit today (the substrate rolls back the worktree changes but
the branch already carries the sha). External review §7 (and per the
source-doc §5.4) asks the substrate to install a compensator effect
whenever a commit lands INSIDE a loop, so a subsequent unsuccessful
disposal (T-cause other than T1 SUCCESS) can undo the commit.

Contract:

- ``CommitCompensator`` is a value: the branch, the sha BEFORE the
  commit, the sha AFTER, the operation shape (``"soft"`` or
  ``"hard"``), and whether the commit was PUSHED. If pushed, the
  compensator refuses to run -- push crosses the substrate boundary
  and any revert must be an explicit follow-up commit, not a silent
  ``reset --hard``.
- ``CompensatorStack`` accumulates compensators in commit order. On
  a successful disposal (T1) the stack is DISCARDED. On any other
  disposal the stack is DRAINED in LIFO order (undo the most recent
  first). Each compensator emits a ``compensator.applied`` event
  when it runs and a ``compensator.refused`` event when it skips due
  to the push boundary.
- The stack is per-loop, not per-step. A step's own worktree rollback
  is handled by the worktree layer; the compensator layer is for
  commits that ADVANCED the loop's HEAD (via ``_fast_forward_head``
  in ``ract.executor.loop``).

Design intent: the compensator is a first-class event, not a hidden
side-effect. Operators reading the event log see EXACTLY which
commits the loop rolled and which ones it refused to touch because
they had already been pushed.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CompensatorPushedError(RuntimeError):
    """Raised when a compensator is asked to run against a pushed commit.

    Push crosses the substrate boundary (remote refs are outside the
    loop's authority); the substrate refuses to force-move a pushed
    ref via reset --hard because that would silently rewrite shared
    history. Caller (loop controller) treats this as "compensator
    refused; log and continue".
    """


class CompensatorAlreadyApplied(RuntimeError):
    """Raised when the stack tries to apply the same compensator twice."""


# ---------------------------------------------------------------------------
# Value
# ---------------------------------------------------------------------------


@dataclass
class CommitCompensator:
    """One compensator: revert instructions for one commit.

    ``repo_root`` is the git repo the commit landed in.
    ``branch`` is the branch that received the commit.
    ``sha_before`` is the sha the branch pointed at BEFORE the commit.
    ``sha_after`` is the sha of the commit itself (the compensator
    checks HEAD matches this before running, so an unrelated commit
    that landed between compensator install and drain trips a soft
    refusal rather than accidentally reverting the wrong thing).
    ``mode`` is ``"soft"`` (``git reset --soft <sha_before>`` --
    preserves working tree, discards the commit only) or ``"hard"``
    (``git reset --hard <sha_before>`` -- discards working-tree
    changes too).
    ``pushed`` is set at install time via
    ``check_pushed(repo_root, sha_after)``. ``True`` locks the
    compensator OFF -- ``apply`` raises ``CompensatorPushedError``.
    """

    repo_root: Path
    branch: str
    sha_before: str
    sha_after: str
    mode: str = "soft"
    pushed: bool = False
    applied: bool = False

    def apply(self) -> bool:
        """Run the compensator.

        Returns True on successful revert, False on soft-refusal
        (HEAD moved past ``sha_after``; unsafe to reset). Raises
        ``CompensatorPushedError`` when ``pushed=True``.
        Raises ``CompensatorAlreadyApplied`` on double apply.
        """
        if self.applied:
            raise CompensatorAlreadyApplied(
                f"compensator for {self.sha_after[:12]} on {self.branch} "
                "already applied"
            )
        if self.pushed:
            raise CompensatorPushedError(
                f"commit {self.sha_after[:12]} on {self.branch} was pushed; "
                "compensator refuses to force-move a remote ref"
            )
        # Confirm HEAD is still at sha_after. If a downstream commit
        # landed since install, we refuse -- the revert would discard
        # the downstream commit too, which is beyond the compensator's
        # authority.
        current = _resolve_head(self.repo_root)
        if current != self.sha_after:
            _LOG.warning(
                "compensator on %s: HEAD %s != installed %s; downstream "
                "commit(s) landed since install; refusing to reset",
                self.branch,
                current[:12] if current else "?",
                self.sha_after[:12],
            )
            self.applied = True  # Mark applied so we do not retry.
            return False

        flag = "--soft" if self.mode == "soft" else "--hard"
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo_root),
                "reset",
                flag,
                self.sha_before,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.applied = True
        if result.returncode != 0:
            _LOG.warning(
                "compensator reset failed on %s: %s",
                self.branch,
                result.stderr.strip() or result.stdout.strip(),
            )
            return False
        return True


# ---------------------------------------------------------------------------
# Stack
# ---------------------------------------------------------------------------


@dataclass
class CompensatorStack:
    """Ordered stack of compensators for one loop.

    ``install`` adds a compensator (loop appends after each successful
    commit that advanced its HEAD). ``drain`` LIFO-applies every
    compensator on unsuccessful disposal (T2/T3/T4/T5/T6/T7/T8/T9).
    ``discard`` clears the stack on successful disposal (T1).

    Every install + drain emits an event via the injected sink so the
    event log shows exactly which compensators fired and which
    refused.
    """

    event_sink: Callable[[str, dict[str, Any]], None] | None = None
    _stack: list[CommitCompensator] = field(default_factory=list)

    def install(self, comp: CommitCompensator) -> None:
        self._stack.append(comp)
        self._emit(
            "compensator.installed",
            {
                "branch": comp.branch,
                "sha_before": comp.sha_before,
                "sha_after": comp.sha_after,
                "mode": comp.mode,
                "pushed": comp.pushed,
            },
        )

    def discard(self, reason: str = "T1_SUCCESS") -> None:
        """Discard every compensator without applying.

        Called by the loop controller on T1 (success). Emits one
        event summarising the drain-skip so the audit trail shows
        the discard was intentional.
        """
        count = len(self._stack)
        self._stack.clear()
        self._emit(
            "compensator.discarded",
            {"reason": reason, "count": count},
        )

    def drain(self, reason: str) -> list[tuple[CommitCompensator, str]]:
        """Apply every compensator in LIFO order; return per-compensator outcomes.

        Each outcome is ``(compensator, status)`` where status is one
        of ``"applied"``, ``"refused_pushed"``, ``"soft_refused"``,
        ``"failed"``.
        """
        outcomes: list[tuple[CommitCompensator, str]] = []
        while self._stack:
            comp = self._stack.pop()
            try:
                ok = comp.apply()
                if ok:
                    status = "applied"
                else:
                    status = "soft_refused"
            except CompensatorPushedError:
                status = "refused_pushed"
            except CompensatorAlreadyApplied:
                status = "already_applied"
            except Exception as exc:  # noqa: BLE001 -- never fail drain
                _LOG.warning("compensator drain error: %s", exc)
                status = "failed"
            self._emit(
                (
                    "compensator.applied"
                    if status == "applied"
                    else "compensator.refused"
                ),
                {
                    "branch": comp.branch,
                    "sha_before": comp.sha_before,
                    "sha_after": comp.sha_after,
                    "mode": comp.mode,
                    "status": status,
                    "drain_reason": reason,
                },
            )
            outcomes.append((comp, status))
        return outcomes

    def pending(self) -> tuple[CommitCompensator, ...]:
        return tuple(self._stack)

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        sink = self.event_sink or _default_event_sink
        try:
            sink(kind, payload)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _resolve_head(repo_root: Path) -> str:
    """Return HEAD sha for ``repo_root`` or ``""`` on failure."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def check_pushed(repo_root: Path, sha: str) -> bool:
    """Return True when ``sha`` is reachable from any remote ref.

    Uses ``git branch -r --contains <sha>``. A non-empty result means
    a remote ref carries the commit; the compensator locks OFF. When
    the repo has no remotes at all, this always returns False -- the
    compensator is free to run.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "branch", "-r", "--contains", sha],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # Uncertain -- be safe and refuse to run the compensator.
        # An operator can inspect the branch and manually reset.
        return True
    return bool(result.stdout.strip())


def build_compensator(
    repo_root: Path,
    *,
    branch: str,
    sha_before: str,
    sha_after: str,
    mode: str = "soft",
) -> CommitCompensator:
    """Factory: build a compensator + probe push state at install time."""
    if mode not in ("soft", "hard"):
        raise ValueError(f"mode must be 'soft' or 'hard'; got {mode!r}")
    pushed = check_pushed(Path(repo_root), sha_after)
    return CommitCompensator(
        repo_root=Path(repo_root),
        branch=branch,
        sha_before=sha_before,
        sha_after=sha_after,
        mode=mode,
        pushed=pushed,
    )


def _default_event_sink(kind: str, payload: dict[str, Any]) -> None:
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(kind, payload)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "CommitCompensator",
    "CompensatorAlreadyApplied",
    "CompensatorPushedError",
    "CompensatorStack",
    "build_compensator",
    "check_pushed",
]


# RACT 0.5.1
