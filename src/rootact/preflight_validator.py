from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml

from rootact.manager import Plan, Step


class _RootKnotType:
    """Sentinel for Root Knot default arguments."""


_ROOT_KNOT: _RootKnotType = _RootKnotType()


@dataclass
class PreflightValidator:
    """
    Validate a RootAct configuration before starting work.
    """

    config_path: Path

    def __init__(self, config_path: Path | str | _RootKnotType = _ROOT_KNOT) -> None:
        if isinstance(config_path, _RootKnotType):
            resolved: Path | str = "rootact.yaml"
        else:
            resolved = config_path
        self.config_path = Path(resolved)

    def validate(self) -> List[Dict[str, Any]]:
        """Return a list of errors; empty list means valid."""
        errors: List[Dict[str, Any]] = []

        if not self.config_path.exists():
            errors.append(
                {
                    "field": "config_path",
                    "message": f"config file not found: {self.config_path}",
                }
            )
            return errors

        try:
            raw = self.config_path.read_text(encoding="utf-8")
            config = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            errors.append({"field": "config", "message": f"invalid YAML: {exc}"})
            return errors

        if not isinstance(config, dict):
            errors.append(
                {"field": "config", "message": "config must be a YAML mapping"}
            )
            return errors

        if "project" not in config:
            errors.append(
                {"field": "project", "message": "missing required section 'project'"}
            )
        elif not isinstance(config["project"], dict):
            errors.append(
                {"field": "project", "message": "'project' must be a mapping"}
            )
        elif "name" not in config["project"]:
            errors.append(
                {
                    "field": "project.name",
                    "message": "missing required field 'project.name'",
                }
            )

        return errors

    def is_valid(self) -> bool:
        """Return True if validation produced no errors."""
        return len(self.validate()) == 0


_plan = Plan(
    assumption="preflight_validator must check that rootact.yaml exists and contains required fields",
    confidence=0.95,
    steps=[
        Step(
            action="create PreflightValidator class with validate and is_valid methods",
            provider_hint="internal",
            expected_artifact="src/rootact/preflight_validator.py",
        )
    ],
)
# RACT 0.1.1 - Trust and Tooling
