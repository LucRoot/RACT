"""B-142: the guided grant also proposes the lint, typecheck, format and build rules; add-rule.

The answers and the passphrase are throwaway strings and the user config is a
temporary folder per test (as in test_policy_guided). Nothing here runs a
command: the rules are proposed, signed and read back.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ract.policy.grant import load_grant
from ract.policy.guided import add_rule, detect_verifiers, guided_init
from ract.tools.verifier_tools import KNOWN, rule_for

PASS = "throwaway passphrase for a test"
REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def user_config(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(folder))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(folder))
    return folder / "ract"


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "proj"
    for rel, body in {"tests/test_a.py": "def test_a():\n    pass\n", **files}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def _guided(project: Path, answer: str = "y") -> tuple[int, list[str], list[str]]:
    shown: list[str] = []
    asked: list[str] = []

    def read_passphrase(prompt: str = "", *, confirm: bool = False) -> str:
        asked.append(prompt)
        return PASS

    code = guided_init(
        project,
        ask=lambda _q: answer,
        show=shown.append,
        read_passphrase=read_passphrase,
        now=NOW,
    )
    return code, shown, asked


def _add(project: Path, rule_id: str, argv: list[str], answer: str = "y"):  # type: ignore[no-untyped-def]
    shown: list[str] = []
    asked: list[str] = []

    def read_passphrase(prompt: str = "", *, confirm: bool = False) -> str:
        asked.append(prompt)
        return PASS

    code = add_rule(
        project,
        rule_id,
        argv,
        ask=lambda _q: answer,
        show=shown.append,
        read_passphrase=read_passphrase,
    )
    return code, shown, asked


PYPROJECT = (
    "[build-system]\nrequires = []\n\n[tool.ruff]\nline-length = 88\n\n"
    "[tool.mypy]\nstrict = true\n\n[tool.black]\n"
)


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (
            {"pyproject.toml": PYPROJECT},
            {
                "lint": ("python", "-m", "ruff", "check"),
                "typecheck": ("python", "-m", "mypy"),
                "format": ("python", "-m", "black", "--check"),
                "build": ("python", "-m", "build"),
            },
        ),
        (
            {
                ".flake8": "[flake8]\n",
                "pyrightconfig.json": "{}",
                "pyproject.toml": "[tool.ruff.format]\n",
            },
            {
                # [tool.ruff.format] is a ruff config too: ruff lints.
                "lint": ("python", "-m", "ruff", "check"),
                "typecheck": ("pyright",),
                "format": ("python", "-m", "ruff", "format", "--check"),
            },
        ),
        (
            {"setup.cfg": "[flake8]\nmax-line-length = 88\n\n[mypy]\n"},
            {"lint": ("python", "-m", "flake8"), "typecheck": ("python", "-m", "mypy")},
        ),
        (
            {
                "package.json": json.dumps(
                    {
                        "scripts": {
                            "lint": "eslint .",
                            "typecheck": "tsc",
                            "build": "vite build",
                            "format:check": "prettier -c .",
                        }
                    }
                )
            },
            {
                "lint": ("npm", "run", "lint"),
                "typecheck": ("npm", "run", "typecheck"),
                "format": ("npm", "run", "format:check"),
                "build": ("npm", "run", "build"),
            },
        ),
        ({}, {}),
    ],
    ids=["pyproject", "ruff-format-pyright", "setup-cfg", "npm", "nothing"],
)
def test_each_tool_is_detected_with_the_narrowest_known_command(
    tmp_path: Path, files: dict[str, str], expected: dict
) -> None:
    found = {r.rule_id: r.argv for r in detect_verifiers(_project(tmp_path, files))}
    assert found == expected
    for kind, argv in found.items():
        # The verifier tools match each one (B-023).
        assert any(argv[: len(k)] == k for k in KNOWN[kind]), (kind, argv)


def test_one_signature_grants_every_detected_rule(tmp_path: Path) -> None:
    project = _project(tmp_path, {"pyproject.toml": PYPROJECT})
    code, shown, asked = _guided(project)
    assert code == 0
    assert len(asked) == 1  # one passphrase (a new key, confirmed), one signature
    state = load_grant(project)
    assert state.holds, state.reason
    rules = {r.id: r for r in state.policy.commands.allow}
    assert set(rules) == {"tests", "lint", "typecheck", "format", "build"}
    for rule in rules.values():
        assert rule.network is False and rule.timeout_s == 900
    assert rule_for(state.policy, "lint").id == "lint"
    text = "\n".join(shown)
    assert "found the linter: python -m ruff check" in text
    assert "found the type checker: python -m mypy" in text


def test_a_linter_alone_is_still_proposed(tmp_path: Path) -> None:
    root = tmp_path / "lintonly"
    root.mkdir()
    (root / "ruff.toml").write_text("line-length = 88\n", encoding="utf-8")
    code, _, _ = _guided(root)
    assert code == 0
    assert [r.id for r in load_grant(root).policy.commands.allow] == ["lint"]


def test_add_rule_shows_the_diff_and_signs_again(tmp_path: Path) -> None:
    project = _project(tmp_path, {})
    assert _guided(project)[0] == 0
    code, shown, asked = _add(project, "format", ["python", "-m", "black", "--check"])
    assert code == 0
    assert asked == ["Passphrase: "]
    state = load_grant(project)
    assert state.holds, state.reason
    assert [r.id for r in state.policy.commands.allow] == ["tests", "format"]
    assert any(" + " in line and "id: format" in line for line in shown)  # the diff


def test_a_declined_add_rule_writes_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path, {})
    assert _guided(project)[0] == 0
    before = (project / ".ract" / "policy.yaml").read_bytes()
    code, shown, asked = _add(project, "lint", ["python", "-m", "ruff", "check"], "n")
    assert code == 1 and asked == []
    assert (project / ".ract" / "policy.yaml").read_bytes() == before
    assert load_grant(project).holds


def test_add_rule_refuses_a_grant_changed_since_its_signature(tmp_path: Path) -> None:
    project = _project(tmp_path, {})
    assert _guided(project)[0] == 0
    path = project / ".ract" / "policy.yaml"
    changed = path.read_text(encoding="utf-8").replace(
        "timeout_s: 900", "timeout_s: 9000"
    )
    path.write_text(changed, encoding="utf-8")
    code, shown, asked = _add(project, "lint", ["python", "-m", "ruff", "check"])
    assert code == 2 and asked == []
    assert path.read_text(encoding="utf-8") == changed  # left as found
    assert "does not hold" in shown[0]


def test_add_rule_refuses_an_id_the_grant_has(tmp_path: Path) -> None:
    project = _project(tmp_path, {})
    assert _guided(project)[0] == 0
    code, shown, _ = _add(project, "tests", ["python", "-m", "pytest", "-x"])
    assert code == 2 and "already has a rule 'tests'" in shown[0]


def test_add_rule_refuses_a_pipe(tmp_path: Path) -> None:
    project = _project(tmp_path, {"ract.yaml": "providers: {}\n"})
    env = {
        **os.environ,
        "APPDATA": str(tmp_path / "cfg"),
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "PYTHONPATH": str(REPO / "src"),
    }
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "policy",
            "add-rule",
            "lint",
            "--",
            "python",
            "-m",
            "ruff",
            "check",
        ],
        input="y\n" + PASS + "\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
        timeout=120,
    )
    assert done.returncode == 3, done.stdout + done.stderr
    assert "at a terminal" in done.stdout
    assert not (project / ".ract").exists()
