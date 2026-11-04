"""The strong-model path (ADR-0049 D6, B-233).

For a strong model the playbook may merge PLANNER and EDITOR steps into fewer,
larger steps, use native tool calling, and run EXPLORER work in parallel in
separate read-only contexts (no worktree is needed for reads, ADR-0047 D6).
A weak model keeps the D5 mechanism unchanged.

What this module is: the mechanism, fully tested. The strength signal is
resolved by :func:`strength_for_harness` from a ``model_strength`` attribute
on the harness, which today defaults to ``"weak"`` for every run. Wiring it
to a capability cache (the probe writes nothing today, ADR-0049 "Model
integration") is the follow-on card; nothing here adds a run-start probe or
any egress.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ract.manager import Plan
    from ract.providers.capability_probe import ProviderProbe
    from ract.rooted import Rooted
    from ract.tools.loop import Complete

WEAK = "weak"
STRONG = "strong"

# A strong model, for this card, is one the probe saw take tool calls, emit
# reasoning text, and advertise a context window at or above this floor.
# The floor is a named constant so the boundary is one line to change.
CONTEXT_FLOOR_TOKENS = 32_768

# The merged-role name D6 uses for the combined PLANNER+EDITOR step.
MERGED_ROLE = "planner+editor"


def select_variant(roles: list[str], *, strength: str) -> list[str]:
    """The playbook variant for *strength*.

    ``strong`` merges one consecutive ``planner``+``editor`` pair into the
    single :data:`MERGED_ROLE` entry (fewer, larger steps); anything else
    returns the roles unchanged, which is what keeps the weak path on the D5
    mechanism.
    """
    if strength != STRONG:
        return list(roles)
    out: list[str] = []
    index = 0
    while index < len(roles):
        if (
            index + 1 < len(roles)
            and roles[index] == "planner"
            and roles[index + 1] == "editor"
        ):
            out.append(MERGED_ROLE)
            index += 2
        else:
            out.append(roles[index])
            index += 1
    return out


def strength_from_probe(probe: ProviderProbe) -> str:
    """Map a capability-probe result to a strength word.

    ``strong`` only when the probe saw tool calling and reasoning text work
    and a context window at or above :data:`CONTEXT_FLOOR_TOKENS`; every
    other result, including an unprobed provider, is ``weak``. A finding the
    probe never made cannot promote a model.
    """
    by_label = {finding.label: finding for finding in probe.findings}

    tool_calling = by_label.get("tool calling")
    reasoning = by_label.get("reasoning text")
    context = by_label.get("context window")
    return (
        STRONG
        if tool_calling is not None
        and tool_calling.status == "works"
        and reasoning is not None
        and reasoning.status == "returned"
        and context is not None
        and context.number is not None
        and context.number >= CONTEXT_FLOOR_TOKENS
        else WEAK
    )


def apply_strong_path(plan: Plan, *, strength: str, agent_loop: bool = True) -> Plan:
    """The plan a run executes.

    ``strong`` collapses a plan of two or more steps into one agent step
    that carries every approved step in its instruction: the step agent loop
    works through them with tool calls in fewer completions, and the end-of-
    turn verification is unchanged, so the verified result is the same. The
    merge needs the step agent loop; without it (``agent_loop=False``) the
    plan passes through, since a merged step could not run. A weak strength,
    a single-step plan and an answer-only plan (nothing a larger step could
    merge) also return the plan untouched.
    """
    if strength != STRONG or len(plan.steps) < 2 or not agent_loop:
        return plan
    if not any(step.expected_artifact for step in plan.steps):
        return plan
    instruction = "Do every step of the approved plan, in order." + "".join(
        f" Step {i}: {step.action}" for i, step in enumerate(plan.steps, start=1)
    )
    merged = replace(
        plan.steps[-1],
        action=instruction,
        expected_artifact="",
        agent=True,
        opening=None,
    )
    return replace(plan, steps=[merged])


def strength_for_harness(harness: Any) -> str:
    """The strength word a run resolves to.

    Reads the harness's ``model_strength`` attribute, defaulting to
    :data:`WEAK`; today nothing sets it, so every real run keeps the D5
    mechanism. The capability-cache card wires probe facts to the attribute.
    """
    strength = getattr(harness, "model_strength", WEAK)
    return strength if strength in (WEAK, STRONG) else WEAK


def explore_in_parallel(
    complete: Complete,
    questions: list[str],
    root: Any,
    *,
    budgets: Any = None,
    max_workers: int | None = None,
) -> list[Rooted[str]]:
    """Run read-only EXPLORER questions in separate contexts, answers in order.

    Each question is one run of the read-only answer loop with its own
    messages and its own tool gate; the loops run in worker threads under a
    snapshot of the caller's context (so the cancel flag and the reporter
    are the turn's), and each offers only the read-only tools, so a write
    call in any of them is refused by the gate and never touches the disk.
    """
    if not questions:
        return []
    from concurrent.futures import ThreadPoolExecutor

    from ract.runtime import run_with_ambient
    from ract.tools.loop import LoopBudgets, answer_with_tools

    def run_one(question: str) -> Rooted[str]:
        return answer_with_tools(
            complete,
            question,
            root,
            budgets=budgets or LoopBudgets(),
        )

    with ThreadPoolExecutor(max_workers=max_workers or min(len(questions), 4)) as pool:
        futures = [
            pool.submit(run_with_ambient(run_one, question)) for question in questions
        ]
        return [future.result() for future in futures]
