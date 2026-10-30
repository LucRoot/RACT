"""The tier-3 context of a step: the grant, who answers, and how commands run (ADR-0048 D6).

LR:: A tier-3 tool runs only inside a step that has this context, set by
the executor from the operator's project (its ``.ract/policy.yaml``, never
the step worktree's copy). The order of checks is D6's: no grant that holds
refuses, naming ``ract policy init --guided``, ``ract policy sign`` and the
ADR; the matcher's hard floor and deny rules refuse, naming the rule; in
``ask`` mode every command asks. The answer comes from ``approve``, the
operator at the terminal; with nobody to ask (headless, ``--yolo``) there
is no approver and every tier-3 call is refused. No model output reaches
``approve``.

The grant is pinned (D3, G-216 W1): the session's pin, or the first load's
when there is none, is compared at the step's start and again at each
command. A difference suspends the context: every later tier-3 call is
refused with ``SUSPENDED_REASON`` until the operator confirms the new grant
with ``/permissions resume``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

NO_GRANT_HINT = (
    "`ract policy init --guided` proposes and signs a grant (or `ract policy sign` "
    "signs .ract/policy.yaml); ADR-0048 D3 says what a grant allows"
)
SUSPENDED_REASON = (
    "suspended: policy changed. .ract/policy.yaml or its signature changed during "
    "this session; tier 3 stays off until you confirm with /permissions resume"
)
RESUME_HINT = "/permissions resume shows what changed and asks you to confirm it"


def suspend(state: Any) -> Any:
    """*state* as a grant that no longer holds because its files changed."""
    return replace(state, status="suspended", reason=SUSPENDED_REASON, policy=None)


@dataclass
class Tier3Context:
    """What a step's tier-3 calls need, set for the step by the executor."""

    project: Path
    grant: Any  # GrantState
    approve: Callable[[dict[str, Any]], bool] | None
    runner: Any = None
    mode: str = "ask"
    model_written: set[str] = field(default_factory=set)
    runs: list[Any] = field(default_factory=list)
    # The pin every check compares with: the session's, else the first load's.
    expected_pin: str | None = None
    # B-113: the session's "for this session" answers (allowlist.SessionApprovals).
    session_approvals: Any = None

    def check_pin(self) -> None:
        """Suspend this context when the grant's files changed since the pin (W1)."""
        from ract.policy.grant import pin_digest

        if self.grant.status == "suspended" or self.expected_pin is None:
            return
        try:
            now = pin_digest(self.project)
        except OSError as exc:
            print(f"[tier3] the grant was not re-read: {exc}", flush=True)
            now = ""
        if now != self.expected_pin:
            self.grant = suspend(self.grant)


_current: ContextVar[Tier3Context | None] = ContextVar("ract_tier3", default=None)


def current() -> Tier3Context | None:
    return _current.get()


@contextmanager
def bound(context: Tier3Context | None) -> Iterator[Tier3Context | None]:
    """Set *context* for the calls inside; the previous one comes back after."""
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)


def for_project(
    project: Path | str,
    approve: Callable[[dict[str, Any]], bool] | None,
    runner: Any = None,
    expected_pin: str | None = None,
    *,
    mode: str = "ask",
    session_approvals: Any = None,
) -> Tier3Context:
    """The context for a step in *project*, with its grant read now.

    With *expected_pin* (the session's), a grant whose files differ from the
    pinned ones is suspended; without it, this load's pin is the pin.
    """
    from ract.policy.grant import load_grant

    project = Path(project)
    grant = load_grant(project)
    if expected_pin is not None and grant.pin != expected_pin:
        grant = suspend(grant)
    # B-113: the session asks for a mode; the grant's max_mode caps it.
    allowed = getattr(getattr(grant, "policy", None), "max_mode", "ask")
    return Tier3Context(
        project=project,
        grant=grant,
        approve=approve,
        runner=runner,
        mode="allowlist" if mode == "allowlist" and allowed == "allowlist" else "ask",
        expected_pin=expected_pin if expected_pin is not None else grant.pin,
        session_approvals=session_approvals,
    )


__all__ = [
    "NO_GRANT_HINT",
    "RESUME_HINT",
    "SUSPENDED_REASON",
    "Tier3Context",
    "bound",
    "current",
    "for_project",
    "suspend",
]
