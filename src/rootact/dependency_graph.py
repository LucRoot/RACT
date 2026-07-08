# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from typing import Dict, Set

from .manager import Plan, Step


class DependencyGraph:
    """A simple directed acyclic graph that tracks artifact dependencies.

    This helper extracts artifact dependencies from a Plan and its Steps, allowing
    static analysis of execution order. It is deterministic and does not require
    any external libraries.
    """

    def __init__(self) -> None:
        self._graph: Dict[str, Set[str]] = {}
        self._reverse: Dict[str, Set[str]] = {}

    def add_plan(self, plan: Plan) -> None:
        """Add a plan and its steps to the graph.

        Args:
            plan: The plan containing steps and an optional assumption.
        """
        for step in plan.steps:
            self.add_step(step)
        # Infer dependencies: a step depends on any plan artifact referenced in
        # its action description. Checking the full plan (not just prior steps)
        # catches forward references that can form cycles.
        all_artifacts = {step.expected_artifact for step in plan.steps}
        for step in plan.steps:
            artifact = step.expected_artifact
            action_lower = step.action.lower()
            for other in all_artifacts:
                if other == artifact:
                    continue
                if other.lower() in action_lower:
                    self._add_edge(artifact, other)

    def _add_edge(self, dependent: str, dependency: str) -> None:
        """Record that ``dependent`` depends on ``dependency``."""
        self._ensure_node(dependent)
        self._ensure_node(dependency)
        self._graph[dependent].add(dependency)
        self._reverse[dependency].add(dependent)

    def _ensure_node(self, artifact: str) -> None:
        """Create graph and reverse entries for ``artifact`` if absent."""
        if artifact not in self._graph:
            self._graph[artifact] = set()
            self._reverse[artifact] = set()

    def add_step(self, step: Step) -> None:
        """Add a single step to the graph.

        Args:
            step: The step to add, providing an expected_artifact.
        """
        artifact = step.expected_artifact
        self._ensure_node(artifact)

    def get_dependencies(self, artifact: str) -> Set[str]:
        """Return the set of artifacts that ``artifact`` depends on.

        Args:
            artifact: The artifact to query.

        Returns:
            A set of artifact names that the given artifact depends on.
        """
        return self._graph.get(artifact, set())

    def get_dependents(self, artifact: str) -> Set[str]:
        """Return the set of artifacts that depend on ``artifact``.

        Args:
            artifact: The artifact to query.

        Returns:
            A set of artifact names that have a dependency on the given artifact.
        """
        return self._reverse.get(artifact, set())

    def has_cycle(self) -> bool:
        """Detect if the current graph contains a cycle.

        Returns:
            True if a cycle exists, False otherwise.
        """
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def _dfs(node: str) -> bool:
            if node not in self._graph:
                return False
            visited.add(node)
            rec_stack.add(node)
            for neighbor in self._graph[node]:
                if neighbor not in visited:
                    if _dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        return any(_dfs(node) for node in self._graph)

    def to_dict(self) -> Dict[str, Set[str]]:
        """Convert the graph to a plain dictionary for serialization.

        Returns:
            A dictionary mapping each artifact to its dependencies.
        """
        return {node: deps for node, deps in self._graph.items()}


# RACT 0.1.0 - Initial Public Release
