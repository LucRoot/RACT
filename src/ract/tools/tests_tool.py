"""``run_tests``: the project's tests, under the grant's test rule, asked first (B-112).

LR:: A tier-3 tool (ADR-0048 D5, D6, D11). The command is the grant's test
rule (the rule with id ``tests``, or the one that runs pytest or ``npm
test``) plus the selectors the model names, each a test path or node id
inside the project. The matcher sees the whole argv; a selector naming a
file written in this session makes it ask in every mode. In ``ask`` mode
the operator answers a prompt that shows the full argv, the resolved
executable, the folder, network on or off and that the sandbox is best
effort; the model's reason is shown as the model's. With no grant that
holds, no test rule, or nobody to answer, nothing runs and the refusal says
why. Network is off unless the rule says otherwise (D11).
"""

from __future__ import annotations

import uuid
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ract.core.threat_model import CapabilityTier
from ract.tools import ToolRefused, ToolResult, ToolSpec

_RESULT_CAP = 64 * 1024


class RunTestsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selectors: list[str] = Field(default_factory=list, max_length=32)
    reason: str = Field(default="", max_length=500)

    @field_validator("selectors")
    @classmethod
    def _inside(cls, selectors: list[str]) -> list[str]:
        for selector in selectors:
            path = selector.split("::", 1)[0].replace("\\", "/")
            if (
                not selector
                or selector.startswith("-")
                or "\x00" in selector
                or len(selector) > 300
                or PurePosixPath(path).is_absolute()
                or ":" in path
                or ".." in PurePosixPath(path).parts
            ):
                raise ValueError(
                    f"{selector!r} is not a test path or node id inside the project"
                )
        return selectors


def _test_rule(policy: object) -> object | None:
    rules = list(getattr(getattr(policy, "commands", None), "allow", []) or [])
    for rule in rules:
        if rule.id == "tests":
            return rule
    runners = (["python", "-m", "pytest"], ["pytest"], ["npm", "test"])
    return next((r for r in rules if list(r.argv)[: len(r.argv)] in runners), None)


def run_tests(root: Path, args: RunTestsArgs) -> ToolResult:
    from ract.policy import tier3
    from ract.policy.matcher import classify
    from ract.tools.command import run_command

    ctx = tier3.current()
    if ctx is None:
        raise ToolRefused("tier 3 is off for this step", tier3.NO_GRANT_HINT)
    if not ctx.grant.holds or ctx.grant.policy is None:
        raise ToolRefused(f"tier 3 is off: {ctx.grant.reason}", tier3.NO_GRANT_HINT)
    policy = ctx.grant.policy
    rule = _test_rule(policy)
    if rule is None:
        raise ToolRefused(
            "the grant has no test rule",
            "`ract policy init --guided` proposes one for this project's test runner",
        )
    argv = [*rule.argv, *args.selectors]
    match = classify(argv, policy, root, model_written=frozenset(ctx.model_written))
    if match.outcome == "refused":
        raise ToolRefused(f"refused: {match.reason}", "name tests inside the project")
    if ctx.approve is None:
        raise ToolRefused(
            "tier 3 asks you before a command runs, and nobody can answer here",
            "run it in a session at a terminal; headless runs and --yolo never run tier 3",
        )
    facts = {
        "argv": list(match.argv),
        "executable": match.executable,
        "cwd": "the step's worktree",
        "network": "on" if rule.network else "off (not enforced on this machine)",
        "sandbox": "best effort: not enforced on this machine",
        "rule": rule.id,
        "why": match.reason,
        "reason": args.reason,
        "notes": list(match.notes),
    }
    if not ctx.approve(facts):
        raise ToolRefused(
            "you declined the command; nothing ran", "the model can ask again or stop"
        )
    rooted = run_command(
        match,
        worktree=root,
        rule=rule,
        grant_digest=ctx.grant.digest,
        approval_id=f"a-{uuid.uuid4().hex[:12]}",
        approver="operator-tty",
        runner=ctx.runner,
        network=bool(rule.network),
        project=ctx.project,
    )
    if not rooted.is_ok():
        raise ToolRefused(rooted.error or "the command did not run", rooted.hint or "")
    result = rooted.unwrap()
    ctx.runs.append(result)
    outcome = (
        "passed"
        if result.passed
        else ("killed: " + result.killed_by if result.killed_by else "failed")
    )
    tail = result.stdout[-4000:] if result.stdout else ""
    text = (
        f"{' '.join(result.argv)}: exit {result.exit_code}, {outcome}"
        + (" (fake runner: no command ran)" if result.runner == "fake" else "")
        + (f"\n{tail}" if tail else "")
        + (f"\nstderr:\n{result.stderr[-2000:]}" if result.stderr else "")
    )
    return ToolResult(
        text=text,
        facts={
            "exit_code": result.exit_code,
            "passed": result.passed,
            "killed_by": result.killed_by,
            "runner": result.runner,
            "rule_id": result.rule_id,
        },
        truncated=result.stdout_truncated or result.stderr_truncated,
    )


RUN_TESTS = ToolSpec(
    name="run_tests",
    tier=CapabilityTier.TIER_3_EXTERNAL,
    args_model=RunTestsArgs,
    mutates=True,
    result_cap_bytes=_RESULT_CAP,
    run=run_tests,
)

__all__ = ["RUN_TESTS", "RunTestsArgs", "run_tests"]
