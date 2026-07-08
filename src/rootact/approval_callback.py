# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from collections.abc import Callable

from rootact.manager import Step

_ROOT_KNOT = object()


ConsoleApprovalCallback = Callable[[Step], bool]


def console_approval_callback(step: Step) -> bool:
    """Prompt the operator for approval before executing *step*.

    LR:: This is intentionally simple: it reads a single line from stdin and
    accepts 'y' or 'yes' (case-insensitive). It is meant for interactive
    terminal use; non-interactive callers should pre-approve steps or use
    yolo mode.
    """
    prompt = (
        f"Approve step: [{step.provider_hint}] {step.action} "
        f"-> {step.expected_artifact}? [y/N]: "
    )
    try:
        response = input(prompt).strip().lower()
    except EOFError:
        return False
    return response in {"y", "yes"}


def auto_approval_callback(step: Step) -> bool:
    """Auto-approve low-risk steps; block high-risk ones.

    Risk is crudely guessed from the action text. This is a fallback when no
    interactive terminal is available and the user still wants some gating.
    """
    risky = {"delete", "remove", "drop", "rm", "exec", "eval", "shell"}
    action_lower = step.action.lower()
    return not any(word in action_lower for word in risky)


def yolo_approval_callback(_step: Step) -> bool:
    """Always approve. Used in yolo mode."""
    return True
