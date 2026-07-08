# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from rootact.manager import Step


class ProjectDocument:
    """A user-configurable project document that stores sections and metadata."""

    REQUIRED_SECTIONS = {"goal", "plan"}
    DEFAULT_SECTIONS: Dict[str, Any] = {"notes": []}

    def __init__(
        self,
        sections: Optional[Dict[str, Any]] = None,
        goal: Optional[str] = None,
        plan: Optional[List[Step]] = None,
    ):
        self._sections: Dict[str, Any] = {}
        self._sections.update(self.DEFAULT_SECTIONS)
        if sections is not None:
            self._sections.update(sections)
        if goal is not None:
            self._sections["goal"] = goal
        if plan is not None:
            self._sections["plan"] = plan
        else:
            self._sections.setdefault("plan", [])
        for section in self.REQUIRED_SECTIONS:
            if section not in self._sections:
                raise ValueError(f"Required section '{section}' is missing")

    @classmethod
    def load(cls, path: str) -> "ProjectDocument":
        """Load a project document from a JSON file."""
        file_path = Path(path)
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        goal = data.get("goal")
        plan_data = data.get("plan", [])
        plan_steps = [
            Step(
                action=s["action"],
                provider_hint=s["provider_hint"],
                expected_artifact=s["expected_artifact"],
            )
            for s in plan_data
        ]
        # Preserve any extra sections (e.g., notes, custom) from the JSON file.
        extra_sections = {k: v for k, v in data.items() if k not in {"goal", "plan"}}
        return cls(sections=extra_sections, goal=goal, plan=plan_steps)

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        """Recursively serialize Step instances and lists to JSON-safe shapes."""
        if isinstance(value, Step):
            return {
                "action": value.action,
                "provider_hint": value.provider_hint,
                "expected_artifact": value.expected_artifact,
            }
        if isinstance(value, list):
            return [ProjectDocument._serialize_value(item) for item in value]
        if isinstance(value, dict):
            return {k: ProjectDocument._serialize_value(v) for k, v in value.items()}
        return value

    def save(self, path: str) -> None:
        """Save the project document to a JSON file."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {}
        goal = self._sections.get("goal")
        if goal is not None:
            data["goal"] = goal
        plan = self._sections.get("plan", [])
        data["plan"] = [
            {
                "action": step.action,
                "provider_hint": step.provider_hint,
                "expected_artifact": step.expected_artifact,
            }
            for step in plan
        ]
        # Merge any additional sections for serialization.
        for section_name, content in self._sections.items():
            if section_name not in {"goal", "plan"}:
                data[section_name] = self._serialize_value(content)
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def sections(self) -> Dict[str, Any]:
        """Return the current sections mapping."""
        return self._sections

    def __repr__(self) -> str:
        return f"ProjectDocument(goal={self._sections.get('goal')}, sections={list(self._sections.keys())})"
