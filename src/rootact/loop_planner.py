# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""LoopPlanner breaks a high-level intent into a milestone backlog.

The planner reuses the configured management LM through the Harness/Planner path,
but it asks for milestones instead of code files. The resulting backlog is
persisted under ``.rootact/backlog.json`` and consumed by ``LoopController`` to
drive the Root-Knot-anchored recursion loop toward a concrete definition of done.
"""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rootact.codebase_historian import CodebaseHistorian
from rootact.harness import Harness
from rootact.rooted import Rooted


@dataclass(frozen=True)
class Milestone:
    """A single unit of work in the loop backlog."""

    id: str
    description: str
    acceptance: str
    status: str = "open"

    def __post_init__(self) -> None:
        if self.status not in {"open", "done", "blocked"}:
            raise ValueError(f"Invalid milestone status: {self.status}")


class LoopPlanner:
    """Generate and persist a milestone backlog for a looping intent."""

    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)
        self.project_dir = self.config_path.parent
        self.backlog_path = self.project_dir / ".rootact" / "backlog.json"

    def _planner_prompt(self, intent: str, historian_context: str = "") -> str:
        """Return the prompt that asks the management LM for milestones."""
        context_block = ""
        if historian_context:
            context_block = (
                "\n\nExisting symbols related to this intent (from the codebase "
                "historian):\n"
                f"{historian_context}\n"
                "If a milestone would create a new symbol that duplicates one of "
                "the above, explicitly state that the existing symbol will be "
                "reused, extended, or replaced. Avoid silent duplication."
            )
        return (
            "You are planning work for an agentic coding tool. Break the following "
            "intent into 3-8 concrete milestones. Each milestone must have a short "
            "description and clear acceptance criteria. Do not write code. Do not "
            "include implementation details. Output ONLY a JSON object with this "
            "shape:\n"
            "{\n"
            '  "milestones": [\n'
            "    {\n"
            '      "id": "m1",\n'
            '      "description": "Implement the core watcher loop",\n'
            '      "acceptance": "A function exists that blocks and returns on a filesystem event"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"Intent: {intent}"
            f"{context_block}"
        )

    def _historian_context(self, intent: str, k: int = 5) -> str:
        """Return a human-readable summary of existing symbols close to *intent*."""
        try:
            historian = CodebaseHistorian(self.project_dir).build()
        except Exception:  # noqa: BLE001
            return ""
        matches = historian.query(intent, k=k)
        if not matches:
            return ""
        lines: list[str] = []
        for match in matches:
            line = f"- {match.symbol_id} ({match.symbol_type})"
            if match.commit_message:
                line += f" — last commit: {match.commit_message[:60]}"
            lines.append(line)
        return "\n".join(lines)

    def _parse_json(self, text: str) -> Rooted[dict[str, Any]]:
        """Extract and validate the milestone JSON from model output."""
        # Look for a fenced JSON block first.
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        candidate = fence_match.group(1) if fence_match else text
        candidate = candidate.strip()
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            return Rooted(
                value=None,
                assumption="The management LM returns valid milestone JSON.",
                confidence=0.0,
                provenance=["loop_planner.parse_json"],
                error=f"Failed to parse milestone JSON: {exc}",
            )
        if "milestones" not in data or not isinstance(data["milestones"], list):
            return Rooted(
                value=None,
                assumption="The milestone JSON contains a 'milestones' list.",
                confidence=0.0,
                provenance=["loop_planner.parse_json"],
                error="Missing or invalid 'milestones' key.",
            )
        return Rooted(
            value=data,
            assumption="The management LM returns valid milestone JSON.",
            confidence=1.0,
            provenance=["loop_planner.parse_json"],
        )

    def _json_to_milestones(self, data: dict[str, Any]) -> Rooted[list[Milestone]]:
        """Convert parsed milestone JSON into Milestone objects."""
        milestones: list[Milestone] = []
        for idx, raw in enumerate(data["milestones"]):
            if not isinstance(raw, dict):
                return Rooted(
                    value=None,
                    assumption="Every milestone is a JSON object.",
                    confidence=0.0,
                    provenance=["loop_planner.json_to_milestones"],
                    error=f"Milestone at index {idx} is not an object.",
                )
            mid = str(raw.get("id", f"m{idx + 1}")).strip()
            description = str(raw.get("description", "")).strip()
            acceptance = str(raw.get("acceptance", "")).strip()
            if not mid or not description or not acceptance:
                return Rooted(
                    value=None,
                    assumption="Every milestone has id, description, and acceptance.",
                    confidence=0.0,
                    provenance=["loop_planner.json_to_milestones"],
                    error=f"Milestone {mid} is missing id, description, or acceptance.",
                )
            milestones.append(
                Milestone(
                    id=mid,
                    description=description,
                    acceptance=acceptance,
                    status="open",
                )
            )
        if not milestones:
            return Rooted(
                value=None,
                assumption="The management LM produces at least one milestone.",
                confidence=0.0,
                provenance=["loop_planner.json_to_milestones"],
                error="No milestones found.",
            )
        return Rooted(
            value=milestones,
            assumption="The management LM produces at least one milestone.",
            confidence=1.0,
            provenance=["loop_planner.json_to_milestones"],
        )

    def generate_backlog(self, intent: str) -> Rooted[list[Milestone]]:
        """Ask the configured management LM for a milestone backlog."""
        harness_rooted = Harness.from_config_path(self.config_path)
        if not harness_rooted.is_ok():
            return Rooted(
                value=None,
                assumption="The project configuration loads a usable Harness.",
                confidence=0.0,
                provenance=["loop_planner.generate_backlog"],
                error=f"Failed to load Harness: {harness_rooted.error}",
            )
        harness = harness_rooted.unwrap()
        historian_context = self._historian_context(intent)
        # Use the Manager directly, not the Planner, because the milestone prompt
        # asks for a "milestones" JSON object rather than a plan with steps. The
        # Planner would reject a response with no steps; we parse the raw result
        # ourselves below.
        plan_rooted = harness.manager.plan(
            self._planner_prompt(intent, historian_context)
        )
        if not plan_rooted.is_ok():
            return Rooted(
                value=None,
                assumption="The management LM can produce a milestone plan.",
                confidence=0.0,
                provenance=["loop_planner.generate_backlog"],
                error=f"Failed to generate milestones: {plan_rooted.error}",
            )
        plan = plan_rooted.unwrap()
        # If the model followed instructions, the plan assumption contains the
        # milestone JSON. Some managers put it in the first step action instead.
        candidate = plan.assumption
        if not candidate.strip():
            candidate = "\n".join(step.action for step in plan.steps if step.action)
        parsed = self._parse_json(candidate)
        if not parsed.is_ok():
            # Fallback: concatenate all step actions and try again.
            fallback_text = "\n".join(step.action for step in plan.steps if step.action)
            parsed = self._parse_json(fallback_text)
        if not parsed.is_ok():
            return Rooted(
                value=None,
                assumption="The milestone plan is parseable JSON.",
                confidence=0.0,
                provenance=["loop_planner.generate_backlog"],
                error=parsed.error,
            )
        return self._json_to_milestones(parsed.unwrap())

    def load(self) -> list[Milestone] | None:
        """Load a previously persisted backlog, if any."""
        if not self.backlog_path.is_file():
            return None
        try:
            data = json.loads(self.backlog_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict) or "milestones" not in data:
            return None
        milestones: list[Milestone] = []
        for raw in data["milestones"]:
            try:
                milestones.append(Milestone(**raw))
            except (TypeError, ValueError):
                continue
        return milestones if milestones else None

    def save(self, milestones: list[Milestone]) -> Path:
        """Persist the backlog to disk."""
        self.backlog_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "milestones": [asdict(milestone) for milestone in milestones],
        }
        self.backlog_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return self.backlog_path

    @staticmethod
    def next_open(milestones: list[Milestone]) -> Milestone | None:
        """Return the first open milestone, or None if all are done/blocked."""
        for milestone in milestones:
            if milestone.status == "open":
                return milestone
        return None

    @staticmethod
    def mark_done(milestones: list[Milestone], milestone_id: str) -> list[Milestone]:
        """Return a new milestone list with the given id marked done."""
        result: list[Milestone] = []
        found = False
        for milestone in milestones:
            if milestone.id == milestone_id:
                found = True
                result.append(
                    Milestone(
                        id=milestone.id,
                        description=milestone.description,
                        acceptance=milestone.acceptance,
                        status="done",
                    )
                )
            else:
                result.append(milestone)
        if not found:
            raise KeyError(f"Milestone not found: {milestone_id}")
        return result


# RACT 0.1.0 - Initial Public Release
