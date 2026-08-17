"""Tests for the typed MISSING sentinel."""

from __future__ import annotations

from ract.core.sentinels import MISSING, _MissingType


def test_missing_is_singleton() -> None:
    """Repeat construction returns the same object."""
    assert MISSING is _MissingType()
    assert _MissingType() is _MissingType()


def test_missing_is_falsy() -> None:
    """Falsy for guard-check ergonomics."""
    if MISSING:
        raise AssertionError("MISSING should be falsy")
    assert not MISSING
    assert bool(MISSING) is False


def test_missing_distinct_from_none() -> None:
    """MISSING is not None."""
    assert MISSING is not None
    assert MISSING != None  # noqa: E711 — intentional identity check


def test_missing_repr() -> None:
    """repr is the token 'MISSING'."""
    assert repr(MISSING) == "MISSING"


# RACT 0.4.1
