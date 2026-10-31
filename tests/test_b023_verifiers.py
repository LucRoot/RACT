"""B-023: build, lint, typecheck and format run under the grant and feed the gates.

No test runs a command: the scripted runner answers, or a stand-in counted as
real (name ``process``) that executes nothing. Keys are throwaways.
"""

from __future__ import annotations

import os
import stat
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ract.policy import tier3
from ract.policy.grant import sign
from ract.policy.operator_key import generate, unlock
from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from ract.tools import run_tool
from ract.tools.command import RawRun, ScriptedRunner
from ract.tools.verifier_tools import KNOWN, rule_for
from tests.test_j4_named_test_runs import ws  # noqa: F401 (fixture)

PASS = "throwaway passphrase for a test"
RULES = {
    "build": "[python, -m, build]",
    "lint": "[ruff, check]",
    "typecheck": "[mypy]",
    "format": "[ruff, format, --check]",
}


def _grant(root: Path, kinds=tuple(RULES)) -> None:
    key = generate(PASS)
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    allow = "".join(f"    - id: {k}\n      argv: {RULES[k]}\n" for k in kinds)
    (root / ".ract").mkdir(exist_ok=True)
    (root / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(root)}'\n"
        f"issued_at: {now:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {now + timedelta(days=30):%Y-%m-%dT%H:%M:%SZ}\n"
        f"key_id: {key.key_id}\n"
        "sandbox: best_effort\n"
        f"commands:\n  allow:\n{allow}"
        "  deny:\n    - argv: [ruff, check, --fix]\n",
        encoding="utf-8",
    )
    sign(root, unlock(PASS), key)


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    cfg = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    root = tmp_path / "calc"
    (root / "src").mkdir(parents=True)
    (root / "src" / "calc.py").write_text("x = 1\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("python", "ruff", "mypy"):
        exe = bin_dir / (f"{name}.exe" if os.name == "nt" else name)
        exe.write_text("", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir))
    return root


def _call(root: Path, kind: str, runner, **args):
    ctx = tier3.for_project(root, approve=lambda facts: True, runner=runner)
    with tier3.bound(ctx):
        return run_tool(root, f"run_{kind}", args), ctx


@pytest.mark.parametrize("kind", list(KNOWN))
def test_a_pass_is_structured(project: Path, kind: str) -> None:
    _grant(project)
    rooted, ctx = _call(
        project, kind, ScriptedRunner([{"exit_code": 0, "stdout": "ok"}])
    )
    assert rooted.is_ok(), rooted.error
    facts = rooted.unwrap().facts
    assert facts["kind"] == kind and facts["exit_code"] == 0 and facts["passed"]
    assert facts["command_id"].startswith("a-") and len(facts["output_sha256"]) == 64
    assert "duration_ms" in facts and facts["rule_id"] == kind and len(ctx.runs) == 1


@pytest.mark.parametrize("kind", list(KNOWN))
def test_a_fail_says_failed(project: Path, kind: str) -> None:
    _grant(project)
    rooted, _ctx = _call(
        project, kind, ScriptedRunner([{"exit_code": 1, "stdout": "E1"}])
    )
    assert rooted.is_ok()
    facts = rooted.unwrap().facts
    assert facts["exit_code"] == 1 and facts["passed"] is False


@pytest.mark.parametrize("kind", list(KNOWN))
def test_no_rule_says_not_run_because(project: Path, kind: str) -> None:
    _grant(project, kinds=tuple(k for k in RULES if k != kind))
    runner = ScriptedRunner([{}])
    rooted, _ctx = _call(project, kind, runner)
    assert not rooted.is_ok()
    assert f"not run, because the grant has no {kind} rule" in rooted.error
    assert runner.calls == []


@pytest.mark.parametrize("kind", list(KNOWN))
def test_the_matcher_refuses_an_option_or_a_path_outside(
    project: Path, kind: str
) -> None:
    _grant(project)
    runner = ScriptedRunner([{}])
    for bad in ("--fix", "../outside.py", "/etc/passwd"):
        rooted, _ctx = _call(project, kind, runner, paths=[bad])
        assert not rooted.is_ok() and "arguments refused" in rooted.error, bad
    assert runner.calls == []


def test_a_deny_rule_refuses_through_the_matcher(project: Path) -> None:
    _grant(project)
    from ract.tools.verifier_tools import VERIFIER_TOOLS  # noqa: F401 (registered)

    ctx = tier3.for_project(
        project, approve=lambda facts: True, runner=ScriptedRunner([{}])
    )
    rule = rule_for(ctx.grant.policy, "lint")
    assert list(rule.argv) == ["ruff", "check"]
    # The model may add only paths; the deny rule names --fix, which a path cannot be.
    from ract.policy.matcher import classify

    match = classify(["ruff", "check", "--fix"], ctx.grant.policy, project)
    assert match.outcome == "refused" and "denied" in match.reason


def test_a_rule_is_found_by_its_command_when_its_id_differs(project: Path) -> None:
    class Rule:
        def __init__(self, id, argv):
            self.id, self.argv = id, argv

    class Policy:
        class commands:
            allow = [Rule("checks", ["python", "-m", "mypy"]), Rule("x", ["make"])]

    assert rule_for(Policy, "typecheck").id == "checks"
    assert rule_for(Policy, "build").id == "x"
    assert rule_for(Policy, "lint") is None


class StandIn:
    """Counted as a real run (name ``process``); executes nothing."""

    name = "process"

    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code

    def run(self, argv, *, cwd, env, timeout_s):
        return RawRun(self.exit_code, b"out", b"", 7)


def _turn_with_a_lint_run(root: Path, monkeypatch, exit_code: int):
    """A turn whose step ran the lint tool once (the step's tool call, simulated)."""
    from ract import turn_context

    _grant(root)
    bin_dir = root.parent / "lint-bin"
    bin_dir.mkdir(exist_ok=True)
    ruff = bin_dir / ("ruff.exe" if os.name == "nt" else "ruff")
    ruff.write_text("", encoding="utf-8")
    ruff.chmod(ruff.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    original = turn_context.bind

    def bind(*a, **kw):
        if a and a[0] is None and kw.get("runs") is None:
            # B-192: the step's lint run follows its write, so it runs at the
            # end of the turn, while the turn's context is still bound; run at
            # the start it would be stale.
            ctx = tier3.for_project(
                root, approve=lambda facts: True, runner=StandIn(exit_code)
            )
            with tier3.bound(ctx):
                run_tool(root, "run_lint", {"reason": "check the change"})
        original(*a, **kw)

    monkeypatch.setattr("ract.session_turn.turn_context.bind", bind)
    monkeypatch.setattr("ract.approval_callback.read_line", lambda _p: "y")
    events: list[SessionEvent] = []
    stream = EventStream(session="s-b023")
    stream.subscribe(events.append)
    request = TurnRequest(
        config=root / "ract.yaml",
        intent="tidy src/calc.py",
        session_id="s-b023",
        resume=False,
        auto=True,
        terminal=True,
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    return code, events[-1].data


def test_a_failed_lint_run_keeps_the_turn_from_done(ws: Path, monkeypatch) -> None:  # noqa: F811
    code, finished = _turn_with_a_lint_run(ws, monkeypatch, 1)
    assert code == 1 and finished["outcome"] == "failed"
    assert finished["verdict"] == (
        "Not done: 1 step ran; the lint run `ruff check` failed (exit 1)."
    )


def test_a_passed_lint_run_lets_the_turn_be_done(ws: Path, monkeypatch) -> None:  # noqa: F811
    code, finished = _turn_with_a_lint_run(ws, monkeypatch, 0)
    assert code == 0 and finished["outcome"] == "done"
    assert finished["verification"]["status"] == "verified"
