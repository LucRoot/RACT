"""A hard token budget per run (B-065).

``token_budget`` in ``ract.yaml`` is a positive whole number, or absent or
null for no budget. A run counts the input and output tokens that the
providers report for its requests. When the next request would start with
the count at or over the budget, the request is not sent and the turn stops
with a plain message.

The count comes from the usage that each response reports (the same numbers
the egress ledger records). A response with no usage is not counted, and the
run says once that the budget is not enforced for that provider. Nothing is
estimated from bytes.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

KEY = "token_budget"
STOP_PREFIX = "stopped: this run used"


class BudgetConfigError(ValueError):
    """``token_budget`` is set to something other than a positive whole number."""


def parse(value: object) -> int | None:
    """The budget for a config value: a positive int, or None when off."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BudgetConfigError(
            f"{KEY} must be a positive whole number, or left out to turn it off; "
            f"got {value!r}"
        )
    return value


@dataclass
class Budget:
    limit: int
    used: int = 0
    unreported: set[str] = field(default_factory=set)

    def exhausted(self) -> bool:
        return self.used >= self.limit

    def stop_message(self) -> str:
        return (
            f"{STOP_PREFIX} {self.used} tokens; {KEY} is {self.limit}. "
            f"Raise {KEY} in ract.yaml, or split the task."
        )

    def add_usage(self, usage: Any, provider: str) -> None:
        """Count one response's usage. A response with none is noted once."""
        total = _total(usage)
        if total is None:
            if provider not in self.unreported:
                self.unreported.add(provider)
                print(
                    f"[ract] {KEY} is set, but {provider} reports no token counts, "
                    "so it is not enforced",
                    flush=True,
                )
            return
        self.used += total


def _total(usage: Any) -> int | None:
    if not isinstance(usage, dict):
        return None
    tin = usage.get("prompt_tokens", usage.get("input_tokens"))
    tout = usage.get("completion_tokens", usage.get("output_tokens"))
    if not isinstance(tin, int) or not isinstance(tout, int):
        return None
    return tin + tout


_active: Budget | None = None


def current() -> Budget | None:
    """The budget of the run in progress, or None."""
    return _active


@contextmanager
def run_budget(limit: int | None) -> Iterator[Budget | None]:
    """Count the requests made inside the block against *limit*."""
    global _active
    previous = _active
    _active = Budget(limit) if limit is not None else None
    try:
        yield _active
    finally:
        _active = previous
