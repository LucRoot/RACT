"""B-112 (ADR-0048 D5, D10): run_command's core, through the scripted runner only.

No test runs a command (D-117): the scripted runner answers instead and
records what it was asked to run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.policy.matcher import Match
from ract.tools.command import TRACE_NOTE, ScriptedRunner, cap_output, run_command


class Rule:
    id = "tests"
    cwd = "step_worktree"
    timeout_s = 900
    max_output_bytes = 1_048_576
    home = "isolated"
    env_extra = ["PYTHONHASHSEED"]


def _match(argv=("python", "-m", "pytest")) -> Match:
    return Match("matches", "the rule tests", tuple(argv), "/usr/bin/python", "tests")


ENV = {
    "PATH": "/usr/bin",
    "PYTHONHASHSEED": "0",
    "GITHUB_TOKEN": "secret-value",
    "RACT_RUN_ID": "r1",
    "RACT_TIER_3_ENABLED": "1",
    "HOME": "/home/operator",
    "XDG_CONFIG_HOME": "/home/operator/.config",
}


def _run(tmp_path: Path, runner: ScriptedRunner, **kw):
    return run_command(
        _match(),
        worktree=tmp_path,
        rule=Rule(),
        runner=runner,
        process_env=ENV,
        project=tmp_path,
        **kw,
    )


def test_the_environment_is_scrubbed_and_home_is_the_steps(tmp_path: Path) -> None:
    runner = ScriptedRunner([{"exit_code": 0, "stdout": "1 passed"}])
    result = _run(tmp_path, runner).unwrap()
    env = runner.calls[0]["env"]
    assert "GITHUB_TOKEN" not in env  # never passed
    assert "RACT_TIER_3_ENABLED" not in env and env.get("RACT_RUN_ID") == "r1"
    assert env["PYTHONHASHSEED"] == "0"  # the rule's env_extra
    assert env["HOME"] != "/home/operator" and env["HOME"] == env["XDG_CONFIG_HOME"]
    assert "secret-value" not in json.dumps(result.env_names)
    assert result.passed and result.runner == "fake"


def test_network_off_is_asked_of_the_command_and_said_not_enforced(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner([{"exit_code": 0}])
    result = _run(tmp_path, runner).unwrap()
    assert runner.calls[0]["env"]["HTTPS_PROXY"] == "http://127.0.0.1:9"
    assert result.network == "off (not enforced)"
    assert any("not enforced" in n for n in result.notes)
    assert not result.enforced and result.sandbox == "none"


def test_the_command_is_the_resolved_executable_and_never_a_shell(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner([{"exit_code": 0}])
    _run(tmp_path, runner)
    assert runner.calls[0]["argv"] == ["/usr/bin/python", "-m", "pytest"]
    assert runner.calls[0]["cwd"] == str(tmp_path)


def test_a_timeout_is_recorded_as_a_kill(tmp_path: Path) -> None:
    runner = ScriptedRunner([{"exit_code": None, "killed_by": "timeout"}])
    result = _run(tmp_path, runner, timeout_s=5).unwrap()
    assert result.killed_by == "timeout" and not result.passed
    assert result.limits["wall_s"] == 5  # lowered, never raised past the rule


def test_the_session_cannot_raise_a_limit(tmp_path: Path) -> None:
    result = _run(tmp_path, ScriptedRunner([{}]), timeout_s=99_999).unwrap()
    assert result.limits["wall_s"] == 900


def test_output_is_capped_head_and_tail_and_escapes_are_stripped() -> None:
    text, cut = cap_output(b"\x1b[31mred\x1b[0m " + b"x" * 5000 + b" END", 200)
    assert cut and "\x1b" not in text and text.startswith("red ")
    assert text.endswith(" END") and "bytes dropped" in text


def test_the_record_holds_d10_and_no_output_text(tmp_path: Path, monkeypatch) -> None:
    from ract.key_paths import repo_key_dir

    runner = ScriptedRunner([{"exit_code": 1, "stdout": "FAILED test_add"}])
    result = _run(tmp_path, runner, approval_id="a1", approver="operator-tty").unwrap()
    assert TRACE_NOTE in _run(tmp_path, ScriptedRunner([{}])).assumption
    path = repo_key_dir(tmp_path, "commands").parent / "commands.jsonl"
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    for key in (
        "argv",
        "executable",
        "cwd",
        "env_names",
        "env_allowlist_digest",
        "rule_id",
        "approval_id",
        "approver",
        "sandbox",
        "enforced",
        "limits",
        "exit_code",
        "duration_ms",
        "killed_by",
        "stdout_bytes",
        "stdout_sha256",
        "stdout_truncated",
    ):
        assert key in record, key
    assert "stdout" not in record and "FAILED test_add" not in path.read_text(
        encoding="utf-8"
    )
    assert record["approver"] == "operator-tty" and not result.passed


def test_a_rule_cwd_outside_the_worktree_is_refused(tmp_path: Path) -> None:
    class Escaping(Rule):
        cwd = "step_worktree/../.."

    rooted = run_command(
        _match(),
        worktree=tmp_path,
        rule=Escaping(),
        runner=ScriptedRunner([{}]),
        process_env=ENV,
    )
    assert not rooted.is_ok() and "leaves the step worktree" in rooted.error


def test_the_fake_runner_is_chosen_only_by_its_variable(
    tmp_path: Path, monkeypatch
) -> None:
    from ract.tools.command import ProcessRunner, default_runner

    monkeypatch.delenv("RACT_FAKE_RUNNER", raising=False)
    # B-114: where no sandbox confines commands, the plain runner.
    monkeypatch.setattr(
        "ract.security.command_sandbox.runner_for", lambda *a, **k: None
    )
    assert isinstance(default_runner(), ProcessRunner)
    script = tmp_path / "script.json"
    script.write_text('[{"exit_code": 0}]', encoding="utf-8")
    monkeypatch.setenv("RACT_FAKE_RUNNER", str(script))
    assert default_runner().name == "fake"
    monkeypatch.setenv("RACT_FAKE_RUNNER", str(tmp_path / "missing.json"))
    with pytest.raises(RuntimeError):
        default_runner()
