from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.skills_registry import SkillRegistry


def test_register_and_load(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    registry.register("greet", "Hello, $name!")
    loaded = registry.load("greet")
    assert loaded["name"] == "greet"
    assert loaded["template"] == "Hello, $name!"
    assert loaded["tools"] == []


def test_register_with_tools(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    registry.register("search", "Find $query", tools=["web_search", "summarize"])
    loaded = registry.load("search")
    assert loaded["tools"] == ["web_search", "summarize"]


def test_list_skills_sorted(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    registry.register("b", "b-template")
    registry.register("a", "a-template")
    assert registry.list_skills() == ["a", "b"]


def test_load_missing_raises_keyerror(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    with pytest.raises(KeyError):
        registry.load("missing")


def test_invoke_renders_template(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    registry.register("greet", "Hello, $name!")
    rendered = registry.invoke("greet", {"name": "World"})
    assert rendered == "Hello, World!"


def test_invoke_missing_skill_raises_keyerror(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    with pytest.raises(KeyError):
        registry.invoke("missing", {})


def test_register_empty_name_raises(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    with pytest.raises(ValueError):
        registry.register("", "template")
