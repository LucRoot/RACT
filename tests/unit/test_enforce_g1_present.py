"""v0.5.1 wiring module_07 -- enforce_g1 present in pre_commit.

Contract:
- ``ract.antilazy.pre_commit.enforce_g1`` exists and returns a
  :class:`HoldoutGateOutcome`.
- With no dual suite the outcome is ``passed=True, skipped=True`` and
  a non-empty ``rootknot_signature`` (AL-1 invariant, module_07 item 4).
- With a dual suite whose visible half passes and held-out half fails
  the outcome carries ``blocked_on_holdout_gap=True`` and
  ``should_roll_back=True``.
- The re-export at ``ract.antilazy`` mirrors the pre_commit surface.

Closure of Lens E audit AL-E-03 HIGH for G1.
"""

from __future__ import annotations

import pytest


def test_enforce_g1_importable_from_pre_commit():
    """The canonical dispatcher lives on ``pre_commit`` (parity with G2-G6)."""
    from ract.antilazy import pre_commit

    assert hasattr(pre_commit, "enforce_g1")
    assert callable(pre_commit.enforce_g1)


def test_enforce_g1_importable_from_package():
    """The re-export at :mod:`ract.antilazy` covers G1 too (module_07 item 3)."""
    from ract import antilazy

    assert "enforce_g1" in antilazy.__all__
    assert callable(antilazy.enforce_g1)
    assert "HoldoutGateOutcome" in antilazy.__all__


def test_enforce_g1_skips_gracefully_without_dual_suite():
    """Legacy single-suite runs must not be artificially failed."""
    from ract.antilazy.pre_commit import enforce_g1

    outcome = enforce_g1(None, None)
    assert outcome.passed is True
    assert outcome.skipped is True
    assert outcome.should_roll_back is False
    assert outcome.rootknot_signature
    assert outcome.rootknot_signature.startswith("sha256:")


def test_enforce_g1_carries_al1_signature():
    """Every enforce_g1 outcome carries an AL-1 attestation."""
    from ract.antilazy.pre_commit import enforce_g1

    outcome = enforce_g1(None, None)
    # AL-1: field is non-empty and content-derived (changing inputs
    # produces a different signature; changing NOTHING produces the
    # same signature).
    same_again = enforce_g1(None, None)
    assert outcome.rootknot_signature == same_again.rootknot_signature
    assert len(outcome.rootknot_signature) > 10


def test_enforce_g1_blocked_on_holdout_gap():
    """A dual suite whose visible passes but held-out fails triggers the gap."""
    pytest.importorskip("ract.antilazy.holdout")
    # Duck-typed stand-in — the enforce_g1 code path only reads
    # ``.visible`` / ``.held_out`` / ``.required()`` shape.
    from unittest.mock import MagicMock

    from ract.antilazy.pre_commit import enforce_g1

    class _AlwaysOk:
        ok = True

    class _NeverOk:
        ok = False

    def _make_predicate(ok: bool):
        pred = MagicMock()
        pred.id = b"\x00" * 16
        pred.evaluate = MagicMock(return_value=_AlwaysOk() if ok else _NeverOk())
        return pred

    visible = MagicMock()
    visible.required = MagicMock(return_value=[_make_predicate(True)])
    held_out = MagicMock()
    held_out.required = MagicMock(return_value=[_make_predicate(False)])

    dual = MagicMock()
    dual.visible = visible
    dual.held_out = held_out
    dual.holdout_kind = "real"
    dual.intent_id = b"\x00" * 16
    dual.held_out_digest = "0" * 64

    class _Snap:
        files = {}
        timestamp = 0.0
        metadata = {}

    outcome = enforce_g1(dual, _Snap())
    assert outcome.passed is False
    assert outcome.blocked_on_holdout_gap is True
    assert outcome.should_roll_back is True
    assert outcome.rootknot_signature.startswith("sha256:")
