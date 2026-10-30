"""B-111: ``ract policy keygen | sign | status | revoke``.

Each test gets its own user config folder; the passphrase is a throwaway
string handed to the terminal reader, except where the test proves that a
pipe is refused.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ract.policy import cli as policy_cli
from ract.policy.operator_key import load_public

PASS = "throwaway passphrase for a test"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def user_config(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(folder))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(folder))
    return folder / "ract"


@pytest.fixture
def typed(monkeypatch) -> list[str]:
    prompts: list[str] = []

    def read_passphrase(prompt: str = "Passphrase: ", *, confirm: bool = False) -> str:
        prompts.append(prompt)
        return PASS

    monkeypatch.setattr(policy_cli, "read_passphrase", read_passphrase)
    # G-217 S1: sign shows the policy and asks; these tests answer yes.
    monkeypatch.setattr(policy_cli, "_confirm", lambda _question: True)
    return prompts


def _body(out: str) -> str:
    """The output after its first line, which names the project (G-217 S2)."""
    first, _, rest = out.partition("\n")
    assert first.startswith("project: "), first
    return rest


def _policy(project: Path, key_id: str, sandbox: str = "best_effort") -> str:
    return (
        "version: 1\n"
        "binding:\n"
        f"  project_root: '{os.path.realpath(project)}'\n"
        "issued_at: 2026-10-30T10:00:00Z\n"
        "expires_at: 2027-01-28T10:00:00Z\n"
        f"key_id: {key_id}\n"
        "max_mode: ask\n"
        f"sandbox: {sandbox}\n"
        "commands:\n"
        "  allow:\n"
        "    - id: tests\n"
        "      argv: [python, -m, pytest]\n"
    )


def test_keygen_sign_status_revoke(
    tmp_path: Path, user_config: Path, typed: list[str], capsys, monkeypatch
) -> None:
    assert policy_cli.policy_command(["keygen"]) == 0
    key = load_public()
    assert (user_config / "operator" / "operator.key.json").is_file()
    project = tmp_path / "project"
    (project / ".ract").mkdir(parents=True)
    (project / "ract.yaml").write_text("providers: {}\n", encoding="utf-8")
    monkeypatch.chdir(project)
    capsys.readouterr()

    assert policy_cli.policy_command(["status"]) == 0
    assert _body(capsys.readouterr().out).startswith("T3 off (no grant): no grant")

    (project / ".ract" / "policy.yaml").write_text(
        _policy(project, key.key_id), encoding="utf-8"
    )
    assert policy_cli.policy_command(["status"]) == 0
    assert "T3 off (no grant): the policy is not signed" in capsys.readouterr().out

    assert policy_cli.policy_command(["sign"]) == 0
    out = capsys.readouterr().out
    assert f"signed .ract/policy.yaml with {key.key_id}" in out
    assert "tier 3: T3 ask" in out

    assert policy_cli.policy_command(["status"]) == 0
    out = _body(capsys.readouterr().out)
    assert out.startswith("T3 ask")
    assert "sandbox: best_effort (commands are not confined on this machine)" in out
    assert "allow tests: python -m pytest (network off, 900 s)" in out

    assert policy_cli.policy_command(["revoke"]) == 0
    assert "stays refused" in capsys.readouterr().out
    policy_cli.policy_command(["status"])
    assert _body(capsys.readouterr().out).startswith(
        "T3 off (no grant): this grant was revoked"
    )


def test_sign_names_each_policy_problem(
    tmp_path: Path, user_config: Path, typed: list[str], capsys, monkeypatch
) -> None:
    policy_cli.policy_command(["keygen"])
    key = load_public()
    project = tmp_path / "project"
    (project / ".ract").mkdir(parents=True)
    (project / "ract.yaml").write_text("providers: {}\n", encoding="utf-8")
    monkeypatch.chdir(project)
    text = _policy(project, key.key_id).replace("[python, -m, pytest]", "[python]")
    (project / ".ract" / "policy.yaml").write_text(text, encoding="utf-8")
    capsys.readouterr()

    assert policy_cli.policy_command(["sign"]) == 2
    out = capsys.readouterr().out
    assert "policy.yaml:12 commands.allow[0].argv: ['python'] is too broad" in out
    assert not (project / ".ract" / "policy.yaml.sig").exists()


def test_a_grant_that_claims_enforcement_holds_nothing(
    tmp_path: Path, user_config: Path, typed: list[str], capsys, monkeypatch
) -> None:
    policy_cli.policy_command(["keygen"])
    key = load_public()
    project = tmp_path / "project"
    (project / ".ract").mkdir(parents=True)
    (project / "ract.yaml").write_text("providers: {}\n", encoding="utf-8")
    monkeypatch.chdir(project)
    (project / ".ract" / "policy.yaml").write_text(
        _policy(project, key.key_id, sandbox="enforced"), encoding="utf-8"
    )
    policy_cli.policy_command(["sign"])
    capsys.readouterr()
    policy_cli.policy_command(["status"])
    out = _body(capsys.readouterr().out)
    assert out.startswith("T3 off (no grant)")
    assert "must say sandbox: best_effort" in out


def test_rotate_belongs_to_keygen(user_config: Path, capsys) -> None:
    assert policy_cli.policy_command(["sign", "--rotate"]) == 2
    assert "--rotate belongs to `ract policy keygen`" in capsys.readouterr().out


def test_a_piped_passphrase_is_refused_by_the_real_command(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "APPDATA": str(tmp_path / "cfg"),
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "PYTHONPATH": str(REPO / "src"),
        "RACT_PASSPHRASE": PASS,  # no environment variable supplies it
    }
    done = subprocess.run(
        [sys.executable, "-m", "ract.cli", "policy", "keygen"],
        input=PASS + "\n" + PASS + "\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
    )
    assert done.returncode == 3, done.stdout + done.stderr
    assert "typed at a terminal" in done.stdout
    assert not (tmp_path / "cfg" / "ract" / "operator").exists()
