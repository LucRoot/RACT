from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import time
from typing import Dict, Callable

import pytest

from rootact.fixture_timeout_guard import execute_with_timeout


def test_execute_with_timeout_success(capsys):
    """A fixture that prints output completes without error."""

    def fixture_quick() -> None:
        print("quick ok")

    fixture_dict: Dict[str, Callable[[], None]] = {"quick": fixture_quick}
    execute_with_timeout(fixture_dict, capsys, timeout_seconds=0.5)


def test_execute_with_timeout_timeout(capsys):
    """A fixture that sleeps too long raises TimeoutError."""

    def slow_fixture() -> None:
        time.sleep(0.5)

    fixture_dict: Dict[str, Callable[[], None]] = {"slow": slow_fixture}
    with pytest.raises(TimeoutError) as excinfo:
        execute_with_timeout(fixture_dict, capsys, timeout_seconds=0.05)
    assert "slow" in str(excinfo.value)


def test_execute_with_timeout_no_output(capsys):
    """A silent fixture raises AssertionError about missing output."""

    def silent_fixture() -> None:
        pass

    fixture_dict: Dict[str, Callable[[], None]] = {"silent": silent_fixture}
    with pytest.raises(AssertionError) as excinfo:
        execute_with_timeout(fixture_dict, capsys, timeout_seconds=0.1)
    assert "silent" in str(excinfo.value)


def test_execute_with_timeout_propagates_assertion_error(capsys):
    """An AssertionError raised by a fixture propagates."""

    def failing_fixture() -> None:
        assert False, "intentional failure"

    fixture_dict: Dict[str, Callable[[], None]] = {"fail": failing_fixture}
    with pytest.raises(AssertionError) as excinfo:
        execute_with_timeout(fixture_dict, capsys, timeout_seconds=0.1)
    assert "intentional failure" in str(excinfo.value)


def test_execute_with_timeout_propagates_value_error(capsys):
    """A ValueError raised by a fixture propagates."""

    def value_error_fixture() -> None:
        raise ValueError("bad value")

    fixture_dict: Dict[str, Callable[[], None]] = {"ve": value_error_fixture}
    with pytest.raises(ValueError) as excinfo:
        execute_with_timeout(fixture_dict, capsys, timeout_seconds=0.1)
    assert "bad value" in str(excinfo.value)


def test_root_knot_is_sentinel():
    """Verify that _ROOT_KNOT is defined as a unique sentinel object."""
    import rootact.fixture_timeout_guard as mod

    assert hasattr(mod, "_ROOT_KNOT")
    assert isinstance(mod._ROOT_KNOT, object)
    assert mod._ROOT_KNOT is mod._ROOT_KNOT
