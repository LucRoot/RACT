# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Configuration-driven project templates for RACT.

Scaffolds a new project from a named template and a provider preset. This turns
``rootact init --template python-package --provider local`` into a working,
documented, tested starter project instead of a bare ``rootact.yaml``.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

import yaml

from rootact.builtin_skill_library import BuiltinSkillLibrary
from rootact.harness import _default_manager_prompt_path
from rootact.provider_presets import get_preset
from rootact.skills_registry import SkillRegistry


@dataclass
class InitializationResult:
    """Result of a project initialization."""

    project_dir: Path
    template: str
    provider: str
    files_written: list[Path]


class ProjectInitializer:
    """Initialize a new RACT project from a template and provider preset.

    LR:: Templates live under ``src/rootact/project_templates/`` as JSON files.
    Each template declares the files to create and an optional built-in skill to
    install. The initializer refuses to overwrite an existing ``rootact.yaml`` so
    it cannot accidentally clobber a real project.
    """

    def __init__(
        self, project_dir: Path, template_name: str, provider_name: str
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.template_name = template_name
        self.provider_name = provider_name
        self.templates_dir = Path(__file__).parent / "project_templates"

    def initialize(self) -> InitializationResult:
        """Create the project directory, config, template files, and prompt."""
        self.project_dir.mkdir(parents=True, exist_ok=True)
        config_path = self.project_dir / "rootact.yaml"
        if config_path.is_file():
            raise FileExistsError(
                f"{config_path} already exists; refusing to overwrite an existing project."
            )

        template = self._load_template()
        config = self._build_config()
        config_path.write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )

        files_written: list[Path] = [config_path]
        files_written.extend(self._write_template_files(template))
        files_written.extend(self._write_default_prompt())
        files_written.extend(self._install_skill(template.get("skill")))

        return InitializationResult(
            project_dir=self.project_dir,
            template=self.template_name,
            provider=self.provider_name,
            files_written=files_written,
        )

    def _load_template(self) -> dict[str, Any]:
        path = self.templates_dir / f"{self.template_name}.json"
        if not path.is_file():
            available = sorted(p.stem for p in self.templates_dir.glob("*.json"))
            raise KeyError(
                f"Unknown template: {self.template_name}. Available: {available}"
            )
        return json.loads(path.read_text(encoding="utf-8"))

    def _build_config(self) -> dict[str, Any]:
        config = get_preset(self.provider_name)
        config.setdefault("project", {})
        config["project"]["name"] = self.project_dir.name
        return config

    def _write_template_files(self, template: dict[str, Any]) -> list[Path]:
        written: list[Path] = []
        project_name = self.project_dir.name
        subs = {
            "project_name": project_name,
            "provider_name": self.provider_name,
            "root_author": "Dr. Lucas Root, Ph.D.",
            "ract_name": "RACT",
        }
        for rel_path, raw_content in template.get("files", {}).items():
            rendered_path = Template(rel_path).safe_substitute(subs)
            rendered_content = Template(raw_content).safe_substitute(subs)
            target = self.project_dir / rendered_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file():
                continue
            target.write_text(rendered_content, encoding="utf-8")
            written.append(target)
        return written

    def _write_default_prompt(self) -> list[Path]:
        prompts_dir = self.project_dir / "prompts"
        prompt_file = prompts_dir / "manager.txt"
        if prompt_file.is_file():
            return []
        prompts_dir.mkdir(parents=True, exist_ok=True)
        default_prompt = _default_manager_prompt_path()
        if default_prompt.is_file():
            shutil.copy2(default_prompt, prompt_file)
            return [prompt_file]
        return []

    def _install_skill(self, skill_name: str | None) -> list[Path]:
        if not skill_name:
            return []
        library = BuiltinSkillLibrary()
        registry = SkillRegistry(self.project_dir)
        try:
            path = library.install(skill_name, registry)
        except KeyError:
            return []
        return [path]


def list_templates() -> list[str]:
    """Return available template names."""
    templates_dir = Path(__file__).parent / "project_templates"
    return sorted(p.stem for p in templates_dir.glob("*.json"))


# RACT 0.1.0 - Initial Public Release
