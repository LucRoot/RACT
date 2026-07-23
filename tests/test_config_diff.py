# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RACT config diff tool."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from ract.config_diff import diff_configs


def test_diff_configs_detects_added_removed_and_changed(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text(
        "project:\n  name: old\nprovider:\n  name: local\n",
        encoding="utf-8",
    )
    b.write_text(
        "project:\n  name: new\nprovider:\n  name: local\nnovelty:\n  budget: 0.1\n",
        encoding="utf-8",
    )

    result = diff_configs(a, b)
    assert result["added"] == {"novelty.budget": "0.1"}
    assert result["removed"] == {}
    assert result["changed"] == {"project.name": {"before": "old", "after": "new"}}
    assert "provider.name" in result["unchanged"]


def test_diff_configs_detects_removed_key(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text("project:\n  name: test\ndebug: true\n", encoding="utf-8")
    b.write_text("project:\n  name: test\n", encoding="utf-8")

    result = diff_configs(a, b)
    assert result["removed"] == {"debug": "True"}
    assert result["added"] == {}
    assert result["changed"] == {}
