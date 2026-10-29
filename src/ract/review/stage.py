"""The review stage in a run: the setting, one review per changed step, the events (B-061c).

``review:`` in ract.yaml is ``off`` (the default), ``advisory`` or ``retry``
(ADR-0049 D14). With a review on, each plan step that wrote a file is read by
the REVIEWER after the write; the validated findings are shown below the turn
summary, labeled as the reviewer's. A review never changes whether a step is
done: the step's own result and the turn's VerificationResult decide that.

Token budget (D-093 amendment 3): a review is skipped before it starts when
fewer than ``MIN_TOKENS_TO_START`` tokens of the run's budget remain, and a
review that crosses the budget is stopped by the provider's own refusal; its
partial findings are dropped and the summary says "review stopped: token
budget".
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ract import run_token_budget, turn_context
from ract.review.findings import ReviewRequest, describe, validate
from ract.review.reviewer import review_step

MODES = ("off", "advisory", "retry")
MIN_TOKENS_TO_START = 20_000  # the MANAGER's default (D-093), reversible
# ADR-0049 D5: at most two retries per step; a review retry counts (B-061d).
MAX_STEP_RETRIES = 2
SAME_MODEL = "reviewed by the same model"


class ReviewConfigError(ValueError):
    """``review`` in ract.yaml is not off, advisory or retry."""


def mode(config: dict[str, Any]) -> str:
    """The review mode in *config*; ``off`` when the key is absent."""
    value = config.get("review", "off")
    if value is None or value is False:
        return "off"
    if value not in MODES:
        raise ReviewConfigError(
            f"review must be one of off, advisory or retry; got {value!r}"
        )
    return str(value)


def changed_lines(before: str | None, after: str) -> set[int]:
    """Line numbers of *after* that the change added or replaced (1-based)."""
    old = (before or "").splitlines()
    new = after.splitlines()
    lines: set[int] = set()
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            lines.update(range(j1 + 1, j2 + 1))
    return lines


def unified_diff(path: str, before: str | None, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}" if before is not None else "/dev/null",
            tofile=f"b/{path}",
        )
    )


def _remaining() -> int | None:
    budget = run_token_budget.current()
    return None if budget is None else budget.limit - budget.used


def review_written_step(
    complete: Callable[[list[dict[str, Any]]], Any],
    *,
    root: Path | str,
    n: int,
    goal: str,
    path: str,
    before: str | None,
    after: str,
    reviewer: str = SAME_MODEL,
) -> dict[str, Any]:
    """Review step *n*, report ``review.started`` and ``review.finished``, return the summary."""
    key = path.replace("\\", "/")
    base = {"n": n, "reviewer": reviewer, "path": key}
    remaining = _remaining()
    if remaining is not None and remaining < MIN_TOKENS_TO_START:
        summary = {
            **base,
            "status": "skipped",
            "note": f"review skipped: token budget ({remaining} tokens left)",
            "findings": [],
        }
        turn_context.report("review.finished", summary)
        return summary
    turn_context.report("review.started", base)
    request = ReviewRequest(
        step=n,
        goal=goal,
        acceptance=(),
        diff=unified_diff(key, before, after),
        verification="not run for this step; the harness checks the turn",
    )
    result = review_step(complete, request, root)
    if not result.is_ok():
        stopped = run_token_budget.STOP_PREFIX in (result.error or "")
        summary = {
            **base,
            "status": "stopped" if stopped else "failed",
            "note": "review stopped: token budget" if stopped else result.error,
            "findings": [],
        }
        turn_context.report("review.finished", summary)
        return summary
    checked = validate(root, result.unwrap(), {key: changed_lines(before, after)})
    summary = {
        **base,
        "status": "done",
        **describe(checked),
        "findings": [
            {
                "path": f.path,
                "line": f.line,
                "severity": f.severity,
                "claim": f.claim,
            }
            for f in checked.kept
        ],
    }
    turn_context.report("review.finished", summary)
    return summary
