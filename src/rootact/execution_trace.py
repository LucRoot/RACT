# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from typing import List, Dict, Any

from rootact.manager import Plan


def execution_trace(
    plan: Plan, context: Dict[str, Any] | None = None
) -> List[Dict[str, Any]]:
    """Convert a Plan into a deterministic execution trace.

    This utility extracts the ordered steps from a Plan and builds a trace
    suitable for logging or debugging. It does not perform side effects.
    """
    if context is None:
        context = {}
    trace: List[Dict[str, Any]] = []
    for step in plan.steps:
        trace.append(
            {
                "action": step.action,
                "provider_hint": step.provider_hint,
                "expected_artifact": step.expected_artifact,
                "context_snapshot": context.get(step.action, {}),
            }
        )
    return trace


def build_trace_context(context: Dict[str, Any], action: str) -> Dict[str, Any]:
    """Helper to safely retrieve context for a given action.

    Returns an empty dict if the action key is missing, ensuring deterministic
    output even when context is incomplete.
    """
    return context.get(action, {})
