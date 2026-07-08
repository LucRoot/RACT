# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass
from typing import List

from .manager import Plan, Step


@dataclass
class PlanBuilder:
    """Utility to construct a Plan from a textual description.

    This helper parses a simple human‑readable plan string and builds a
    ``Plan`` instance populated with ``Step`` objects.  It is deterministic,
    has no external dependencies, and is fully covered by unit tests.
    """

    def __init__(self, description: str) -> None:
        self.description = description
        self.steps: List[Step] = []

    def build(self) -> Plan:
        """Parse ``self.description`` and return a populated ``Plan``.

        The expected format is a comma‑separated list where each entry is
        ``<action>;<provider_hint>;<expected_artifact>``.  Example:
        ``"list files;fs;file_list.csv, download model;hf;model.pt"``.
        """
        raw_steps = [s.strip() for s in self.description.split(",") if s.strip()]
        steps = []
        for raw in raw_steps:
            parts = [p.strip() for p in raw.split(";")]
            if len(parts) != 3:
                raise ValueError(f"Invalid step format: {raw}")
            action, provider_hint, expected_artifact = parts
            steps.append(
                Step(
                    action=action,
                    provider_hint=provider_hint,
                    expected_artifact=expected_artifact,
                )
            )
        return Plan(
            assumption="Extracted from description", confidence=0.9, steps=steps
        )
