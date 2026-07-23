"""Tests for the RACT skill marketplace."""

from __future__ import annotations


import json
import subprocess
import sys
from pathlib import Path

from ract.skill_marketplace import SkillMarketplace
from ract.skills_registry import SkillRegistry


def test_marketplace_list_local_catalog(tmp_path: Path) -> None:
    """Listing reads a local catalog file."""
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "name": "demo",
                        "description": "A demo skill",
                        "url": "http://example.com/demo.json",
                        "author": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    marketplace = SkillMarketplace(catalog)
    skills = marketplace.list_skills()
    assert len(skills) == 1
    assert skills[0]["name"] == "demo"


def test_marketplace_install_from_local_file(tmp_path: Path) -> None:
    """Install downloads a local skill file and saves it to the registry."""
    skill = {"name": "demo", "description": "demo", "template": "hello", "tools": []}
    skill_path = tmp_path / "demo.json"
    skill_path.write_text(json.dumps(skill), encoding="utf-8")

    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "name": "demo",
                        "description": "A demo skill",
                        "url": str(skill_path),
                        "author": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    registry = SkillRegistry(tmp_path / "project")
    marketplace = SkillMarketplace(catalog)
    installed = marketplace.install("demo", registry)
    assert installed.is_file()
    loaded = registry.load("demo")
    assert loaded["template"] == "hello"


def test_marketplace_install_missing_skill_raises(tmp_path: Path) -> None:
    """Installing a skill not in the catalog raises KeyError."""
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"skills": []}), encoding="utf-8")
    registry = SkillRegistry(tmp_path / "project")
    marketplace = SkillMarketplace(catalog)
    try:
        marketplace.install("missing", registry)
    except KeyError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("expected KeyError")


def test_cli_skills_marketplace_list(tmp_path: Path) -> None:
    """CLI lists marketplace skills from a local catalog."""
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "name": "demo",
                        "description": "A demo skill",
                        "url": "http://example.com/demo.json",
                        "author": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "skills",
            "marketplace",
            "list",
            "--catalog",
            str(catalog),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "demo" in result.stdout


def test_cli_skills_marketplace_install(tmp_path: Path) -> None:
    """CLI installs a marketplace skill into a project directory."""
    skill = {"name": "demo", "description": "demo", "template": "hello", "tools": []}
    skill_path = tmp_path / "demo.json"
    skill_path.write_text(json.dumps(skill), encoding="utf-8")

    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "name": "demo",
                        "description": "A demo skill",
                        "url": str(skill_path),
                        "author": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    project_dir = tmp_path / "project"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "skills",
            "marketplace",
            "install",
            "--project-dir",
            str(project_dir),
            "--name",
            "demo",
            "--catalog",
            str(catalog),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "installed marketplace skill 'demo'" in result.stdout
    assert (project_dir / "skills" / "demo.json").is_file()


# RACT 0.1.1 - Trust and tooling
