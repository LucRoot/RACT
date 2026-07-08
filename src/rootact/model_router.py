from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from typing import Any, Dict, List, Optional


class ModelBackend:
    def __init__(self, name: str, capabilities: Dict[str, Any]) -> None:
        self.name = name
        self.capabilities = capabilities

    def process(self, task_type: str) -> str:
        return f"processed by {self.name}"


class ModelRouter:
    """Routes tasks to appropriate model backends based on type and complexity."""

    def __init__(self, backends: Optional[List[ModelBackend]] = None) -> None:
        self.backends: Dict[str, ModelBackend] = {}
        if backends:
            for backend in backends:
                self.register_backend(backend)

    def register_backend(self, backend: ModelBackend) -> None:
        """Register a backend with its capabilities."""
        self.backends[backend.name] = backend

    def supported_task_types(self) -> List[str]:
        """Return list of task types for which at least one backend is registered."""
        return list(
            set(
                pref
                for caps in self.backends.values()
                for pref in caps.capabilities.get("task_types", [])
            )
        )

    def route(self, task_type: str, complexity: str) -> ModelBackend:
        """Select a backend matching task_type and complexity; fallback to most capable."""
        candidates = [
            caps
            for b, caps in self.backends.items()
            if task_type in caps.capabilities.get("task_types", [])
            and caps.capabilities.get("complexity_level") == complexity
        ]
        if candidates:
            return candidates[0]
        fallback = max(
            self.backends.values(),
            key=lambda b: len(b.capabilities.get("capabilities", [])),
        )
        return fallback

    def route_fallback(self, task_type: str, complexity: str) -> ModelBackend:
        """Fallback routing when no exact match is found."""
        candidates = [
            caps
            for b, caps in self.backends.items()
            if task_type in caps.capabilities.get("task_types", [])
            and caps.capabilities.get("complexity_level") == complexity
        ]
        if candidates:
            return candidates[0]
        if self.backends:
            return max(
                self.backends.values(),
                key=lambda b: len(b.capabilities.get("capabilities", [])),
            )
        raise RuntimeError("No backends registered")


# Simple fake backends for testing
class FakeFastBackend(ModelBackend):
    def __init__(self) -> None:
        super().__init__(
            "fast",
            {
                "task_types": ["boilerplate"],
                "complexity_level": "low",
                "capabilities": {},
            },
        )

    def process(self, task_type: str) -> str:
        return f"fast processed by {self.name}"


class FakeCapableBackend(ModelBackend):
    def __init__(self) -> None:
        super().__init__(
            "capable",
            {
                "task_types": ["diagnose", "architect"],
                "complexity_level": "high",
                "capabilities": {"extra": "info"},
            },
        )

    def process(self, task_type: str) -> str:
        return f"capable processed by {self.name}"
