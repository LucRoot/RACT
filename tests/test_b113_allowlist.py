"""B-113 (slice d): allowlist mode, session approvals, changed entry points ask.

Commands go to the scripted runner only; keys are throwaways in temporary
folders; the project is a temporary git repository.
"""

from __future__ import annotations

import os
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ract.policy import tier3
from ract.policy.allowlist import CHANGED, WRITTEN, SessionApprovals
from ract.policy.grant import PolicyInvalid, parse_policy, sign
from ract.policy.operator_key import generate, unlock
from ract.tools import run_tool
from ract.tools.command import ScriptedRunner

PASS = "throwaway passphrase for a test"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    cfg = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    root = tmp_path / "calc"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_calc.py").write_text(
        "def test_add():\n    pass\n", encoding="utf-8"
    )
    (root / "conftest.py").write_text("", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "c")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / ("python.exe" if os.name == "nt" else "python")
    exe.write_text("", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    return root


def _grant(root: Path, max_mode: str = "allowlist") -> None:
    key = generate(PASS)
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    (root / ".ract").mkdir(exist_ok=True)
    (root / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(root)}'\n"
        f"issued_at: {now:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {now + timedelta(days=30):%Y-%m-%dT%H:%M:%SZ}\n"
        f"key_id: {key.key_id}\n"
        f"max_mode: {max_mode}\n"
        "sandbox: best_effort\n"
        "commands:\n  allow:\n    - id: tests\n      argv: [python, -m, pytest]\n",
        encoding="utf-8",
    )
    sign(root, unlock(PASS), key)


def _call(root: Path, *, mode="allowlist", answer=True, sessions=None, written=()):
    asked: list[dict] = []
    runner = ScriptedRunner([{"exit_code": 0}])
    ctx = tier3.for_project(
        root,
        lambda facts: asked.append(facts) or answer,
        runner,
        mode=mode,
        session_approvals=sessions,
    )
    ctx.model_written.update(written)
    with tier3.bound(ctx):
        rooted = run_tool(root, "run_tests", {})
    return rooted, asked, runner


def test_a_matching_command_runs_without_asking_in_allowlist(project: Path) -> None:
    _grant(project)
    rooted, asked, runner = _call(project)
    assert rooted.is_ok(), rooted.error
    assert asked == [] and len(runner.calls) == 1
    assert rooted.unwrap().facts["approved_by"] == "allow-rule"


def test_ask_mode_still_asks(project: Path) -> None:
    _grant(project)
    rooted, asked, _runner = _call(project, mode="ask")
    assert rooted.is_ok() and len(asked) == 1


def test_the_grants_max_mode_caps_the_session(project: Path) -> None:
    _grant(project, max_mode="ask")
    _rooted, asked, _runner = _call(project, mode="allowlist")
    assert len(asked) == 1


def test_a_changed_conftest_asks_even_under_a_matching_rule(project: Path) -> None:
    _grant(project)
    (project / "conftest.py").write_text("import os\n", encoding="utf-8")
    _rooted, asked, _runner = _call(project)
    assert len(asked) == 1
    assert ("conftest.py", CHANGED) in asked[0]["entry_points"]
    assert asked[0]["session_choice"] is False


def test_a_test_file_written_by_the_model_asks(project: Path) -> None:
    _grant(project)
    _rooted, asked, _runner = _call(project, written={"tests/test_new.py"})
    assert len(asked) == 1
    assert ("tests/test_new.py", WRITTEN) in asked[0]["entry_points"]


def test_a_grant_with_no_signing_record_counts_every_entry_point_changed(
    project: Path,
) -> None:
    from ract.key_paths import repo_key_dir

    _grant(project)
    for record in repo_key_dir(project, "grants").glob("*.entrypoints.json"):
        record.unlink()
    _rooted, asked, _runner = _call(project)
    assert len(asked) == 1
    assert {p for p, _ in asked[0]["entry_points"]} >= {
        "conftest.py",
        "tests/test_calc.py",
    }


def test_a_session_approval_runs_again_without_asking_then_ends_with_the_session(
    project: Path,
) -> None:
    _grant(project, max_mode="ask")
    sessions = SessionApprovals()
    _rooted, asked, _runner = _call(
        project, mode="ask", answer="session", sessions=sessions
    )
    assert len(asked) == 1 and asked[0]["session_choice"] is True
    rooted, asked, runner = _call(project, mode="ask", sessions=sessions)
    assert asked == [] and rooted.unwrap().facts["approved_by"] == "session"
    # A new session starts with none.
    _rooted, asked, _runner = _call(project, mode="ask", sessions=SessionApprovals())
    assert len(asked) == 1


def test_unrestricted_is_refused_at_load() -> None:
    text = (
        "version: 1\nbinding:\n  project_root: 'x'\n"
        "issued_at: 2026-10-30T10:00:00Z\nexpires_at: 2026-11-30T10:00:00Z\n"
        "key_id: ed25519:0123456789abcdef\nmax_mode: unrestricted\nsandbox: best_effort\n"
    )
    with pytest.raises(PolicyInvalid):
        parse_policy(text)


@pytest.mark.parametrize(
    "offered, typed, expected",
    [(True, "s", "session"), (True, "y", True), (False, "s", False), (True, "", False)],
)
def test_the_console_prompt_offers_session_only_when_asked_to(
    monkeypatch, capsys, offered, typed, expected
) -> None:
    from ract.approval_callback import console_tier_3_prompt

    monkeypatch.setattr("ract.approval_callback.read_line", lambda _p: typed)
    facts = {
        "argv": ["python", "-m", "pytest"],
        "executable": "/usr/bin/python",
        "session_choice": offered,
        "entry_points": [] if offered else [("conftest.py", CHANGED)],
    }
    assert console_tier_3_prompt(facts) == expected
    out = capsys.readouterr().out
    assert ("s for this session" in out) is offered
    if not offered:
        assert (
            "file: conftest.py" in out and "an allow rule does not answer for it" in out
        )


def test_a_project_whose_entry_points_cannot_be_listed_asks(
    project, monkeypatch
) -> None:
    """Self-review of B-113: not knowing what would run is not a match."""
    import ract.policy.allowlist as allowlist

    _grant(project)
    monkeypatch.setattr(allowlist, "entry_point_digests", lambda root: None)
    _rooted, asked, _runner = _call(project)
    assert len(asked) == 1 and (".", allowlist.UNKNOWN) in asked[0]["entry_points"]


def test_test_files_in_folders_pytest_skips_are_not_entry_points(project) -> None:
    from ract.policy.allowlist import entry_point_digests

    (project / ".venv" / "lib").mkdir(parents=True)
    (project / ".venv" / "lib" / "test_site.py").write_text("", encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "conftest.py").write_text("", encoding="utf-8")
    digests = entry_point_digests(project)
    assert "tests/test_calc.py" in digests and "conftest.py" in digests
    assert not [p for p in digests if p.startswith((".venv/", "node_modules/"))]


@pytest.mark.parametrize(
    "path",
    [
        ".pytest.ini",
        "pytest.toml",
        "Makefile",
        "setup.py",
        "pytest.py",
        "eslint.config.mjs",
        ".eslintrc.cjs",
        "src/calc.test.ts",
        "web/__tests__/a.js",
    ],
)
def test_more_files_decide_what_runs(path: str) -> None:
    """Review finding 3: files a runner or verifier runs or reads, and a top-level
    module that would shadow ``python -m``."""
    from ract.policy.allowlist import is_entry_point

    assert is_entry_point(path)


def test_src_code_is_not_an_entry_point() -> None:
    from ract.policy.allowlist import is_entry_point

    assert not is_entry_point("src/calc.py") and not is_entry_point("docs/a.md")
