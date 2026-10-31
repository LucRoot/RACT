from __future__ import annotations


import shutil
from collections.abc import Callable
from typing import Any, cast

from ract import question_gate
from ract.cell_wrap import wrap_cells
from ract.console_interrupt import read_line
from ract.manager import Plan, Step


ConsoleApprovalCallback = Callable[[Step], bool]

# How long a prompt whose read ended with EOF waits for a Ctrl-C's cancel to
# arrive before it reports its result (adjudication row 6).
_CTRL_C_GRACE_SECONDS = 0.5


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
        response = read_line(f"{lines[-1]} ").strip().lower()
    except EOFError:
        # A Ctrl-C ends this read with EOF just before the turn is cancelled;
        # let the cancel arrive, so the step ends skipped rather than failed.
        from ract import turn_context

        turn_context.cancelled_within(_CTRL_C_GRACE_SECONDS)
        return False
    except KeyboardInterrupt:
        # Ctrl-C at the prompt: end the line first, so the next output does not print onto it.
        print()
        raise
    finally:
        question_gate.close_question()
    return response in {"y", "yes"}


def _tier_2_change(name: str, args: object) -> list[str]:
    """The exact change a tier-2 call asks for, as lines (ADR-0047 D6)."""
    from ract.redaction import redact

    fields: dict[str, Any] = getattr(args, "model_dump", lambda: {})()
    lines = [f"{name} {fields.get('path') or ''}".rstrip()]
    if fields.get("destination"):
        lines.append(f"  to {fields['destination']}")
    for key, mark in (("content", "+"), ("old", "-"), ("new", "+"), ("patch", "")):
        text = fields.get(key)
        if isinstance(text, str):
            body = redact(text).splitlines()
            lines += [f"  {mark}{line}" for line in body[:40]]
            if len(body) > 40:
                lines.append(f"  ... {len(body) - 40} more lines")
    return lines


def console_tier_2_choice(name: str, args: object, note: str = "") -> str:
    """Ask the operator before a tier-2 tool call: "once", "session" or "deny".

    LR:: ADR-0047 D6, ADR-0048 D6. The call touches a control or
    executable-configuration file. The change is shown as it would be
    written, with control characters made visible; "y" allows it once, "s"
    allows writes to the same files for the rest of this session (in memory
    only, ``tier2_approvals``), anything else refuses. *note* says why a
    resumed session is asked again. A model's words never reach this answer:
    the question is read from the console.
    """
    from ract.session_events import safe_text

    width = max(_terminal_width() - 3, 20)
    if note:
        _print_wrapped(note)
    if name.startswith("git_"):
        # B-115 (D8): a git tool shows the exact command and is asked once per call.
        # G-239 D8: quoted, with the staged files and the secret scan's result.
        from ract.tools.git_tools import question_lines

        _print_wrapped(
            "Tier 2: RACT would run this git command in the step's worktree:"
        )
        for line in question_lines(name, args):
            for part in wrap_cells(safe_text(line), width):
                print(f"  {part}")
        question_gate.open_question()
        try:
            response = read_line("Run it once? [y/N]: ").strip().lower()
        except EOFError:
            return "deny"
        finally:
            question_gate.close_question()
        return "once" if response in {"y", "yes"} else "deny"
    _print_wrapped(
        "Tier 2: this change touches a control or executable-configuration "
        "file. The change:"
    )
    for line in _tier_2_change(name, args):
        for part in wrap_cells(safe_text(line), width):
            print(part)
    _print_wrapped("y allows it once, s for this session, N refuses")
    question_gate.open_question()
    try:
        response = read_line("Allow this change? [y/s/N]: ").strip().lower()
    except EOFError:
        return "deny"
    except KeyboardInterrupt:
        print()
        raise
    finally:
        question_gate.close_question()
    if response in {"y", "yes"}:
        return "once"
    if response in {"s", "session"}:
        return "session"
    return "deny"


def console_tier_2_callback(name: str, args: object) -> bool:
    """The tier-2 question with no session to remember an answer in: True to allow."""
    return console_tier_2_choice(name, args) in {"once", "session"}


def console_proposed_reviewer(path: str, before: bytes | None, after: bytes | None):
    """Ask about each hunk a step proposes for *path*, at the console (B-110 D6).

    The answers are read from the console only; a model's text never answers.
    End of input raises ``ReviewStopped`` and nothing from the step is applied.
    """
    from ract.review_hunks import review_proposed_file

    width = _terminal_width()

    def ask(question: str) -> str | None:
        lines = wrap_cells(question, max(width - 3, 20)) or [""]
        for line in lines[:-1]:
            print(line)
        question_gate.open_question()
        try:
            return read_line(f"{lines[-1]} ")
        except EOFError:
            return None
        finally:
            question_gate.close_question()

    return review_proposed_file(path, before, after, ask, print, width)


def console_tier_3_prompt(facts: dict) -> bool | str:
    """Ask the operator before a tier-3 command runs (ADR-0048 D6). True on yes.

    B-113: where a session answer is offered (``session_choice``), ``s``
    returns ``"session"``; a changed entry point is shown first with MASON's
    screen, and then only once or no is offered.

    LR:: The prompt shows the full argv with control characters made
    visible, the resolved executable, the folder, network on or off and
    that no sandbox confines it here; the model's reason is labeled as the
    model's. Only "y" or "yes" typed at the console runs it, once.
    """
    from ract.session_events import safe_text
    from ract.ui.command_screens import CommandRequest, approval_prompt_lines

    # MASON's view (B-112): argv escaped, executable, cwd, network, sandbox,
    # limits, the model's reason as model text. The choice is once or no
    # until slice (d) brings session and always.
    request = CommandRequest(
        argv=tuple(str(a) for a in facts.get("argv", [])),
        executable=str(facts.get("executable") or "not resolved"),
        cwd=str(facts.get("cwd", "")),
        network=str(facts.get("network", "off")).startswith("on"),
        sandbox_enforced=str(facts.get("sandbox", "")).startswith("enforced"),
        limits=(
            f"wall {facts['timeout_s']} s; processes, memory and CPU not enforced "
            "on this machine"
            if facts.get("timeout_s")
            else ""
        ),
        reason=str(facts.get("reason") or ""),
    )
    width = max(_terminal_width() - 3, 20)
    session = bool(facts.get("session_choice"))
    from ract.ui.allow_screens import EntryPointChange, entry_point_question_lines

    for path, why in facts.get("entry_points") or []:
        for line in entry_point_question_lines(
            EntryPointChange(str(path), str(why)), width
        )[:-1]:
            print(line)
    for line in approval_prompt_lines(
        request,
        width,
        choices=(
            "y runs it once, s for this session, N refuses"
            if session
            else "y runs it once, N refuses"
        ),
    ):
        print(line)
    _print_wrapped(
        f"  rule: {safe_text(str(facts.get('rule') or 'none'))} "
        f"({safe_text(str(facts.get('why', '')))})"
    )
    for note in facts.get("notes") or []:
        _print_wrapped(f"  note: {safe_text(str(note))}")
    question_gate.open_question()
    try:
        response = (
            (
                read_line("Run it? [y once, s session, N]: ")
                if session
                else read_line("Run it once? [y/N]: ")
            )
            .strip()
            .lower()
        )
    except EOFError:
        return False
    except KeyboardInterrupt:
        print()
        raise
    finally:
        question_gate.close_question()
    if session and response in {"s", "session"}:
        return "session"
    return response in {"y", "yes"}


def console_git_init_offer(command: str, count: int, left_out: list[str]) -> bool:
    """Offer ``git init`` at the console, as a tier-2 action (B-110 D6). True on yes."""
    from ract.ui.workspace_screens import not_git_offer_lines

    # MASON's view (B-110): the exact command as a tier-2 action, the
    # sensitive names left out, then the choice; the file count first.
    _print_wrapped(
        f"Tier 2: {count} file{'s' if count != 1 else ''} would be committed."
    )
    lines = not_git_offer_lines(command, left_out, max(_terminal_width() - 3, 20))
    for line in lines[:-1]:
        print(line)
    question_gate.open_question()
    try:
        response = read_line(lines[-1] + " ").strip().lower()
    except EOFError:
        return False
    except KeyboardInterrupt:
        print()
        raise
    finally:
        question_gate.close_question()
    return response in {"y", "yes"}


def review_replaces_step_question(
    base: ConsoleApprovalCallback,
) -> ConsoleApprovalCallback:
    """The per-step question, skipped for a step that writes a file (B-110 D6).

    With proposed changes reviewed hunk by hunk before they are applied, the
    review is the question for a file step; a tool call still asks first.
    """

    def callback(step: Step) -> bool:
        if step.expected_artifact and step.tool_call is None:
            return True
        return base(step)

    return callback


def _plan_steps(plan: Plan) -> list:
    """The plan as the approval checklist numbers it (ADR-0049 D12)."""
    from ract.ui.plan_approval_view import Step as PlanStep

    from ract.plan_gate import AGENT_TARGET

    return [
        PlanStep(
            n=n,
            action=step.action,
            target=AGENT_TARGET
            if getattr(step, "agent", False)
            else (step.expected_artifact or None),
        )
        for n, step in enumerate(plan.steps, start=1)
    ]


def _print_wrapped(text: str) -> None:
    """Print a console message wrapped to the terminal width (package 2: no line runs past it)."""
    for line in wrap_cells(text, max(_terminal_width() - 3, 20)):
        print(line)


def _edit_step(steps: list, n: int, plan_gate):
    """Ask for the new text of step ``n`` and apply it (D12). Returns (steps, error).

    With no project root at the console, a path the new text names must already be in the plan:
    any other path is refused.
    """
    # The question gate silences the heartbeat while the operator answers (BUILDER's package 2 handoff).
    question_gate.open_question()
    try:
        text = read_line(f"new text for step {n}: ")
    except EOFError:
        return steps, "no new text was given; the step is unchanged"
    finally:
        question_gate.close_question()
    edited, error = plan_gate.apply_edit(
        steps,
        n,
        text,
        check_path=lambda path: (
            f"{path} is not in the plan and the console cannot check it"
        ),
    )
    if error is not None:
        return steps, error
    return edited, None


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

    def screen(current: list) -> list[str]:
        shown = [
            replace(
                step,
                action=safe_text(step.action),
                target=safe_text(step.target) if step.target else None,
            )
            for step in current
        ]
        return screen_lines(shown, max(_terminal_width() - 3, 20))

    lines = screen(steps)
    edited_n: int | None = None
    while True:
        question_gate.open_question()
        try:
            line = read_line(f"{lines[-1]} ")
        except EOFError:
            # Nobody can answer, or a Ctrl-C ended the read: nothing runs.
            turn_context.cancelled_within(_CTRL_C_GRACE_SECONDS)
            line = "cancel"
        finally:
            question_gate.close_question()
        outcome = plan_gate.resolve_answer(steps, line)
        if outcome.kind == "edit":
            # D12: the new text is one line, checked for new paths; the plan is shown again.
            steps, error = _edit_step(steps, cast(int, outcome.n), plan_gate)
            if error is None:
                edited_n = outcome.n
                # L-196 point 5: the edited plan is announced again, with its new hash.
                turn_context.report(
                    "plan.proposed", plan_gate.approval_requested_payload(steps)
                )
                turn_context.report(
                    "plan.approval_requested",
                    plan_gate.approval_requested_payload(steps),
                )
                lines = screen(steps)
                for shown_line in lines[:-1]:
                    print(shown_line)
            else:
                _print_wrapped(error)
            continue
        if outcome.kind != "ask_again":
            break
        _print_wrapped(cast(str, outcome.error))
    # L-196 point 1: the whole plan as approved, edits included, is what the run takes.
    outcome = replace(outcome, shown=list(steps))
    if outcome.kind == "refused":
        answer = "cancel"
    else:
        answer = "skip" if outcome.skipped else "approve"
    turn_context.report(
        "plan.approval_answered",
        plan_gate.answered_payload(steps, answer, outcome, edited=edited_n),
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

    B-139: an agent step (B-137) names no artifact and no tool call, and may
    change any file through the step loop, so it is refused here too, not
    only at plan approval, which a replayed plan skips.
    """
    if getattr(step, "agent", False):
        return False
    return not step.expected_artifact and step.tool_call is None


def yolo_approval_callback(_step: Step) -> bool:
    """Always approve. Used in yolo mode."""
    return True


# RACT 0.1.1 - Trust and tooling
