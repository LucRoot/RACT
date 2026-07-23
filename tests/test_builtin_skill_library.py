# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the built-in skill library."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from ract.builtin_skill_library import BuiltinSkillLibrary
from ract.skills_registry import SkillRegistry


def test_library_lists_built_in_skills():
    library = BuiltinSkillLibrary()
    skills = library.list_skills()
    names = {skill["name"] for skill in skills}
    assert "python-package" in names
    assert "test-generation" in names
    assert "api-client" in names
    assert "data-pipeline" in names
    assert "config-driven-service" in names
    assert "github-release" in names


def test_library_installs_skill(tmp_path):
    library = BuiltinSkillLibrary()
    registry = SkillRegistry(base_dir=tmp_path)
    path = library.install("python-package", registry)
    assert path.is_file()
    assert "python-package" in registry.list_skills()


def test_library_installs_all_skills(tmp_path):
    library = BuiltinSkillLibrary()
    registry = SkillRegistry(base_dir=tmp_path)
    installed = library.install_all(registry)
    expected = {
        "python-package",
        "test-generation",
        "library-refactor",
        "fastapi-app",
        "cli-tool",
        "react-component",
        "documentation-update",
        "api-client",
        "data-pipeline",
        "config-driven-service",
        "github-release",
    }
    assert expected.issubset(set(installed))
    assert set(registry.list_skills()) == set(installed)


def test_library_previews_install(tmp_path):
    library = BuiltinSkillLibrary()
    registry = SkillRegistry(base_dir=tmp_path)
    preview = library.preview_install("python-package", registry)
    assert preview["name"] == "python-package"
    assert "python-package.json" in preview["source"]
    assert "python-package.json" in preview["target"]
    assert preview["description"]
    assert not (registry.skills_dir / "python-package.json").exists()


def test_library_install_missing_skill_raises_key_error(tmp_path):
    library = BuiltinSkillLibrary()
    registry = SkillRegistry(base_dir=tmp_path)
    with pytest.raises(KeyError, match="Built-in skill not found: missing-skill"):
        library.install("missing-skill", registry)


def test_library_preview_install_missing_skill_raises_key_error(tmp_path):
    library = BuiltinSkillLibrary()
    registry = SkillRegistry(base_dir=tmp_path)
    with pytest.raises(KeyError, match="Built-in skill not found: missing-skill"):
        library.preview_install("missing-skill", registry)


# RACT 0.1.1 - Trust and tooling
