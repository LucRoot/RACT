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

import re
import uuid
from typing import Any
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


def _test_rule(policy: object) -> Any | None:
    rules = list(getattr(getattr(policy, "commands", None), "allow", []) or [])
    for rule in rules:
        if rule.id == "tests":
            return rule
    runners = (["python", "-m", "pytest"], ["pytest"], ["npm", "test"])
    return next((r for r in rules if list(r.argv)[: len(r.argv)] in runners), None)


# Files a test runner executes or reads as configuration (G-214 T2).
_RUNNER_FILES = {
    "conftest.py",
    "pytest.ini",
    "pyproject.toml",
    "tox.ini",
    "setup.cfg",
    "package.json",
    "jest.config.js",
    "vitest.config.ts",
}


def _project_code_notes(written: set[str]) -> list[str]:
    """What the prompt says about the project code the command runs (G-214 T2)."""
    from ract.import_check import is_test_file

    mine = sorted(
        path
        for path in written
        if Path(path).name in _RUNNER_FILES or is_test_file(path)
    )
    note = (
        "this runs project code: the tests, conftest.py and the runner's configuration"
    )
    if mine:
        shown = ", ".join(mine[:6]) + (
            f" and {len(mine) - 6} more" if len(mine) > 6 else ""
        )
        note += f"; written in this session: {shown}"
    return [note]


def tier3_context() -> Any:
    """The step's tier-3 context with a grant that holds, or the refusal that says why."""
    from ract.policy import tier3

    ctx = tier3.current()
    if ctx is None:
        raise ToolRefused("tier 3 is off for this step", tier3.NO_GRANT_HINT)
    # G-216 W1: the pin is checked at each command, not only at the step's start.
    ctx.check_pin()
    if not ctx.grant.holds or ctx.grant.policy is None:
        raise ToolRefused(
            f"tier 3 is off: {ctx.grant.reason}",
            tier3.RESUME_HINT
            if ctx.grant.status == "suspended"
            else tier3.NO_GRANT_HINT,
        )
    return ctx


_SUMMARY = re.compile(r"=+ (.*?) in [0-9.]+s(?: \([^)]*\))? =+\s*$")
_COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)")
_FAILED = re.compile(r"^FAILED (\S+)(?: - (.*))?$")


def pytest_summary(stdout: str, duration_ms: int, exit_code: int | None) -> Any:
    """the RunSummary from pytest's own last summary line; None counts otherwise."""
    from ract.ui.command_screens import FailingTest, RunSummary

    counts: dict[str, int] | None = None
    for line in reversed(stdout.splitlines()):
        found = _SUMMARY.search(line.strip())
        if found:
            counts = {}
            for n, word in _COUNT.findall(found.group(1)):
                key = "failed" if word.startswith("error") else word
                counts[key] = counts.get(key, 0) + int(n)
            break
    failing = tuple(
        FailingTest(m.group(1), m.group(2) or "")
        for m in (_FAILED.match(line) for line in stdout.splitlines())
        if m
    )[:20]
    return RunSummary(
        passed=None if counts is None else counts.get("passed", 0),
        failed=None if counts is None else counts.get("failed", 0),
        skipped=None if counts is None else counts.get("skipped", 0),
        duration_s=duration_ms / 1000,
        exit_code=-1 if exit_code is None else exit_code,
        failing=failing,
    )


def run_tests(root: Path, args: RunTestsArgs) -> ToolResult:
    ctx = tier3_context()
    policy = ctx.grant.policy
    rule = _test_rule(policy)
    if rule is None:
        raise ToolRefused(
            "the grant has no test rule",
            "`ract policy init --guided` proposes one for this project's test runner",
        )
    # G-214 T1: a selector is never read as an option of the runner.
    is_pytest = "pytest" in [
        Path(a).name.lower().removesuffix(".exe") for a in rule.argv
    ]
    argv = [
        *rule.argv,
        *(["--"] if is_pytest and args.selectors else []),
        *args.selectors,
    ]
    return run_under_rule(
        root,
        ctx,
        rule,
        argv,
        args.reason,
        kind="tests",
        refused_hint="name tests inside the project",
        notes=_project_code_notes(ctx.model_written),
    )


def run_under_rule(
    root: Path,
    ctx: Any,
    rule: Any,
    argv: list[str],
    reason: str,
    *,
    kind: str,
    refused_hint: str,
    notes: list[str],
) -> ToolResult:
    """Classify, ask and run *argv* under *rule*: the one path every tier-3 tool takes.

    The result is structured (B-023): the kind, the command id, the exit
    code, the time, the output digest and the capped output. The run is kept
    on the step's context and on the turn, where the verifier counts it.
    """
    from ract import turn_context
    from ract.policy import tier3
    from ract.policy.matcher import classify
    from ract.tools.command import run_command

    policy = ctx.grant.policy

    match = classify(
        argv,
        policy,
        root,
        model_written=frozenset(ctx.model_written),
        also_outside=(ctx.project,),
    )
    if match.outcome == "refused":
        raise ToolRefused(f"refused: {match.reason}", refused_hint)
    # B-028 (D-142): a rule that names another backend never runs on this host.
    for named in (
        rule,
        *(
            r
            for r in getattr(getattr(policy, "commands", None), "allow", []) or []
            if r.id == match.rule_id
        ),
    ):
        backend = getattr(named, "backend", "host")
        if backend != "host":
            from ract.security.other_backends import why_not_wired

            raise ToolRefused(
                f"the rule {named.id!r} runs with backend {backend}, which this "
                f"release does not run yet ({why_not_wired(backend)}); "
                "nothing ran",
                "use a rule without a backend, or wait for the backend (B-028)",
            )
    if ctx.approve is None:
        # B-193: the approval nobody can answer is recorded as denied.
        turn_context.record_denial(
            "T3", " ".join(match.argv), rule=match.rule_id or "", reason=reason
        )
        raise ToolRefused(
            "tier 3 asks you before a command runs, and nobody can answer here",
            "run it in a session at a terminal; headless runs and --yolo never run tier 3",
        )
    # B-114: the lines say what the runner that will run it does.
    if ctx.runner is not None:
        confined = getattr(ctx.runner, "sandbox", None)
    else:
        from ract.security.command_sandbox import enforcing_backend

        backend, _why = enforcing_backend()
        confined = getattr(backend, "name", None)
    facts = {
        "argv": list(match.argv),
        "executable": match.executable,
        "cwd": "the step's worktree",
        "network": "on"
        if rule.network
        else "off"
        if confined
        else "off (not enforced on this machine)",
        "sandbox": f"enforced: {confined}"
        if confined
        else "best effort: not enforced on this machine",
        "rule": rule.id,
        "timeout_s": rule.timeout_s,
        "why": match.reason,
        "reason": reason,
        "notes": [*match.notes, *notes],
        # B-149: a proposal that came after fetched text says so on its card.
        "follows": turn_context.follows_external(),
    }
    # B-113 (D4, D6, G-214): what may run without the question.
    from ract.policy import allowlist

    # Read in the folder the command runs in (the step worktree): a file that
    # differs only there decides what runs too.
    changes = allowlist.changed_entry_points(
        root,
        ctx.grant.digest,
        ctx.model_written,
        record_project=ctx.project,
        argv=list(match.argv),
    )
    sessions = ctx.session_approvals
    approved_by = ""
    # Only the rule this tool runs under may answer for it.
    # B-149: a proposal that follows fetched text always asks: an allow rule
    # or a session answer never runs what a web page may have steered.
    steered = bool(facts["follows"])
    if (
        match.outcome == "matches"
        and match.rule_id == rule.id
        and not changes
        and not steered
    ):
        if ctx.mode == "allowlist":
            approved_by = "allow-rule"
        elif sessions is not None and sessions.covers(match.argv):
            approved_by = "session"
    if not approved_by:
        facts["entry_points"] = [(c.path, c.reason) for c in changes]
        # A session answer is offered only where an allow rule could answer.
        facts["session_choice"] = (
            sessions is not None
            and match.outcome == "matches"
            and match.rule_id == rule.id
            and not changes
            and not steered
        )
        answer = ctx.approve(facts)
        if not answer:
            raise ToolRefused(
                "you declined the command; nothing ran",
                "the model can ask again or stop",
            )
        if steered:
            turn_context.approved_after_external()
        if answer == "session" and facts["session_choice"]:
            sessions.add(match.argv)
            approved_by = "operator-tty, for this session"
        else:
            approved_by = "operator-tty"
    # The question can be open for minutes: the grant is checked again before the run.
    ctx.check_pin()
    if ctx.grant.status == "suspended":
        raise ToolRefused(
            f"tier 3 is off: {ctx.grant.reason}; nothing ran", tier3.RESUME_HINT
        )
    command_id = f"a-{uuid.uuid4().hex[:12]}"
    rooted = run_command(
        match,
        worktree=root,
        rule=rule,
        grant_digest=ctx.grant.digest,
        approval_id=command_id,
        approver=approved_by,
        runner=ctx.runner,
        network=bool(rule.network),
        project=ctx.project,
    )
    if not rooted.is_ok():
        raise ToolRefused(rooted.error or "the command did not run", rooted.hint or "")
    result = rooted.unwrap()
    ctx.runs.append(result)
    turn_context.record_run(kind, result)
    outcome = (
        "passed"
        if result.passed
        else ("killed: " + result.killed_by if result.killed_by else "failed")
    )
    tail = result.stdout[-4000:] if result.stdout else ""
    summary_text = ""
    if kind == "tests":
        # the result view (L-298 item 3): the counts first, each failure after.
        from ract.ui.command_screens import result_lines

        summary = pytest_summary(result.stdout, result.duration_ms, result.exit_code)
        summary_text = "\n".join(result_lines(summary, 10_000)) + "\n"
    text = summary_text + (
        f"{' '.join(result.argv)}: exit {result.exit_code}, {outcome}"
        + (" (fake runner: no command ran)" if result.runner == "fake" else "")
        + (f"\n{tail}" if tail else "")
        + (f"\nstderr:\n{result.stderr[-2000:]}" if result.stderr else "")
    )
    return ToolResult(
        text=text,
        facts={
            "kind": kind,
            "command_id": command_id,
            "approved_by": approved_by,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "output_sha256": result.stdout_sha256,
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

__all__ = ["RUN_TESTS", "RunTestsArgs", "run_tests", "run_under_rule", "tier3_context"]
