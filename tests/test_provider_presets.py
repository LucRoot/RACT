# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for provider presets."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.provider_presets import get_preset, list_presets


def test_list_presets_includes_local():
    assert "local" in list_presets()


def test_list_presets_includes_cheap_frontier():
    for name in ("zai", "moonshot", "openrouter"):
        assert name in list_presets()


def test_get_preset_returns_deep_copy():
    first = get_preset("local")
    second = get_preset("local")
    assert first is not second
    assert first == second


def test_get_preset_unknown_raises():
    with pytest.raises(KeyError):
        get_preset("nonexistent")


def test_preset_has_required_keys():
    preset = get_preset("openai")
    assert "project" in preset
    assert "manager_provider" in preset
    assert "providers" in preset
    assert "prompts_dir" in preset
    assert "context_budget_tokens" in preset


# RACT 0.1.0 - Initial Public Release
