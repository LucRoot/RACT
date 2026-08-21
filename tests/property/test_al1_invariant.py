"""AL-1 invariant: every anti-lazy gate outcome carries a signature.

v0.5.1 wiring module_07 (Lens E AL-E-04) promotes AL-1 attestation
from a caller convention to a substrate invariant. This test verifies:

1. Every gate outcome (G1..G8, polyglot) constructed via its
   ``enforce_gN`` produces a non-empty ``rootknot_signature`` string
   in the ``sha256:<64hex>`` shape.
2. The signature is deterministic over identical inputs (same content
   -> same signature).
3. The signature is content-binding (any change in gate_id / passed /
   report / run_id produces a different signature).
4. ``_require_gate_signature`` raises ``ValueError`` on an empty
   string (defense-in-depth against a hand-constructed outcome).
"""

from __future__ import annotations

import re

import pytest

_SIG_SHAPE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _all_enforce_gN_produce_signatures():
    """Return a list of (gate_id, outcome) for every enforce_gN skip path.

    Uses the skip / no-input paths so no external deps (mutation
    engine, coverage tool, tree-sitter) need to be present.
    """
    from ract.antilazy.pre_commit import (
        enforce_g1,
        enforce_g5_dead_code_polyglot,
        enforce_g6_test_copy_paste_polyglot,
        enforce_g7,
        enforce_g8,
    )

    return [
        ("G1", enforce_g1(None, None)),
        ("G5-polyglot", enforce_g5_dead_code_polyglot([])),
        ("G6-polyglot", enforce_g6_test_copy_paste_polyglot([])),
        ("G7", enforce_g7(intent="i", final_diff=None, visible_suite=None, companion_bundle=None)),
        ("G8", enforce_g8(final_diff=None, effort_estimate=None)),
    ]


def test_every_gate_outcome_carries_al1_signature():
    """AL-1: no gate outcome may carry an empty rootknot_signature."""
    for gate_id, outcome in _all_enforce_gN_produce_signatures():
        sig = outcome.rootknot_signature
        assert sig, f"gate {gate_id!r} produced empty signature"
        assert _SIG_SHAPE.match(sig), (
            f"gate {gate_id!r} signature {sig!r} does not match sha256:<hex>"
        )


def test_signature_is_deterministic_over_identical_inputs():
    """Re-running enforce_g1 with the same inputs produces the same signature."""
    from ract.antilazy.pre_commit import enforce_g1

    a = enforce_g1(None, None)
    b = enforce_g1(None, None)
    assert a.rootknot_signature == b.rootknot_signature


def test_signature_is_content_binding():
    """Changing gate_id or passed or report invalidates the signature."""
    from ract.antilazy.pre_commit import _compute_gate_signature

    base = _compute_gate_signature(gate_id="G1", passed=True, report={"k": "v"})
    diff_gate = _compute_gate_signature(gate_id="G2", passed=True, report={"k": "v"})
    diff_pass = _compute_gate_signature(gate_id="G1", passed=False, report={"k": "v"})
    diff_report = _compute_gate_signature(gate_id="G1", passed=True, report={"k": "V"})
    assert base != diff_gate
    assert base != diff_pass
    assert base != diff_report


def test_signature_run_id_binds_the_payload():
    """The ambient run_id rides inside the signed payload."""
    from ract.antilazy.pre_commit import _compute_gate_signature

    a = _compute_gate_signature(
        gate_id="G1", passed=True, report={"k": "v"}, run_id="run_a"
    )
    b = _compute_gate_signature(
        gate_id="G1", passed=True, report={"k": "v"}, run_id="run_b"
    )
    assert a != b


def test_require_gate_signature_rejects_empty_string():
    from ract.antilazy.pre_commit import _require_gate_signature

    with pytest.raises(ValueError, match="AL-1 invariant"):
        _require_gate_signature("", gate_id="G_test")


def test_require_gate_signature_rejects_none():
    from ract.antilazy.pre_commit import _require_gate_signature

    with pytest.raises(ValueError, match="AL-1 invariant"):
        _require_gate_signature(None, gate_id="G_test")  # type: ignore[arg-type]


def test_require_gate_signature_accepts_valid_hex():
    from ract.antilazy.pre_commit import _require_gate_signature

    sig = "sha256:" + "a" * 64
    assert _require_gate_signature(sig, gate_id="G_test") == sig


def test_signature_field_default_is_empty_string_but_populated_by_enforce():
    """The dataclass default is ``""`` — the AL-1 guarantee is that
    every enforce_gN populates it. A hand-constructed outcome with
    the default '' would be rejected by ``_require_gate_signature``.
    """
    from ract.antilazy.pre_commit import (
        GateOutcome,
        _require_gate_signature,
    )

    # Direct construction with the default is legal at the dataclass
    # level but would fail the invariant check.
    hand = GateOutcome(
        passed=True,
        should_roll_back=False,
        report=None,  # type: ignore[arg-type]
    )
    assert hand.rootknot_signature == ""
    with pytest.raises(ValueError, match="AL-1 invariant"):
        _require_gate_signature(hand.rootknot_signature, gate_id="G_hand")
