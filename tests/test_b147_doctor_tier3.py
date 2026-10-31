"""B-147: `ract doctor --tier3` reports the tier-3 state and the fix for each problem.

One test per state the card names. Keys are throwaway, made in a temporary
user config per test; nothing is signed with the operator's key.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ract.doctor_tier3 import tier3_lines, tier3_report
from ract.policy.grant import sign
from ract.policy.operator_key import generate, unlock

PASS = "throwaway passphrase for a test"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    cfg = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ract.yaml").write_text("project:\n  name: x\n", encoding="utf-8")
    return root


def _policy(root: Path, key_id: str, *, issued: datetime, days: int = 30) -> None:
    (root / ".ract").mkdir(exist_ok=True)
    (root / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(root)}'\n"
        f"issued_at: {issued:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {issued + timedelta(days=days):%Y-%m-%dT%H:%M:%SZ}\n"
        f"key_id: {key_id}\n"
        "max_mode: ask\n"
        "sandbox: best_effort\n"
        "commands:\n  allow:\n    - id: tests\n      argv: [python, -m, pytest]\n",
        encoding="utf-8",
    )


def _signed(root: Path, *, issued: datetime | None = None, days: int = 30) -> None:
    key = generate(PASS)
    _policy(
        root,
        key.key_id,
        issued=issued or datetime.now(timezone.utc) - timedelta(hours=1),
        days=days,
    )
    sign(root, unlock(PASS), key)


def _fits(report: dict) -> None:
    for width in (80, 60, 40):
        assert all(len(line) <= width for line in tier3_lines(report, width)), width


def test_no_grant(project: Path) -> None:
    report = tier3_report(project)
    assert report["tier3"] == "off" and report["grant"]["status"] == "none"
    assert "ract policy init --guided" in report["next"]
    assert all("tier 3 is off" in how for how in report["tools"].values())
    _fits(report)


def test_unsigned(project: Path) -> None:
    key = generate(PASS)
    _policy(project, key.key_id, issued=datetime.now(timezone.utc) - timedelta(hours=1))
    report = tier3_report(project)
    assert report["grant"]["status"] == "unsigned"
    assert report["next"][0] == "ract policy sign"
    _fits(report)


def test_expired(project: Path) -> None:
    _signed(project, issued=datetime.now(timezone.utc) - timedelta(days=40), days=30)
    report = tier3_report(project)
    assert report["grant"]["status"] == "expired" and report["tier3"] == "off"
    assert report["next"][0].startswith("ract policy sign")
    _fits(report)


def test_suspended(project: Path, monkeypatch) -> None:
    from ract.policy import grant as grant_module
    from ract.policy.tier3 import suspend

    _signed(project)
    real = grant_module.load_grant
    monkeypatch.setattr(
        grant_module, "load_grant", lambda p, **kw: suspend(real(p, **kw))
    )
    report = tier3_report(project)
    assert report["grant"]["status"] == "suspended"
    assert report["next"][0].startswith("/permissions resume")
    _fits(report)


def test_holding(project: Path) -> None:
    # A repository, so the entry points can be listed and recorded at signing.
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    _signed(project)
    report = tier3_report(project)
    assert report["tier3"] == "on (ask)" and report["grant"]["holds"]
    assert report["tools"]["run_tests"].startswith("available")
    assert "add-rule lint" in report["tools"]["run_lint"]
    assert "allow_domains" in report["tools"]["web_fetch"]
    assert report["entry_points"]["recorded"] is True
    assert report["next"] == [] or all("keygen" not in f for f in report["next"])
    _fits(report)


def test_holding_outside_a_repository_says_every_command_asks(project: Path) -> None:
    _signed(project)
    report = tier3_report(project)
    assert report["grant"]["holds"] and report["entry_points"]["recorded"] is False
    text = "\n".join(tier3_lines(report, 80))
    assert "not recorded for this grant; every command asks" in text


@pytest.mark.parametrize("confined", [False, True], ids=["best_effort", "enforced"])
def test_the_sandbox_as_this_machine_runs_it(
    project: Path, monkeypatch, confined: bool
) -> None:
    import ract.cli as cli

    fake = {
        "platform": "Linux",
        "backend": "bubblewrap" if confined else "none",
        "backend_binary_found": confined,
        "tier3_commands": "enforced" if confined else "best_effort",
        "why_not": "" if confined else "no backend",
        "confines": {"files": "outside the step worktree"} if confined else {},
        "not_enforced": [] if confined else ["files and network for tier-3 commands"],
        "grant": "",
    }
    monkeypatch.setattr(cli, "sandbox_report", lambda system=None: fake)
    text = "\n".join(tier3_lines(tier3_report(project), 80))
    # MASON's screen (ui/tier3_report.py) words it.
    assert f"backend: {fake['backend']} ({fake['tier3_commands']})" in text
    assert ("does not confine: files and network" in text) is not confined


def test_the_cli_prints_the_report_and_its_json(project: Path, tmp_path: Path) -> None:
    env = {
        **os.environ,
        "APPDATA": str(tmp_path / "user-config"),
        "XDG_CONFIG_HOME": str(tmp_path / "user-config"),
        "PYTHONPATH": str(REPO / "src"),
        "COLUMNS": "60",
    }
    run = [
        sys.executable,
        "-m",
        "ract.cli",
        "doctor",
        "--tier3",
        "--config",
        "ract.yaml",
    ]
    text = subprocess.run(
        run, cwd=project, env=env, capture_output=True, text=True, timeout=120
    )
    assert text.returncode == 0, text.stderr
    assert "why tier 3 is off: no grant" in text.stdout and "to fix:" in text.stdout
    data = subprocess.run(
        run + ["--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert json.loads(data.stdout)["tier3"]["grant"]["status"] == "none"
