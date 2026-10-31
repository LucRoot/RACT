"""``ract policy init --guided``: from no grant to a signed test rule (ADR-0048 D13).

LR:: The guided flow detects the project's test runner, proposes the
narrowest rule for it (for pytest ``[python, -m, pytest]``, network off, a
15-minute limit), explains each field in one line, shows the resulting
``.ract/policy.yaml`` as a diff, and on one yes writes it and signs it. A
machine with no operator key gets one first, and the same passphrase signs,
so the operator types it once (twice to confirm a new one). The mode stays
``ask``: every command still asks before it runs. On Windows the grant says
``sandbox: best_effort`` and the flow says what that means. Nothing runs a
command here; nothing is written before the yes.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ract.policy.grant import (
    DEFAULT_DAYS,
    POLICY_FILE,
    parse_policy,
    sandbox_confines_commands,
    sign,
)
from ract.policy.operator_key import NoOperatorKey, generate, load_public, unlock

Ask = Callable[[str], "str | None"]
Show = Callable[[str], None]
ReadPassphrase = Callable[..., str]


@dataclass(frozen=True)
class Runner:
    """A detected test runner: its rule id, argv and what it was found by."""

    rule_id: str
    argv: tuple[str, ...]
    found_by: str


def detect_runner(project: Path) -> Runner | None:
    """The project's test runner from its files; None when none is recognized."""
    markers = [
        name
        for name in ("pytest.ini", "conftest.py", "tests/conftest.py", "tox.ini")
        if (project / name).is_file()
    ]
    pyproject = project / "pyproject.toml"
    if pyproject.is_file() and "[tool.pytest" in pyproject.read_text(
        encoding="utf-8", errors="replace"
    ):
        markers.append("pyproject.toml [tool.pytest]")
    tests_dir = project / "tests"
    if tests_dir.is_dir() and any(tests_dir.glob("test_*.py")):
        markers.append("tests/test_*.py")
    if markers:
        return Runner("tests", ("python", "-m", "pytest"), ", ".join(markers))
    package = project / "package.json"
    if package.is_file():
        import json

        try:
            scripts = (
                json.loads(package.read_text(encoding="utf-8")).get("scripts") or {}
            )
        except (OSError, ValueError, AttributeError) as exc:
            print(f"[guided] package.json not read: {exc}", flush=True)
            scripts = {}
        if isinstance(scripts, dict) and scripts.get("test"):
            return Runner("tests", ("npm", "test"), "package.json scripts.test")
    return None


def _repo_root(project: Path) -> str | None:
    from ract.executor.worktree import repo_root_commit

    return repo_root_commit(project)


def proposed_policy(project: Path, runner: Runner, key_id: str, now: datetime) -> str:
    """The narrowest grant for *runner*, as the YAML the operator will sign."""
    sandbox = "enforced" if sandbox_confines_commands() else "best_effort"
    root_commit = _repo_root(project)
    argv = ", ".join(runner.argv)
    lines = [
        "version: 1",
        "binding:",
        # G-217 G2: a single-quoted YAML scalar writes ' as ''.
        "  project_root: '" + os.path.realpath(project).replace("'", "''") + "'",
    ]
    if root_commit:
        lines.append(f"  repo_root_commit: {root_commit}")
    lines += [
        f"issued_at: {now:%Y-%m-%dT%H:%M:%SZ}",
        f"expires_at: {now + timedelta(days=DEFAULT_DAYS):%Y-%m-%dT%H:%M:%SZ}",
        f"key_id: {key_id}",
        "max_mode: ask",
        f"sandbox: {sandbox}",
        "commands:",
        "  allow:",
        f"    - id: {runner.rule_id}",
        f"      argv: [{argv}]",
        "      network: false",
        "      cwd: step_worktree",
        "      timeout_s: 900",
        "      home: isolated",
        "  deny:",
        "    - argv: [git, push]",
    ]
    return "\n".join(lines) + "\n"


def explanations(runner: Runner) -> list[str]:
    """One line per field the operator is asked to sign (D13)."""
    confined = sandbox_confines_commands()
    # G-217 G1: without a sandbox these are what the rule declares, not facts.
    lines = [
        f"argv [{', '.join(runner.argv)}]: only this command, with any arguments after it, may run",
        "network: false: it runs with the network off"
        if confined
        else "network: false: declared off; this machine does not enforce it",
        "timeout_s: 900: it is stopped after 15 minutes",
        "cwd: step_worktree: it runs in the step's worktree, never in your files"
        if confined
        else "cwd: step_worktree: it starts in the step's worktree; nothing stops it "
        "reaching your other files",
        "home: isolated: it gets an empty home folder, not yours",
        "max_mode: ask: every command still asks you before it runs",
        "deny [git, push]: never runs, whatever else allows it",
        f"expires in {DEFAULT_DAYS} days; `ract policy sign` renews it",
    ]
    if confined:
        lines.append(
            "sandbox: enforced: the command is confined to what the rule allows"
        )
    else:
        lines.append(
            "sandbox: best_effort: this machine cannot confine commands, so the "
            "network and file limits are not enforced here; the grant says so, and "
            "the command runs with your user's rights"
        )
    return lines


def guided_init(
    project: Path,
    *,
    ask: Ask,
    show: Show,
    read_passphrase: ReadPassphrase,
    width: int = 80,
    now: datetime | None = None,
) -> int:
    """Run the guided flow; the exit code (0 signed, 1 declined, 2 nothing to propose)."""
    from ract.diff_render import render_hunks

    from ract.ui.grant_screens import (
        DetectedRunner,
        ProposedRule,
        detected_runner_lines,
        policy_diff_lines,
        proposed_rule_lines,
        signed_result_lines,
    )

    now = now or datetime.now(timezone.utc)
    runner = detect_runner(project)
    if runner is None:
        # MASON's view (B-111), then where to go from here.
        for line in detected_runner_lines(None, width):
            show(line)
        show("hint: write .ract/policy.yaml by hand, then run `ract policy sign`")
        return 2
    for line in detected_runner_lines(
        DetectedRunner(" ".join(runner.argv), runner.argv, runner.found_by), width
    ):
        show(line)
    try:
        key = load_public()
        has_key = True
    except NoOperatorKey:
        key, has_key = None, False
    key_id = key.key_id if key is not None else "ed25519:0000000000000000"
    text = proposed_policy(project, runner, key_id, now)
    # G-217 G2: a policy that cannot hold fails here, before the question and
    # before any key is made.
    parse_policy(text)
    # MASON's rule view, then the grant-wide fields D13 also asks to explain.
    for line in proposed_rule_lines(
        ProposedRule(
            rule_id=runner.rule_id,
            argv=runner.argv,
            network=False,
            timeout_minutes=15,
            cwd="step_worktree",
            home="isolated",
            sandbox_enforced=sandbox_confines_commands(),
        ),
        width,
    ):
        show(line)
    for line in explanations(runner):
        if line.startswith(("max_mode", "deny", "expires", "sandbox")):
            show(f"  {line}")
    path = project / ".ract" / POLICY_FILE
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    # With no key yet, its id is unknown until the yes: say so in the preview.
    preview = (
        text
        if has_key
        else text.replace(
            f"key_id: {key_id}", "key_id: (your new key, made when you answer yes)"
        )
    )
    for line in policy_diff_lines(
        render_hunks(f".ract/{POLICY_FILE}", old, preview, width=width), width
    ):
        show(line)
    if not has_key:
        show(
            "There is no operator key on this machine: one is created first, outside this project."
        )
    answer = (ask("Write this policy and sign it? [y/N] ") or "").strip().lower()
    if answer not in {"y", "yes"}:
        show("Nothing was written.")
        return 1
    if has_key:
        passphrase = read_passphrase("Passphrase: ")
        private = unlock(passphrase)
    else:
        passphrase = read_passphrase(
            "New passphrase (8 characters or more, 12 is better): ", confirm=True
        )
        key = generate(passphrase)
        from ract.policy.operator_key import passphrase_warning

        warning = passphrase_warning(passphrase)
        if warning:
            show(warning)
        text = proposed_policy(project, runner, key.key_id, now)
        private = unlock(passphrase)
    assert key is not None
    parse_policy(text)  # never write a policy that would not hold
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written whole: a temporary file beside it, then one replace.
    temp = path.with_name(f".{POLICY_FILE}.{os.getpid()}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    digest = sign(project, private, key)
    expires = (now + timedelta(days=DEFAULT_DAYS)).date().isoformat()
    for line in signed_result_lines(runner.rule_id, expires, "T3 ask", width):
        show(line)
    show(f"  .ract/{POLICY_FILE} signed with {key.key_id} (sha256 {digest[:12]})")
    return 0


__all__ = ["Runner", "detect_runner", "explanations", "guided_init", "proposed_policy"]
