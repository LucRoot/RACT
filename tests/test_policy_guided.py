"""B-111 (ADR-0048 D13): ``ract policy init --guided`` from no grant to a signed pytest rule.

The answers and the passphrase are throwaway strings; the user config is a
temporary folder per test. The real-terminal walk (under two minutes) is the
slice-b walkthrough.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ract.policy.grant import load_grant
from ract.policy.guided import detect_runner, explanations, guided_init
from ract.policy.operator_key import load_public

PASS = "throwaway passphrase for a test"
REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def user_config(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(folder))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(folder))
    return folder / "ract"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "calc"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_calc.py").write_text(
        "def test_x():\n    pass\n", encoding="utf-8"
    )
    return root


def _run(project: Path, answer: str) -> tuple[int, list[str], list[str]]:
    shown: list[str] = []
    passphrases: list[str] = []

    def read_passphrase(prompt: str = "", *, confirm: bool = False) -> str:
        passphrases.append(prompt)
        return PASS

    code = guided_init(
        project,
        ask=lambda _q: answer,
        show=shown.append,
        read_passphrase=read_passphrase,
        now=NOW,
    )
    return code, shown, passphrases


def test_a_new_user_reaches_a_signed_pytest_rule(
    project: Path, user_config: Path
) -> None:
    code, shown, passphrases = _run(project, "y")

    assert code == 0
    # One passphrase entry (confirmed once), for the new key and the signature.
    assert passphrases == ["New passphrase (8 characters or more, 12 is better): "]
    # MASON's detected-runner view (B-111).
    assert shown[0].startswith("found the test runner: python -m pytest")
    assert any("seen in: tests/test_*.py" in line for line in shown)
    assert any("there is no operator key" in line.lower() for line in shown)
    assert any(line.startswith("+") or " + " in line for line in shown)  # the diff
    state = load_grant(project, now=NOW)
    assert state.holds
    rule = state.policy.commands.allow[0]
    assert rule.argv == ["python", "-m", "pytest"] and rule.network is False
    assert rule.timeout_s == 900 and state.policy.max_mode == "ask"
    assert state.policy.key_id == load_public().key_id
    assert shown[-1].endswith("Tier 3: T3 ask.")


def test_declining_writes_nothing(project: Path, user_config: Path) -> None:
    code, shown, passphrases = _run(project, "n")
    assert code == 1 and shown[-1] == "Nothing was written."
    assert passphrases == []
    assert not (project / ".ract").exists()
    assert not (user_config / "operator").exists()  # no key either


def test_an_existing_key_signs_with_one_passphrase(
    project: Path, user_config: Path
) -> None:
    _run(project, "y")
    first = load_public()
    code, _shown, passphrases = _run(project, "y")
    assert code == 0 and passphrases == ["Passphrase: "]
    assert load_public() == first


def test_every_field_is_explained_in_one_line(project: Path) -> None:
    lines = explanations(detect_runner(project))
    for field in (
        "argv",
        "network",
        "timeout_s",
        "cwd",
        "home",
        "max_mode",
        "deny",
        "sandbox",
    ):
        assert any(line.startswith(field) for line in lines), field
    if os.name == "nt":
        assert any("cannot confine commands" in line for line in lines)


def test_no_runner_proposes_nothing(tmp_path: Path, user_config: Path) -> None:
    code, shown, _ = _run(tmp_path, "y")
    assert code == 2 and "No test runner found" in shown[0]
    assert not (tmp_path / ".ract").exists()


def test_an_npm_test_script_is_detected(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "jest"}}', encoding="utf-8"
    )
    assert detect_runner(tmp_path).argv == ("npm", "test")


def test_the_guided_flow_refuses_a_pipe(project: Path, tmp_path: Path) -> None:
    # G-217 S2: the command acts on the project the run reads (its ract.yaml).
    (project / "ract.yaml").write_text("providers: {}\n", encoding="utf-8")
    env = {
        **os.environ,
        "APPDATA": str(tmp_path / "cfg"),
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "PYTHONPATH": str(REPO / "src"),
    }
    done = subprocess.run(
        [sys.executable, "-m", "ract.cli", "policy", "init", "--guided"],
        input="y\n" + PASS + "\n" + PASS + "\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
        timeout=120,
    )
    assert done.returncode == 3, done.stdout + done.stderr
    assert "at a terminal" in done.stdout
    assert not (project / ".ract").exists()


def test_the_preview_never_shows_a_made_up_key_id(
    project: Path, user_config: Path
) -> None:
    _code, shown, _ = _run(project, "n")
    text = "\n".join(shown)
    assert "ed25519:0000000000000000" not in text
    assert "your new key, made when you answer yes" in text
