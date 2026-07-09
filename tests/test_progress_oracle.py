# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the Progress Oracle base."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from typing import Any

import pytest

from rootact.progress_oracle import ProgressOracle, ProgressVerdict
from rootact.rooted import Rooted


class StubOracle(ProgressOracle):
    def __init__(self, verdict: ProgressVerdict) -> None:
        self.verdict = verdict

    def evaluate(self, context: dict[str, Any]) -> Rooted[ProgressVerdict]:
        return Rooted(
            value=self.verdict,
            assumption="stub",
            confidence=1.0,
            provenance=["stub"],
        )


def test_progress_verdict_validates_verdict():
    with pytest.raises(ValueError):
        ProgressVerdict(verdict="invalid", reason="no", confidence=1.0)


def test_progress_verdict_validates_confidence():
    with pytest.raises(ValueError):
        ProgressVerdict(verdict="proceed", reason="no", confidence=1.5)


def test_stub_oracle_returns_verdict():
    verdict = ProgressVerdict(verdict="proceed", reason="ok", confidence=1.0)
    oracle = StubOracle(verdict)
    result = oracle.evaluate({})
    assert result.is_ok()
    assert result.unwrap() == verdict


# RACT 0.1.1 - Trust and Tooling
