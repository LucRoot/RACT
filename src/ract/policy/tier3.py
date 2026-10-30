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
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NO_GRANT_HINT = (
    "`ract policy init --guided` proposes and signs a grant (or `ract policy sign` "
    "signs .ract/policy.yaml); ADR-0048 D3 says what a grant allows"
)


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
) -> Tier3Context:
    """The context for a step in *project*, with its grant read now."""
    from ract.policy.grant import load_grant

    project = Path(project)
    return Tier3Context(
        project=project, grant=load_grant(project), approve=approve, runner=runner
    )


__all__ = ["NO_GRANT_HINT", "Tier3Context", "bound", "current", "for_project"]
