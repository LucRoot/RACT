# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Built-in skill library for RACT.

RACT ships with a small set of ready-to-use skills so users feel value on day
one. Each skill is a JSON file under ``builtin_skills/`` containing a
string.Template that the harness prepends to the intent. The templates carry
RACT's signature quirks (Root Knot markers, Rooted results, explicit
assumptions) so every built-in skill perpetuates the author's style.
"""

import json
import shutil
from pathlib import Path
from typing import Any

from rootact.skills_registry import SkillRegistry


class BuiltinSkillLibrary:
    """Expose and install built-in RACT skills into a project's skill directory."""

    def __init__(self) -> None:
        self.builtin_dir = Path(__file__).parent / "builtin_skills"

    def list_skills(self) -> list[dict[str, Any]]:
        """Return metadata for every built-in skill."""
        skills: list[dict[str, Any]] = []
        for path in sorted(self.builtin_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            skills.append(
                {"name": data["name"], "description": data.get("description", "")}
            )
        return skills

    def install(self, name: str, registry: SkillRegistry) -> Path:
        """Copy a built-in skill into the project's skill registry."""
        source = self.builtin_dir / f"{name}.json"
        if not source.is_file():
            raise KeyError(f"Built-in skill not found: {name}")
        target = registry.skills_dir / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    def install_all(self, registry: SkillRegistry) -> list[str]:
        """Install every built-in skill into the project's skill registry."""
        installed: list[str] = []
        for path in sorted(self.builtin_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.install(data["name"], registry)
            installed.append(data["name"])
        return installed
