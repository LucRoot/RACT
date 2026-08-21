"""v0.5.1 wiring module_07 -- enforce_g8 present in pre_commit.

Contract:
- ``enforce_g8`` returns :class:`EffortGateOutcome` with a non-empty
  ``rootknot_signature`` (AL-1 invariant).
- With no ``effort_estimate`` it emits ``laziness.skipped``
  (reason ``"no_effort_estimate"``) — Lens E AL-E-03 fix.
- With ``effort_estimate`` set but no ``final_diff`` it emits
  ``laziness.skipped`` (reason ``"no_final_diff"``).

Closure of Lens E audit AL-E-03 HIGH for G8.
"""

from __future__ import annotations

from unittest.mock import patch


def test_enforce_g8_importable_from_pre_commit():
    from ract.antilazy import pre_commit

    assert callable(pre_commit.enforce_g8)


def test_enforce_g8_importable_from_package():
    from ract import antilazy

    assert "enforce_g8" in antilazy.__all__
    assert callable(antilazy.enforce_g8)


def test_enforce_g8_skips_without_effort_estimate():
    from ract.antilazy.pre_commit import enforce_g8

    events: list = []

    def _fake_emit(name, payload, **kwargs):
        events.append((name, payload))

    with patch("ract.trace.sink.emit", _fake_emit):
        outcome = enforce_g8(final_diff=None, effort_estimate=None)

    assert outcome.passed is True
    assert outcome.skipped is True
    assert outcome.skip_reason == "no_effort_estimate"
    assert outcome.rootknot_signature.startswith("sha256:")
    assert (
        "laziness.skipped",
        {"gate_id": "G8", "reason": "no_effort_estimate"},
    ) in events


def test_enforce_g8_skips_when_final_diff_missing():
    from ract.antilazy.pre_commit import enforce_g8

    events: list = []

    def _fake_emit(name, payload, **kwargs):
        events.append((name, payload))

    with patch("ract.trace.sink.emit", _fake_emit):
        outcome = enforce_g8(final_diff=None, effort_estimate=object())

    assert outcome.passed is True
    assert outcome.skipped is True
    assert outcome.skip_reason == "no_final_diff"
    assert outcome.rootknot_signature.startswith("sha256:")
    assert (
        "laziness.skipped",
        {"gate_id": "G8", "reason": "no_final_diff"},
    ) in events
