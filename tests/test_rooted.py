__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the Rooted type."""

from rootact.rooted import (
    DEFAULT_CONFIDENCE_FLOOR,
    Rooted,
    root_assert,
    root_bind,
    root_map,
)


def test_rooted_ok_when_value_and_confidence_are_good():
    rooted = Rooted(value=42, assumption="The answer is known.", confidence=1.0)
    assert rooted.is_ok()
    assert rooted.unwrap() == 42


def test_rooted_not_ok_when_confidence_below_floor():
    rooted = Rooted(
        value=42, assumption="Shaky ground.", confidence=DEFAULT_CONFIDENCE_FLOOR - 0.1
    )
    assert not rooted.is_ok()


def test_rooted_not_ok_when_error_set():
    rooted = Rooted(
        value=42, assumption="Looks fine.", confidence=1.0, error="but actually not"
    )
    assert not rooted.is_ok()


def test_root_bind_propagates_failure():
    failure = Rooted(value=None, assumption="x", confidence=0.0, error="boom")
    result = root_bind(
        failure, lambda v: Rooted(value=v * 2, assumption="doubled", confidence=1.0)
    )
    assert not result.is_ok()
    assert "boom" in (result.error or "")


def test_root_bind_transforms_ok_value():
    ok = Rooted(value=5, assumption="five", confidence=1.0)
    result = root_bind(
        ok, lambda v: Rooted(value=v * 2, assumption="doubled", confidence=1.0)
    )
    assert result.is_ok()
    assert result.unwrap() == 10


def test_root_map_transforms_value():
    ok = Rooted(value=3, assumption="three", confidence=1.0)
    result = root_map(ok, lambda v: v * v)
    assert result.is_ok()
    assert result.unwrap() == 9


def test_root_assert_passes():
    result = root_assert(2 + 2 == 4, "Arithmetic works.", score=1.0)
    assert result.is_ok()


def test_root_assert_fails():
    result = root_assert(2 + 2 == 5, "Arithmetic works.", score=1.0)
    assert not result.is_ok()


def test_rooted_not_ok_when_value_is_none():
    rooted = Rooted(value=None, assumption="Missing.", confidence=1.0)
    assert not rooted.is_ok()


def test_rooted_ok_at_exact_confidence_floor():
    rooted = Rooted(
        value=42, assumption="At the floor.", confidence=DEFAULT_CONFIDENCE_FLOOR
    )
    assert rooted.is_ok()


def test_rooted_with_step_appends_provenance():
    rooted = Rooted(value=1, assumption="x", confidence=1.0, provenance=["a"])
    stepped = rooted.with_step("b")
    assert stepped.provenance == ["a", "b"]
    assert stepped.value == rooted.value


def test_rooted_unwrap_raises_when_value_is_none():
    rooted = Rooted(value=None, assumption="x", confidence=1.0, error="missing")
    try:
        rooted.unwrap()
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("unwrap should raise when value is None")


def test_root_bind_adds_step_to_provenance():
    ok = Rooted(value=5, assumption="five", confidence=1.0, provenance=["start"])
    result = root_bind(
        ok,
        lambda v: Rooted(value=v * 2, assumption="doubled", confidence=1.0),
        step="double",
    )
    assert result.is_ok()
    assert result.provenance == ["start", "double"]


def test_root_bind_failure_preserves_assumption_and_confidence():
    failure = Rooted(value=None, assumption="x", confidence=0.25, error="boom")
    result = root_bind(
        failure, lambda v: Rooted(value=v * 2, assumption="doubled", confidence=1.0)
    )
    assert not result.is_ok()
    assert result.assumption == "x"
    assert result.confidence == 0.25
    assert "boom" in (result.error or "")


def test_root_map_adds_step_to_provenance():
    ok = Rooted(value=3, assumption="three", confidence=1.0, provenance=["start"])
    result = root_map(ok, lambda v: v * v, step="square")
    assert result.is_ok()
    assert result.provenance == ["start", "square"]


def test_root_map_failure_preserves_hint_and_provider():
    failure = Rooted(
        value=None,
        assumption="x",
        confidence=0.5,
        error="boom",
        hint="try again",
        provider="local",
    )
    result = root_map(failure, lambda v: v * v)
    assert not result.is_ok()
    assert result.hint == "try again"
    assert result.provider == "local"


def test_root_assert_uses_default_score():
    result = root_assert(1 == 1, "Trivial.")
    assert result.is_ok()
    assert result.confidence == 1.0


# RACT 0.1.1 - Trust and Tooling
