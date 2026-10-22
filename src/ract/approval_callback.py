from __future__ import annotations


from collections.abc import Callable

from ract.manager import Step


ConsoleApprovalCallback = Callable[[Step], bool]


def console_approval_callback(step: Step) -> bool:
    """Prompt the operator for approval before executing *step*.

    LR:: This is intentionally simple: it reads a single line from stdin and
    accepts 'y' or 'yes' (case-insensitive). It is meant for interactive
    terminal use; non-interactive callers should pre-approve steps or use
    yolo mode.

    A step that only answers (no file, no tool) writes nothing and is not
    asked about (B-034 `default` mode asks before changes, not questions).
    """
    if not step.expected_artifact and step.tool_call is None:
        return True
    prompt = (
        f"Approve step: [{step.provider_hint}] {step.action} "
        f"-> {step.expected_artifact or 'answer, no file written'}? [y/N]: "
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


def refuse_changes_callback(step: Step) -> bool:
    """`default` mode with no terminal to ask: answers run, changes do not (B-034).

    A headless run (`ract -p`) cannot ask before a change, so it refuses
    every step that writes a file or calls a tool. `--accept-edits` is the
    operator's way to let such a run change files.
    """
    return not step.expected_artifact and step.tool_call is None


def yolo_approval_callback(_step: Step) -> bool:
    """Always approve. Used in yolo mode."""
    return True


# RACT 0.1.1 - Trust and tooling
