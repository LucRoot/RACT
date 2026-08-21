"""v0.5.1 wiring module_07 -- enforce_g7 present in pre_commit.

Contract:
- ``enforce_g7`` returns :class:`CompanionGateOutcome` with a non-empty
  ``rootknot_signature`` (AL-1 invariant).
- With no companion_bundle it emits ``laziness.skipped`` (reason
  ``"no_companion_bundle"``) and returns ``passed=True, skipped=True``.
- With ``companion_bundle`` set but no ``final_diff`` it emits
  ``laziness.skipped`` (reason ``"no_final_diff"``). Neither returns
  silently — Lens E AL-E-03 fix.

Closure of Lens E audit AL-E-03 HIGH for G7.
"""

from __future__ import annotations

from unittest.mock import patch


def test_enforce_g7_importable_from_pre_commit():
    from ract.antilazy import pre_commit

    assert callable(pre_commit.enforce_g7)


def test_enforce_g7_importable_from_package():
    from ract import antilazy

    assert "enforce_g7" in antilazy.__all__
    assert callable(antilazy.enforce_g7)


def test_enforce_g7_skips_without_companion_bundle_and_emits():
    """The Lens E AL-E-03 silent-noop fix: ``laziness.skipped`` fires."""
    from ract.antilazy.pre_commit import enforce_g7

    events: list = []

    def _fake_emit(name, payload, **kwargs):
        events.append((name, payload))

    with patch("ract.trace.sink.emit", _fake_emit):
        outcome = enforce_g7(
            intent="i",
            final_diff=None,
            visible_suite=None,
            companion_bundle=None,
        )

    assert outcome.passed is True
    assert outcome.skipped is True
    assert outcome.skip_reason == "no_companion_bundle"
    assert outcome.rootknot_signature.startswith("sha256:")
    assert ("laziness.skipped", {"gate_id": "G7", "reason": "no_companion_bundle"}) in events


def test_enforce_g7_skips_when_final_diff_missing_and_emits():
    from ract.antilazy.pre_commit import enforce_g7

    events: list = []

    def _fake_emit(name, payload, **kwargs):
        events.append((name, payload))

    # Any truthy stand-in for the companion bundle triggers the second
    # branch; the enforce_g7 code path returns before touching it when
    # final_diff / visible_suite are missing.
    with patch("ract.trace.sink.emit", _fake_emit):
        outcome = enforce_g7(
            intent="i",
            final_diff=None,
            visible_suite=object(),
            companion_bundle=object(),
        )

    assert outcome.passed is True
    assert outcome.skipped is True
    assert outcome.skip_reason == "no_final_diff"
    assert outcome.rootknot_signature.startswith("sha256:")
    assert ("laziness.skipped", {"gate_id": "G7", "reason": "no_final_diff"}) in events
