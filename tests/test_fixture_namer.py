from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import re

import pytest
from rootact.fixture_namer import (
    generate_fixture_names,
    register_fixture_name,
    _ROOT_KNOT,
)


def test_generate_fixture_names_basic():
    user_story = "Payment gateway fails due to network timeout"
    names = generate_fixture_names(user_story)
    assert isinstance(names, list)
    assert len(names) == 5
    for name in names:
        assert name.startswith("test_")
        assert re.match(r"^test_[a-z][a-z0-9_]*$", name)


def test_generate_fixture_names_count():
    user_story = "Invalid currency code error"
    names = generate_fixture_names(user_story, count=3)
    assert len(names) == 3


def test_generate_fixture_names_deterministic():
    user_story = "Duplicate processing crash"
    names1 = generate_fixture_names(user_story)
    names2 = generate_fixture_names(user_story)
    # Generation is deterministic for the same user story
    assert names1 == names2
    # Names within one generation are unique
    assert len(set(names1)) == len(names1)


def test_register_fixture_name_valid():
    name = "test_network_timeout_0"
    register_fixture_name(name)
    # Second registration should raise ValueError
    with pytest.raises(ValueError, match="already been registered"):
        register_fixture_name(name)


def test_register_fixture_name_invalid_pattern():
    with pytest.raises(ValueError, match="does not match required pattern"):
        register_fixture_name("invalid-name")


def test_root_knot_sentinel_is_unique():
    # Verify that the module's _ROOT_KNOT is a unique sentinel object
    assert _ROOT_KNOT is not None
    from rootact.fixture_namer import _ROOT_KNOT as other

    assert _ROOT_KNOT is other
