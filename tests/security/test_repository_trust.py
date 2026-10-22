"""S-025: a repository's own commands run only after the operator trusts it.

`ract "intent"` in a freshly cloned repository ran its `.ract/hooks/*.json`
commands, MCP servers and other configured commands with no question.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ract import trust
from tests.test_session_turn import _repo


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A private user state directory, here and for child processes."""
    home = tmp_path / "state"
    home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home))
    trust._DECIDED.clear()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    return env


def _ract(
    ws: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def _plant_hook(ws: Path, marker: Path, name: str = "audit") -> Path:
    hooks = ws / ".ract" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-c", f"open({str(marker)!r}, 'a').write('ran')"]
    path = hooks / f"pre_{name}.json"
    path.write_text(
        json.dumps({"phase": "pre", "name": name, "command": command}), encoding="utf-8"
    )
    return path


def test_an_untrusted_hook_is_skipped_and_runs_after_trust(
    tmp_path: Path, fake_model_server: Any, state: dict[str, str]
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    marker = tmp_path / "hook.ran"
    _plant_hook(ws, marker)

    first = _ract(ws, state, "fix add")
    assert first.returncode == 0, first.stdout + first.stderr
    assert not marker.exists()
    assert "this repository is not trusted" in first.stderr
    assert "hook pre_audit:" in first.stderr  # the exact command is shown

    trusted = _ract(ws, state, "trust")
    assert trusted.returncode == 0
    assert "hook pre_audit:" in trusted.stdout

    (ws / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    server2 = fake_model_server("baseline_j4_today")
    (ws / "ract.yaml").write_text(
        (ws / "ract.yaml")
        .read_text(encoding="utf-8")
        .replace(server.base_url, server2.base_url),
        encoding="utf-8",
    )
    # ract.yaml changed, but nothing in it is a trust item, so trust holds.
    second = _ract(ws, state, "fix add")
    assert second.returncode == 0, second.stdout + second.stderr
    assert marker.exists()


def test_changing_or_adding_a_hook_ends_trust(
    tmp_path: Path, state: dict[str, str]
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    hook = _plant_hook(ws, tmp_path / "m")
    trust.trust(ws)
    assert trust.is_trusted(ws)
    hook.write_text(
        hook.read_text(encoding="utf-8").replace("ran", "RAN"), encoding="utf-8"
    )
    assert not trust.is_trusted(ws)
    trust.trust(ws)
    _plant_hook(ws, tmp_path / "m2", name="second")
    assert not trust.is_trusted(ws)


def test_mcp_and_gate_changes_in_ract_yaml_end_trust(
    tmp_path: Path, state: dict[str, str]
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "ract.yaml").write_text(
        "mcp_servers:\n  a:\n    command: x\n", encoding="utf-8"
    )
    trust.trust(ws)
    assert trust.is_trusted(ws)
    (ws / "ract.yaml").write_text(
        "mcp_servers:\n  a:\n    command: x\ncoverage_gate:\n  enabled: true\n",
        encoding="utf-8",
    )
    assert not trust.is_trusted(ws)


def test_one_key_per_repository_whatever_the_spelling(
    tmp_path: Path, state: dict[str, str]
) -> None:
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    assert trust.repository_key(ws) == trust.repository_key(ws / "sub" / "..")
    if os.name == "nt":
        assert trust.repository_key(ws) == trust.repository_key(str(ws).upper())


def test_the_trust_store_is_outside_the_project(
    tmp_path: Path, state: dict[str, str]
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    _plant_hook(ws, tmp_path / "m")
    trust.trust(ws)
    assert not any(ws.rglob("trusted_repositories.json"))
    assert trust.store_path().is_file()
    assert ws.resolve() not in trust.store_path().resolve().parents


@pytest.mark.parametrize(
    "answer, allowed, stored",
    [("t", True, True), ("r", True, False), ("s", False, False), ("", False, False)],
)
def test_the_terminal_question(
    tmp_path: Path, state: dict[str, str], answer: str, allowed: bool, stored: bool
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    _plant_hook(ws, tmp_path / "m")
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return answer

    assert trust.decide(ws, interactive=True, ask=ask) is allowed
    assert trust.decide(ws, interactive=True, ask=ask) is allowed  # asked once
    assert len(asked) == 1
    assert trust.is_trusted(ws) is stored


def test_no_terminal_means_skip_without_asking(
    tmp_path: Path, state: dict[str, str]
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    _plant_hook(ws, tmp_path / "m")

    def ask(prompt: str) -> str:
        raise AssertionError("asked without a terminal")

    assert trust.decide(ws, interactive=False, ask=ask) is False


def test_headless_honors_trust_but_bare_never_loads(
    tmp_path: Path, fake_model_server: Any, state: dict[str, str]
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    marker = tmp_path / "hook.ran"
    _plant_hook(ws, marker)
    assert _ract(ws, state, "trust").returncode == 0

    bare = _ract(ws, state, "-p", "fix add", "--bare")
    assert bare.returncode == 0, bare.stderr
    assert not marker.exists()
    assert "(--bare)" in bare.stderr

    (ws / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    server2 = fake_model_server("baseline_j4_today")
    (ws / "ract.yaml").write_text(
        (ws / "ract.yaml")
        .read_text(encoding="utf-8")
        .replace(server.base_url, server2.base_url),
        encoding="utf-8",
    )
    trusted = _ract(ws, state, "-p", "fix add")
    assert trusted.returncode == 0, trusted.stderr
    assert marker.exists()


def test_list_and_remove(tmp_path: Path, state: dict[str, str]) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "ract.yaml").write_text("project:\n  name: x\n", encoding="utf-8")
    _plant_hook(ws, tmp_path / "m")
    assert _ract(ws, state, "trust").returncode == 0
    listed = _ract(ws, state, "trust", "--list")
    assert trust.repository_key(ws) in listed.stdout
    removed = _ract(ws, state, "trust", "--remove")
    assert "no longer trusted" in removed.stdout
    assert not trust.is_trusted(ws)


# ---------------------------------------------------------------- G-044/G-045


def test_trust_project_on_the_command_line_runs_them_headless(
    tmp_path: Path, fake_model_server: Any, state: dict[str, str]
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    marker = tmp_path / "hook.ran"
    _plant_hook(ws, marker)

    result = _ract(ws, state, "-p", "fix add", "--trust-project")

    assert result.returncode == 0, result.stderr
    assert marker.exists()
    assert not trust.is_trusted(ws)  # a one-run grant, nothing stored


@pytest.mark.parametrize(
    "setting",
    [
        "trust: true\n",
        "trust_project: true\n",
        "trusted: true\n",
        "headless:\n  trust_project: true\n",
    ],
)
def test_the_repository_cannot_grant_itself_trust(
    tmp_path: Path, fake_model_server: Any, state: dict[str, str], setting: str
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    marker = tmp_path / "hook.ran"
    _plant_hook(ws, marker)
    with (ws / "ract.yaml").open("a", encoding="utf-8") as handle:
        handle.write(setting)

    result = _ract(ws, state, "-p", "fix add")

    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_reordering_ract_yaml_keeps_trust_changing_a_command_ends_it(
    tmp_path: Path, state: dict[str, str]
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "ract.yaml").write_text(
        "mcp_servers:\n  a:\n    command: x\n    args: [1, 2]\n", encoding="utf-8"
    )
    trust.trust(ws)
    (ws / "ract.yaml").write_text(
        "# reordered\nmcp_servers:\n  a:\n    args: [1, 2]\n    command: x\n",
        encoding="utf-8",
    )
    assert trust.is_trusted(ws)
    (ws / "ract.yaml").write_text(
        "mcp_servers:\n  a:\n    command: y\n    args: [1, 2]\n", encoding="utf-8"
    )
    assert not trust.is_trusted(ws)


def test_a_moved_repository_is_a_new_key(tmp_path: Path, state: dict[str, str]) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    _plant_hook(ws, tmp_path / "m")
    trust.trust(ws)
    moved = tmp_path / "moved"
    ws.rename(moved)
    assert not trust.is_trusted(moved)


def test_a_corrupt_store_trusts_nothing_and_does_not_crash(
    tmp_path: Path, state: dict[str, str]
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    _plant_hook(ws, tmp_path / "m")
    trust.trust(ws)
    trust.store_path().write_text("{not json", encoding="utf-8")
    assert trust.is_trusted(ws) is False
    trust.trust(ws)
    assert trust.is_trusted(ws) is True


def test_doctor_flags_var_syntax_outside_api_key(tmp_path: Path) -> None:
    from ract.doctor import RactDoctor

    (tmp_path / "ract.yaml").write_text(
        "providers:\n  p:\n    adapter: openai\n    url: ${MY_URL}\n    model: m\n",
        encoding="utf-8",
    )
    results = RactDoctor(tmp_path / "ract.yaml").diagnose()
    text = " ".join(r.message for r in results)
    assert "field 'url' uses ${...}, which only api_key expands" in text
