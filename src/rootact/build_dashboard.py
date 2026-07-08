# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"


class _RootKnotType:
    """Sentinel for Root Knot default arguments."""


_ROOT_KNOT: _RootKnotType = _RootKnotType()

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Step:
    action: str
    provider_hint: str
    expected_artifact: str


@dataclass(frozen=True)
class Plan:
    assumption: str
    confidence: float
    steps: List[Step]


class BuildDashboard:
    def __init__(self, outcomes: List[dict] | _RootKnotType = _ROOT_KNOT):
        if isinstance(outcomes, _RootKnotType):
            resolved: List[dict] = []
        else:
            resolved = outcomes
        self.outcomes = resolved

    def render(self) -> str:
        total = len(self.outcomes)
        successes = sum(1 for o in self.outcomes if o.get("status") == "success")
        failures = total - successes
        success_rate = (successes / total * 100) if total else 0.0
        recent_failure = next(
            (
                o.get("error", "")
                for o in reversed(self.outcomes)
                if o.get("status") == "failure"
            ),
            "",
        )
        return (
            f"Build Dashboard\n"
            f"------------\n"
            f"Total builds: {total}\n"
            f"Success rate: {success_rate:.1f}%\n"
            f"Failures: {failures}\n"
            f"Recent failure: {recent_failure or 'none'}\n"
        )


# RACT 0.1.0 - Initial Public Release
