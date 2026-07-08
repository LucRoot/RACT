from __future__ import annotations

_ROOT_KNOT = object()

import pytest
from pathlib import Path

from rootact.edge_case_validator import validate_user_story


def test_validate_user_story_empty_string_returns_false():
    assert validate_user_story("") is False


def test_validate_user_story_invalid_type_raises_typeerror():
    with pytest.raises(TypeError):
        validate_user_story(123)


def test_validate_user_story_longer_than_five_hundred_chars_returns_false():
    long_input = "a" * 501
    assert validate_user_story(long_input) is False


def test_validate_user_story_no_alnum_characters_returns_false():
    input_with_only_symbols = "!!!@@@###$$$"
    assert validate_user_story(input_with_only_symbols) is False


def test_validate_user_story_valid_input_returns_true():
    valid_input = "Invalid currency code causes timeout."
    assert validate_user_story(valid_input) is True


def test_root_author_marker_present_in_source_file():
    source_path = Path("src/rootact/edge_case_validator.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content


# RACT 0.1.0 - Initial Public Release
