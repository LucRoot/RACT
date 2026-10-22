from __future__ import annotations

_SENTINEL = object()


import json
import re
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Union

from ract.manager import Plan, Step


_SKILL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class _SentinelType:
    """Sentinel for default arguments."""


_SENTINEL_DEFAULT: _SentinelType = _SentinelType()

_SKILLS_DIR_NAME = "skills"


class SkillRegistry:
    """
    A registry for RACT skills that stores templates and tool wrappers as JSON files.
    Skills are persisted under a base directory and can be loaded, listed, and invoked.
    """

    def __init__(
        self, base_dir: Union[str, Path, _SentinelType] = _SENTINEL_DEFAULT
    ) -> None:
        if isinstance(base_dir, _SentinelType):
            resolved: Union[str, Path] = Path.cwd()
        else:
            resolved = base_dir
        self.base_dir = Path(resolved)
        self.skills_dir = self.base_dir / _SKILLS_DIR_NAME
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def skill_file(self, name: str) -> Path:
        """Path of the skill's JSON file; refuses names that are not one file name.

        LR:: The name comes from ract.yaml (``skill:``) and the CLI, and was
        joined straight into the path, so ``../../config`` loaded any .json
        file and rendered its ``template`` into the plan prompt (S-018b).
        """
        if not _SKILL_NAME_RE.fullmatch(name or "") or ".." in name:
            raise ValueError(
                f"skill name {name!r} must be letters, digits, '.', '_' or '-', "
                "starting with a letter or digit"
            )
        return self.skills_dir / f"{name}.json"

    def register(
        self,
        name: str,
        template: str,
        tools: List[str] | None | _SentinelType = _SENTINEL_DEFAULT,
    ) -> None:
        """
        Register a new skill by writing its metadata to a JSON file.

        Parameters
        ----------
        name: str
            Unique identifier for the skill; must be a valid filename component.
        template: str
            The raw template string that may contain $variable references.
        tools: list[str] | None
            Optional list of tool names associated with the skill.
        """
        skill_path = self.skill_file(name)
        if isinstance(tools, _SentinelType):
            resolved_tools: Optional[List[str]] = None
        else:
            resolved_tools = tools
        skill_data = {
            "name": name,
            "template": template,
            "tools": resolved_tools or [],
        }
        with skill_path.open("w", encoding="utf-8") as fp:
            json.dump(skill_data, fp, indent=2)

    def load(self, name: str) -> Dict[str, Any]:
        """
        Load a previously registered skill.

        Parameters
        ----------
        name: str
            The exact name used during registration.

        Returns
        -------
        dict
            The skill metadata (name, template, tools).

        Raises
        ------
        KeyError
            If no skill with the given name exists.
        """
        skill_path = self.skill_file(name)
        if not skill_path.is_file():
            raise KeyError(f"Skill '{name}' not found")
        with skill_path.open("r", encoding="utf-8") as fp:
            return json.load(fp)

    def list_skills(self) -> List[str]:
        """
        Return a sorted list of all registered skill names.
        """
        if not self.skills_dir.exists():
            return []
        return sorted(p.stem for p in self.skills_dir.glob("*.json"))

    def invoke(self, name: str, context: Dict[str, Any]) -> str:
        """
        Render the skill's template with the provided context.

        Parameters
        ----------
        name: str
            The skill to invoke.
        context: dict
            Mapping of variable names to values for substitution.

        Returns
        -------
        str
            The rendered template.

        Raises
        ------
        KeyError
            If the skill does not exist.
        ValueError
            If the template contains a variable that is not present in ``context``.
        """
        skill = self.load(name)
        template_str = skill["template"]
        tmpl = Template(template_str)
        return tmpl.safe_substitute(context)


_plan = Plan(
    assumption="RACT must provide a SkillsRegistry that persists skills as JSON and supports register, load, list_skills, and invoke",
    confidence=0.95,
    steps=[
        Step(
            action="create SkillRegistry class with required methods",
            provider_hint="internal",
            expected_artifact="src/ract/skills_registry.py",
        )
    ],
)
# RACT 0.1.1 - Trust and tooling
