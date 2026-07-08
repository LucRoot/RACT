from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from pathlib import Path

import pytest

from rootact.preflight_validator import PreflightValidator

_ROOT_KNOT = object()


def test_missing_config_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    validator = PreflightValidator(missing)
    errors = validator.validate()
    assert len(errors) == 1
    assert errors[0]["field"] == "config_path"
    assert validator.is_valid() is False


def test_missing_project_section(tmp_path: Path) -> None:
    config = tmp_path / "rootact.yaml"
    config.write_text("providers: []\n")
    validator = PreflightValidator(config)
    errors = validator.validate()
    assert any(e["field"] == "project" for e in errors)
    assert validator.is_valid() is False


def test_missing_project_name(tmp_path: Path) -> None:
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  description: test\n")
    validator = PreflightValidator(config)
    errors = validator.validate()
    assert any(e["field"] == "project.name" for e in errors)
    assert validator.is_valid() is False


def test_valid_config(tmp_path: Path) -> None:
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: myproject\n")
    validator = PreflightValidator(config)
    assert validator.validate() == []
    assert validator.is_valid() is True


def test_invalid_yaml(tmp_path: Path) -> None:
    config = tmp_path / "rootact.yaml"
    config.write_text("project: [\n")
    validator = PreflightValidator(config)
    errors = validator.validate()
    assert len(errors) == 1
    assert errors[0]["field"] == "config"
    assert validator.is_valid() is False


def test_default_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: default\n")
    validator = PreflightValidator()
    assert validator.is_valid() is True
