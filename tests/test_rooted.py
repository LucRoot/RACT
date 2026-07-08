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


# RACT 0.1.0 - Initial Public Release
