# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Novelty budget anti-rot guard.

AI agents create new files, packages, and symbols because there is no cost to
doing so. The novelty budget makes novelty a scarce resource. Each session starts
with a fixed number of "surprise points"; novel choices consume them. When the
budget is exhausted, further novel choices are blocked unless the operator
explicitly overrides.

LR:: This is not a creativity limiter. It is an inattention tax. The agent must
notice when an existing symbol could be extended instead of inventing a new one.
"""

import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rootact.gravity_scorer import GravityScorer


@dataclass(frozen=True)
class NoveltyCharge:
    """A single novelty charge against the budget."""

    category: str
    points: int
    artifact: str
    detail: str


@dataclass
class NoveltyBudgetState:
    """Persisted novelty-budget state for a session."""

    budget: int
    spent: int
    charges: list[dict[str, Any]]


class NoveltyBudget:
    """Track and enforce novelty spending per session."""

    DEFAULT_BUDGET = 15
    CHARGES = {
        "new_file": 3,
        "new_public_symbol": 6,
        "new_dependency": 8,
        "gravity_deviation": 2,
    }

    def __init__(
        self,
        project_dir: Path | str,
        *,
        budget: int | None = None,
        gravity_top_k: int = 10,
        state_path: Path | str | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.budget = max(budget or self.DEFAULT_BUDGET, 0)
        self.gravity_top_k = max(gravity_top_k, 1)
        self._state_path = (
            Path(state_path)
            if state_path is not None
            else self.project_dir / ".rootact" / "novelty_budget.json"
        )
        self._state = self._load_state()

    def _load_state(self) -> NoveltyBudgetState:
        """Load persisted state or initialize a fresh budget."""
        if self._state_path.is_file():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                return NoveltyBudgetState(
                    budget=int(data.get("budget", self.budget)),
                    spent=int(data.get("spent", 0)),
                    charges=list(data.get("charges", [])),
                )
            except (json.JSONDecodeError, ValueError, OSError):
                pass
        return NoveltyBudgetState(budget=self.budget, spent=0, charges=[])

    def save(self) -> None:
        """Persist the current budget state."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(
                {
                    "budget": self._state.budget,
                    "spent": self._state.spent,
                    "charges": self._state.charges,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def reset(self) -> None:
        """Reset the budget to a fresh state."""
        self._state = NoveltyBudgetState(budget=self.budget, spent=0, charges=[])
        self.save()

    @property
    def remaining(self) -> int:
        return max(self._state.budget - self._state.spent, 0)

    def assess(
        self,
        expected_artifact: str,
        content: str,
    ) -> list[NoveltyCharge]:
        """Return novelty charges for writing *content* to *expected_artifact*.

        Charges are computed by comparing the proposed content with the existing
        file on disk. New files, new public symbols, new dependencies, and
        deviations from high-gravity symbols all cost points.
        """
        if not expected_artifact:
            return []
        target = self.project_dir / expected_artifact
        old_text = ""
        if target.is_file():
            try:
                old_text = target.read_text(encoding="utf-8")
            except OSError:
                old_text = ""

        charges: list[NoveltyCharge] = []
        is_new_file = not target.is_file()
        if is_new_file:
            charges.append(
                NoveltyCharge(
                    category="new_file",
                    points=self.CHARGES["new_file"],
                    artifact=expected_artifact,
                    detail="file does not exist",
                )
            )

        if expected_artifact.endswith(".py"):
            charges.extend(
                self._assess_python_novelty(
                    expected_artifact, old_text, content, is_new_file
                )
            )

        charges.extend(
            self._assess_dependency_novelty(expected_artifact, old_text, content)
        )
        charges.extend(self._assess_gravity_deviation(expected_artifact, content))

        return charges

    def _assess_python_novelty(
        self, artifact: str, old_text: str, new_text: str, is_new_file: bool
    ) -> list[NoveltyCharge]:
        """Detect new public symbols in a Python artifact."""
        try:
            old_tree = ast.parse(old_text) if old_text.strip() else None
            new_tree = ast.parse(new_text)
        except SyntaxError:
            return []

        old_public: set[str] = set()
        if old_tree is not None:
            for node in old_tree.body:
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    if not node.name.startswith("_"):
                        old_public.add(node.name)

        new_public: set[str] = set()
        for node in new_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    new_public.add(node.name)

        added = new_public - old_public
        charges: list[NoveltyCharge] = []
        for name in sorted(added):
            charges.append(
                NoveltyCharge(
                    category="new_public_symbol",
                    points=self.CHARGES["new_public_symbol"],
                    artifact=artifact,
                    detail=f"new public symbol '{name}'",
                )
            )
        return charges

    def _assess_dependency_novelty(
        self, artifact: str, old_text: str, new_text: str
    ) -> list[NoveltyCharge]:
        """Detect changes to dependency lockfiles."""
        if not (
            artifact.endswith("pyproject.toml")
            or artifact.lower().endswith("requirements.txt")
        ):
            return []
        # A coarse but safe signal: any non-trivial change to a dependency file
        # costs novelty points. Future versions can parse the actual dependency set.
        if old_text.strip() == new_text.strip():
            return []
        return [
            NoveltyCharge(
                category="new_dependency",
                points=self.CHARGES["new_dependency"],
                artifact=artifact,
                detail="dependency file changed",
            )
        ]

    def _assess_gravity_deviation(
        self, artifact: str, content: str
    ) -> list[NoveltyCharge]:
        """Detect when new code does not reference high-gravity symbols."""
        if not artifact.endswith(".py"):
            return []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        if not referenced:
            return []

        try:
            scorer = GravityScorer(self.project_dir)
            top = scorer.top_k(k=self.gravity_top_k)
        except Exception:  # noqa: BLE001
            return []
        top_names = {s.name for s in top}
        if referenced & top_names:
            return []
        return [
            NoveltyCharge(
                category="gravity_deviation",
                points=self.CHARGES["gravity_deviation"],
                artifact=artifact,
                detail="no reference to top-gravity symbols",
            )
        ]

    def spend(self, charges: list[NoveltyCharge]) -> None:
        """Record charges against the budget."""
        for charge in charges:
            self._state.spent += charge.points
            self._state.charges.append(asdict(charge))
        self.save()

    def would_exceed(self, charges: list[NoveltyCharge]) -> bool:
        """Return True if applying *charges* would exceed the remaining budget."""
        return sum(c.points for c in charges) > self.remaining

    def summary(self) -> dict[str, Any]:
        """Return a JSON-friendly budget summary."""
        return {
            "budget": self._state.budget,
            "spent": self._state.spent,
            "remaining": self.remaining,
            "charge_count": len(self._state.charges),
        }


# RACT 0.1.0 - Initial Public Release
