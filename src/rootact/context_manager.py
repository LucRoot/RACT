from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from rootact.manager import Plan
from rootact.plan_serializers import plan_from_dict, plan_to_dict


@dataclass
class SessionState:
    goal: str
    constraints: Dict[str, Any]
    plan: Optional[Plan] = None
    recent_failures: int = 0
    artifacts: Dict[str, bytes] = field(default_factory=dict)


class ContextManager:
    """Manages session context for RootACT, handling save, load, clear, reset, and rollback tracking."""

    def __init__(self, base_dir: str | os.PathLike) -> None:
        self.base_dir = Path(base_dir)
        self.session_store: Dict[str, SessionState] = {}
        self._ensure_store()

    def _ensure_store(self) -> None:
        """Ensure the base directory exists for session persistence."""
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _state_to_dict(state: SessionState) -> Dict[str, Any]:
        """Serialize a SessionState to a JSON-safe dictionary.

        LR:: Artifacts are base64-encoded so bytes survive the JSON round-trip.
        Plans use the shared plan serializer so the manager's dataclass structure
        is preserved without leaking JSON logic into the manager module.
        """
        return {
            "goal": state.goal,
            "constraints": state.constraints,
            "plan": plan_to_dict(state.plan) if state.plan is not None else None,
            "recent_failures": state.recent_failures,
            "artifacts": {
                name: base64.b64encode(data).decode("ascii")
                for name, data in state.artifacts.items()
            },
        }

    @staticmethod
    def _state_from_dict(data: Dict[str, Any]) -> SessionState:
        """Reconstruct a SessionState from a dictionary."""
        plan = None
        if data.get("plan") is not None:
            plan = plan_from_dict(data["plan"])
        return SessionState(
            goal=data["goal"],
            constraints=data["constraints"],
            plan=plan,
            recent_failures=data.get("recent_failures", 0),
            artifacts={
                name: base64.b64decode(data)
                for name, data in data.get("artifacts", {}).items()
            },
        )

    def load(self, session_id: str) -> SessionState:
        """Load a session's state from disk; raise if not found."""
        path = self.base_dir / f"{session_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Session {session_id} not found")
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        state = self._state_from_dict(data)
        self.session_store[session_id] = state
        return state

    def save(self, session_id: str, state: SessionState) -> None:
        """Save the given state to disk atomically and keep it in memory."""
        self.session_store[session_id] = state
        path = self.base_dir / f"{session_id}.json"
        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fp:
            json.dump(self._state_to_dict(state), fp, indent=2)
        tmp_path.replace(path)

    def clear(self, session_id: str, keep_goal: bool = False) -> None:
        """Clear artifacts, plan, and recent failures; optionally preserve the goal."""
        if session_id not in self.session_store:
            self.load(session_id)
        state = self.session_store[session_id]
        if keep_goal:
            preserved = SessionState(
                goal=state.goal,
                constraints=state.constraints,
                plan=None,
                recent_failures=0,
                artifacts={},
            )
        else:
            preserved = SessionState(
                goal="",
                constraints={},
                plan=None,
                recent_failures=0,
                artifacts={},
            )
        self.save(session_id, preserved)

    def reset_to_goal(
        self, session_id: str, goal: str, constraints: Dict[str, Any]
    ) -> None:
        """Replace the session state with a fresh goal and constraints."""
        if session_id not in self.session_store:
            self.load(session_id)
        self.save(
            session_id,
            SessionState(
                goal=goal,
                constraints=constraints,
                plan=None,
                recent_failures=0,
                artifacts={},
            ),
        )

    def rollback_streak(self, session_id: str) -> int:
        """Increment and return the consecutive failure count for the session."""
        if session_id not in self.session_store:
            self.load(session_id)
        state = self.session_store[session_id]
        state.recent_failures += 1
        self.save(session_id, state)
        return state.recent_failures


# RACT 0.1.0 - Initial Public Release
