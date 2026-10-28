from __future__ import annotations


import shutil
from collections.abc import Callable

from ract import question_gate
from ract.cell_wrap import wrap_cells
from ract.manager import Plan, Step


ConsoleApprovalCallback = Callable[[Step], bool]


def _terminal_width() -> int:
    """The terminal's columns, between 40 and 80 (the same rule as the REPL)."""
    return max(40, min(80, shutil.get_terminal_size((80, 24)).columns))


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
    question = (
        f"Approve step: [{step.provider_hint}] {step.action} "
        f"-> {step.expected_artifact or 'answer, no file written'}? [y/N]:"
    )
    # The question wraps to the terminal width; the answer goes on the last line (B-041c).
    # Three columns stay free there, so the prompt and a one-character answer fit (package H).
    # By terminal columns (package I): a wide character is two columns.
    lines = wrap_cells(question, max(_terminal_width() - 3, 20))
    for line in lines[:-1]:
        print(line)
    question_gate.open_question()
    try:
        response = input(f"{lines[-1]} ").strip().lower()
    except EOFError:
        return False
    except KeyboardInterrupt:
        # Ctrl-C at the prompt: end the line first, so the next output does not print onto it.
        print()
        raise
    finally:
        question_gate.close_question()
    return response in {"y", "yes"}


def _plan_steps(plan: Plan) -> list:
    """The plan as the approval checklist numbers it (ADR-0049 D12)."""
    from ract.ui.plan_approval_view import Step as PlanStep

    return [
        PlanStep(n=n, action=step.action, target=step.expected_artifact or None)
        for n, step in enumerate(plan.steps, start=1)
    ]


def console_plan_approval(plan: Plan):
    """Show the plan once and read the operator's answer before any step runs (D12).

    Returns None when the plan needs no question (fewer than two steps, or no
    step that changes a file); otherwise the ``plan_gate.Resolution``:
    approved (with the steps kept and skipped) or refused (cancel). An answer
    that is not understood asks again. The text typed is never run; the
    plan's own text is shown through ``safe_text``.
    """
    from dataclasses import replace

    from ract import plan_gate, turn_context
    from ract.session_events import safe_text
    from ract.ui.plan_approval_view import screen_lines

    steps = _plan_steps(plan)
    if not plan_gate.approval_needed(steps, mode="default"):
        return None
    turn_context.report(
        "plan.approval_requested", plan_gate.approval_requested_payload(steps)
    )
    shown = [
        replace(
            step,
            action=safe_text(step.action),
            target=safe_text(step.target) if step.target else None,
        )
        for step in steps
    ]
    lines = screen_lines(shown, max(_terminal_width() - 3, 20))
    for line in lines[:-1]:
        print(line)
    while True:
        question_gate.open_question()
        try:
            line = input(f"{lines[-1]} ")
        except EOFError:
            line = "cancel"  # nobody can answer: nothing runs
        finally:
            question_gate.close_question()
        outcome = plan_gate.resolve_answer(steps, line)
        if outcome.kind != "ask_again":
            break
        print(outcome.error)
    if outcome.kind == "refused":
        answer = "cancel"
    else:
        answer = "skip" if outcome.skipped else "approve"
    turn_context.report(
        "plan.approval_answered", plan_gate.answered_payload(steps, answer, outcome)
    )
    return outcome


def refuse_plan_needing_approval(plan: Plan):
    """Headless ``default``: a plan that needs approval is refused before any step (D12).

    Returns a refused ``plan_gate.Resolution`` naming ``--accept-edits``, or None.
    """
    from ract import plan_gate

    sentence = plan_gate.headless_refusal(_plan_steps(plan), mode="default")
    if sentence is None:
        return None
    return plan_gate.Resolution("refused", error=sentence)


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
