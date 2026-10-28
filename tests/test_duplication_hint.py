"""Package R: the duplication guard's error gets a hint that says what the user can do.

The message and the guard are harness gates (senior-only); the hint rendering is in the
lane. The guard's error text reaches the hint mapping; the category word "duplication" is
dropped by the advice filter, so the user used to get the provider-check hint.
"""

from __future__ import annotations

from ract.session_turn import hint_for

GUARD_ERROR = "Duplication guard blocked write: sub (src.calc) similarity=0.974; sub (src.calc) similarity=1.000"


def test_the_duplication_guard_error_gets_a_hint_about_the_change_not_the_provider():
    hint = hint_for(GUARD_ERROR)
    assert "check-providers" not in hint
    assert "doctor" not in hint
    assert "repeats" in hint or "already" in hint
    assert "ask" in hint.lower()


def test_the_duplication_hint_names_what_the_user_can_do():
    hint = hint_for(GUARD_ERROR).lower()
    assert "new" in hint and ("existing" in hint or "reuse" in hint)
