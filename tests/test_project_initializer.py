# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for project template initialization."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.project_initializer import ProjectInitializer, list_templates


@pytest.mark.parametrize("template", ["python-package", "cli-tool"])
def test_initialize_creates_config_and_files(tmp_path, template):
    project_dir = tmp_path / "myapp"
    initializer = ProjectInitializer(project_dir, template, "local")
    result = initializer.initialize()

    assert result.project_dir == project_dir
    assert result.template == template
    assert result.provider == "local"

    config_path = project_dir / "rootact.yaml"
    assert config_path.is_file()
    config_text = config_path.read_text(encoding="utf-8")
    assert "project:" in config_text
    assert "myapp" in config_text
    assert "manager_provider: local" in config_text

    prompt_path = project_dir / "prompts" / "manager.txt"
    assert prompt_path.is_file()

    assert (project_dir / "src" / "myapp" / "__init__.py").is_file()
    assert (project_dir / "README.md").is_file()
    assert (project_dir / "pyproject.toml").is_file()


def test_initialize_refuses_overwrite(tmp_path):
    project_dir = tmp_path / "existing"
    project_dir.mkdir()
    (project_dir / "rootact.yaml").write_text("existing: true\n", encoding="utf-8")
    initializer = ProjectInitializer(project_dir, "python-package", "local")
    with pytest.raises(FileExistsError):
        initializer.initialize()


def test_list_templates_includes_builtins():
    templates = list_templates()
    assert "python-package" in templates
    assert "cli-tool" in templates


def test_initialize_installs_skill(tmp_path):
    project_dir = tmp_path / "pkgskill"
    initializer = ProjectInitializer(project_dir, "python-package", "local")
    result = initializer.initialize()
    skill_path = project_dir / "skills" / "python-package.json"
    assert skill_path.is_file()
    assert skill_path in result.files_written
