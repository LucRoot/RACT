"""The REVIEWER call (ADR-0049 D14, B-061b).

One review is one run of the read-only tools loop (B-011a) with the REVIEWER
prompt and its own budgets: 8 turns, 16 tool calls, 300 s. The request holds
the step's goal, its acceptance checks, the verification summary and the
diff, and nothing else. The diff is repository text, so it goes inside a
block with the untrusted label; every request passes the outbound scan in the
adapter, as every model request does. The reply is read only as a
``ReviewFindings`` object; the loop offers only the four tier-0 tools, so a
call to any other tool is refused by the tool gate. Each request is recorded
in the egress ledger with purpose ``role:reviewer`` (ADR-0049 D8).
"""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

from ract import egress_ledger
from ract.review.findings import (
    FindingsRefused,
    ReviewFindings,
    ReviewRequest,
    parse_findings,
)
from ract.rooted import Rooted
from ract.tools import UNTRUSTED_LABEL
from ract.tools.loop import Complete, LoopBudgets, answer_with_tools, tool_lines

REVIEW_BUDGETS = LoopBudgets(max_turns=8, max_tool_calls=16, max_wall_seconds=300.0)
LEDGER_PURPOSE = "role:reviewer"
_FENCE = re.compile(r"^```[\w-]*\n(.*)\n```$", re.S)


def prompt() -> str:
    """The REVIEWER system prompt, with the tool list filled in."""
    text = (resources.files("ract") / "default_prompts" / "reviewer.txt").read_text(
        encoding="utf-8"
    )
    return text.replace("{tools}", tool_lines())


def question(request: ReviewRequest) -> str:
    """The user message for one review: the four D14 inputs and nothing else."""
    checks = "\n".join(f"- {c}" for c in request.acceptance) or "- (none given)"
    return (
        f"Step {request.step}: {request.goal}\n\n"
        f"Acceptance checks:\n{checks}\n\n"
        f"Verification result:\n{request.verification or '(none recorded)'}\n\n"
        f"{UNTRUSTED_LABEL}\n<diff>\n{request.diff}\n</diff>"
    )


def read_findings(answer: str) -> ReviewFindings:
    """The ReviewFindings in the loop's final answer, or FindingsRefused."""
    text = answer.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise FindingsRefused("the reply is not a JSON findings object") from None
    return parse_findings(data)


def review_step(
    complete: Complete, request: ReviewRequest, root: Path | str
) -> Rooted[ReviewFindings]:
    """Run one review; the findings are not validated here (``validate`` is)."""
    with egress_ledger.purpose(LEDGER_PURPOSE, role="reviewer"):
        answered = answer_with_tools(
            complete,
            question(request),
            root,
            budgets=REVIEW_BUDGETS,
            system=prompt(),
        )
    if not answered.is_ok():
        return Rooted(
            value=None,
            assumption="The REVIEWER replied with findings.",
            confidence=0.0,
            provenance=["review.reviewer"],
            error=f"review not completed: {answered.error}",
            hint=answered.hint,
        )
    try:
        findings = read_findings(answered.unwrap())
    except FindingsRefused as exc:
        return Rooted(
            value=None,
            assumption="The REVIEWER replied with findings.",
            confidence=0.0,
            provenance=["review.reviewer"],
            error=f"review not completed: {exc}",
            hint="findings",
        )
    return Rooted(
        value=findings,
        assumption="The REVIEWER replied with findings; they are not checked yet.",
        confidence=1.0,
        provenance=["review.reviewer"],
    )
