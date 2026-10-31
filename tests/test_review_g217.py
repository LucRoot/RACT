"""G-217 (the MANAGER's senior review, part 5): S1, S2, G1, G2.

Keys and passphrases are throwaways in temporary folders; nothing runs.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ract.policy import cli as policy_cli
from ract.policy import guided
from ract.policy.grant import PolicyInvalid, load_grant
from ract.policy.operator_key import NoOperatorKey, load_public

PASS = "throwaway passphrase for a test"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
REAL_CONFIRM = policy_cli._confirm


@pytest.fixture
def user_config(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(folder))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(folder))
    return folder / "ract"


@pytest.fixture
def prompts(monkeypatch) -> list[str]:
    asked: list[str] = []

    def read_passphrase(prompt: str = "Passphrase: ", *, confirm: bool = False) -> str:
        asked.append(prompt)
        return PASS

    monkeypatch.setattr(policy_cli, "read_passphrase", read_passphrase)
    return asked


def _project(tmp_path: Path, monkeypatch, prompts: list[str]) -> Path:
    from ract.policy.unlock import SESSION_WINDOW

    # The unlock window is per process: another test may have left it open.
    SESSION_WINDOW.lock()
    monkeypatch.setattr(policy_cli, "_confirm", lambda _q: True)
    assert policy_cli.policy_command(["keygen"]) == 0
    prompts.clear()
    key = load_public()
    project = tmp_path / "project"
    (project / ".ract").mkdir(parents=True)
    (project / "ract.yaml").write_text("providers: {}\n", encoding="utf-8")
    (project / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(project)}'\n"
        "issued_at: 2026-10-30T10:00:00Z\n"
        "expires_at: 2027-01-28T10:00:00Z\n"
        f"key_id: {key.key_id}\n"
        "sandbox: best_effort\n"
        "commands:\n  allow:\n    - id: tests\n      argv: [python, -m, pytest]\n"
        "  deny:\n    - argv: [git, push]\n",
        encoding="utf-8",
    )
    return project


# ---------------------------------------------------------------- S1


@pytest.mark.parametrize("answer", ["n", "", None], ids=["no", "empty", "eof"])
def test_s1_sign_shows_the_policy_and_a_no_signs_nothing(
    tmp_path: Path, user_config: Path, prompts: list[str], monkeypatch, capsys, answer
) -> None:
    project = _project(tmp_path, monkeypatch, prompts)
    monkeypatch.chdir(project)
    monkeypatch.setattr(policy_cli, "_confirm", REAL_CONFIRM)  # the real question

    def read_line(_question: str) -> str:
        if answer is None:
            raise EOFError
        return answer

    monkeypatch.setattr("ract.console_interrupt.read_line", read_line)
    capsys.readouterr()
    assert policy_cli.policy_command(["sign"]) == 1
    out = capsys.readouterr().out
    assert (
        "allow tests: python -m pytest (network off, 900 s, cwd step_worktree, home isolated)"
        in out
    )
    assert "deny: git push" in out and "max mode ask; expires 2027-01-28" in out
    assert "not enforced on this machine" in out and "Nothing was signed." in out
    assert prompts == [] and not (project / ".ract" / "policy.yaml.sig").exists()


def test_s1_a_yes_asks_the_passphrase_and_signs(
    tmp_path: Path, user_config: Path, prompts: list[str], monkeypatch, capsys
) -> None:
    project = _project(tmp_path, monkeypatch, prompts)
    monkeypatch.chdir(project)
    assert policy_cli.policy_command(["sign"]) == 0
    assert prompts and (project / ".ract" / "policy.yaml.sig").is_file()


# ---------------------------------------------------------------- S2


def test_s2_from_a_subfolder_it_acts_on_the_projects_policy(
    tmp_path: Path, user_config: Path, prompts: list[str], monkeypatch, capsys
) -> None:
    project = _project(tmp_path, monkeypatch, prompts)
    deep = project / "src" / "pkg"
    deep.mkdir(parents=True)
    (deep / ".ract").mkdir()  # a stray folder with no policy, never the target
    monkeypatch.chdir(deep)
    capsys.readouterr()
    assert policy_cli.policy_command(["sign"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"project: {project.resolve()}"
    assert (project / ".ract" / "policy.yaml.sig").is_file()
    assert not (deep / ".ract" / "policy.yaml.sig").exists()


def test_s2_with_no_project_it_refuses(
    tmp_path: Path, user_config: Path, monkeypatch, capsys
) -> None:
    lonely = tmp_path / "nowhere"
    lonely.mkdir()
    monkeypatch.chdir(lonely)
    monkeypatch.setattr(policy_cli, "find_project", lambda _start: None)
    assert policy_cli.policy_command(["status"]) == 2
    assert "no project here" in capsys.readouterr().out


def test_s2_find_project_prefers_ract_yaml_then_the_git_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "a" / "b").mkdir(parents=True)
    assert policy_cli.find_project(root / "a" / "b") == root.resolve()
    (root / "a" / "ract.yaml").write_text("", encoding="utf-8")
    assert policy_cli.find_project(root / "a" / "b") == (root / "a").resolve()


# ---------------------------------------------------------------- G1


@pytest.fixture
def runner_project(tmp_path: Path) -> Path:
    root = tmp_path / "calc"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_calc.py").write_text(
        "def test_x():\n    pass\n", encoding="utf-8"
    )
    return root


@pytest.mark.parametrize("confined", [False, True])
def test_g1_the_explanation_says_what_the_machine_does(
    runner_project: Path, monkeypatch, confined: bool
) -> None:
    monkeypatch.setattr(guided, "sandbox_confines_commands", lambda: confined)
    lines = guided.explanations(guided.detect_runner(runner_project))
    network = next(line for line in lines if line.startswith("network"))
    cwd = next(line for line in lines if line.startswith("cwd"))
    if confined:
        assert network == "network: false: it runs with the network off"
        assert "never in your files" in cwd
    else:
        assert (
            network == "network: false: declared off; this machine does not enforce it"
        )
        assert "nothing stops it reaching your other files" in cwd
        assert any("runs with your user's rights" in line for line in lines)


# ---------------------------------------------------------------- G2


def _guided(project: Path, answers: list[str]) -> tuple[int, list[str], list[str]]:
    shown: list[str] = []
    asked: list[str] = []

    def ask(question: str) -> str:
        asked.append(question)
        return answers.pop(0) if answers else ""

    code = guided.guided_init(
        project,
        ask=ask,
        show=shown.append,
        read_passphrase=lambda prompt="", *, confirm=False: PASS,
        now=NOW,
    )
    return code, shown, asked


def test_g2_a_project_path_with_an_apostrophe_holds(
    tmp_path: Path, user_config: Path
) -> None:
    project = tmp_path / "it's here"
    (project / "tests").mkdir(parents=True)
    (project / "tests" / "test_calc.py").write_text(
        "def test_x():\n    pass\n", encoding="utf-8"
    )
    code, _shown, _asked = _guided(project, ["y"])
    assert code == 0
    assert load_grant(project, now=NOW).holds


def test_g2_a_preview_that_cannot_hold_fails_before_the_question_and_the_key(
    runner_project: Path, user_config: Path, monkeypatch
) -> None:
    good = guided.proposed_policy
    monkeypatch.setattr(
        guided,
        "proposed_policy",
        lambda *a, **kw: good(*a, **kw).replace(
            "max_mode: ask", "max_mode: everything"
        ),
    )
    asked: list[str] = []
    with pytest.raises(PolicyInvalid):
        guided.guided_init(
            runner_project,
            ask=lambda q: asked.append(q) or "y",
            show=lambda _line: None,
            read_passphrase=lambda prompt="", *, confirm=False: PASS,
            now=NOW,
        )
    assert asked == []
    with pytest.raises(NoOperatorKey):
        load_public()
    assert not (runner_project / ".ract" / "policy.yaml").exists()


def test_g2_the_policy_is_written_whole(
    runner_project: Path, user_config: Path
) -> None:
    code, _shown, _asked = _guided(runner_project, ["y"])
    assert code == 0
    leftovers = [
        p.name for p in (runner_project / ".ract").iterdir() if p.name.endswith(".tmp")
    ]
    assert leftovers == []
