"""B-047: a workspace made by the last published version (v0.5.2) opened here.

The old tree is extracted from the local tag with ``git archive``. Nothing is
installed. The old version runs with ``PYTHONPATH`` pointing at its ``src``,
and this branch's ``ract`` runs in the same workspace. The fake model server
answers both. The user state directory is the test run's own (conftest).

Two items are not run in this pass: the old hook under trust (item 4) and the
legacy ``.rack`` migration (item 6). Both are skipped with that reason.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
NEW_SRC = REPO / "src"
TAG = "v0.5.2"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


@pytest.fixture(scope="module")
def old_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    probe = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--verify", "-q", f"{TAG}^{{commit}}"],
        capture_output=True,
    )
    if probe.returncode != 0:
        pytest.skip(f"tag {TAG} is not in this repository")
    archive = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", TAG],
        capture_output=True,
        check=True,
    ).stdout
    dest = tmp_path_factory.mktemp("v052")
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        tree.extractall(dest)  # the tag's own archive, extracted into a new folder
    return dest / "src"


def _env(src: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["PYTHONPATH"] = str(src)
    return env


def _run(env: dict[str, str], ws: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        cwd=ws,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )


@pytest.fixture()
def v052_workspace(
    tmp_path: Path, old_src: Path, fake_model_server: Any
) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
    """A repository with one commit, a v0.5.2 config, and one old one-shot run."""
    server = fake_model_server("baseline_j4_today")
    ws = tmp_path / "ws"
    ws.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    # CI runners carry no global identity; the old RACT's own worktree git
    # calls inherit this repo-local one (CI fix, the release's red run).
    subprocess.run([*GIT, "config", "user.name", "demo"], cwd=ws, check=True)
    subprocess.run(
        [*GIT, "config", "user.email", "demo@example.invalid"], cwd=ws, check=True
    )
    (ws / "src").mkdir()
    (ws / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (ws / "prompts").mkdir()
    prompt = (old_src.parent / "prompts" / "manager.txt").read_text(encoding="utf-8")
    (ws / "prompts" / "manager.txt").write_text(prompt, encoding="utf-8")
    (ws / "ract.yaml").write_text(
        "project:\n  name: demo\nmanager_provider: local\nprompts_dir: prompts\n"
        "providers:\n  local:\n    adapter: local_http\n"
        f"    url: {server.base_url}\n    model: fake-coder\n    max_retries: 0\n",
        encoding="utf-8",
    )
    subprocess.run([*GIT, "add", "-A"], cwd=ws, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=ws, check=True)
    old_run = _run(_env(old_src), ws, "fix add")
    return ws, old_src, old_run


def test_the_old_one_shot_run_finished(v052_workspace: Any) -> None:
    _, _, old_run = v052_workspace
    assert old_run.returncode == 0, old_run.stderr[-400:]


def test_a_v052_config_loads_and_doctor_passes(v052_workspace: Any) -> None:
    ws, old_src, _ = v052_workspace
    proc = _run(_env(NEW_SRC), ws, "doctor")
    assert proc.returncode == 0, proc.stdout[-600:]
    assert "Traceback" not in proc.stdout + proc.stderr


def test_a_session_saved_by_v052_is_read_by_this_branch(v052_workspace: Any) -> None:
    ws, old_src, _ = v052_workspace
    save = (
        "import sys; from dataclasses import asdict; from pathlib import Path\n"
        "from ract.ract_runner import _session_store_for\n"
        "from ract.session_store import SessionState\n"
        "from ract.manager import Plan\n"
        "store = _session_store_for(Path('ract.yaml'))\n"
        "store.save('s-old', asdict(SessionState(intent='fix add', "
        "plan=Plan('fix add', 0.85, []), outcomes=[], artifacts={})))\n"
    )
    wrote = subprocess.run(
        [sys.executable, "-c", save],
        cwd=ws,
        env=_env(old_src),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert wrote.returncode == 0, wrote.stderr[-400:]
    read = (
        "from pathlib import Path\n"
        "from ract.ract_runner import _session_store_for\n"
        "print(_session_store_for(Path('ract.yaml')).load('s-old')['intent'])\n"
    )
    got = subprocess.run(
        [sys.executable, "-c", read],
        cwd=ws,
        env=_env(NEW_SRC),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert got.returncode == 0, got.stderr[-400:]
    assert got.stdout.strip() == "fix add"


def test_history_says_what_it_has_and_never_a_traceback(v052_workspace: Any) -> None:
    ws, _, _ = v052_workspace
    proc = _run(_env(NEW_SRC), ws, "report", "--last")
    assert "Traceback" not in proc.stdout + proc.stderr
    assert "No loop report found" in proc.stdout or proc.returncode == 0


def test_a_corrupted_old_session_file_gives_a_plain_error(v052_workspace: Any) -> None:
    ws, _, _ = v052_workspace
    sessions = ws / ".ract" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "bad.json").write_text("{not json", encoding="utf-8")
    proc = _run(_env(NEW_SRC), ws, "report", "--session", "bad")
    assert "Traceback" not in proc.stdout + proc.stderr


def test_ract_state_is_not_shown_as_untracked_after_a_run_on_this_branch(
    v052_workspace: Any,
) -> None:
    # The v0.5.2 run leaves .ract/ behind. This branch's own run (a dry-run plan
    # against the same fake server) must not make it show as untracked: S-016
    # excludes it on this branch. A strict xfail carried this FOUND until then.
    ws, _, _ = v052_workspace
    proc = _run(_env(NEW_SRC), ws, "fix add", "--dry-run")
    assert "Traceback" not in proc.stdout + proc.stderr
    # The planning reply is scenario-dependent: the second request of this scenario
    # is not a plan, so the run may exit 1. What matters here is that it ran on this
    # branch and left no traceback, and that .ract/ is then ignored.
    status = subprocess.run(
        ["git", "status", "--short"], cwd=ws, capture_output=True, text=True
    ).stdout
    assert "?? .ract/" not in status


@pytest.mark.skip(
    reason="not run in this pass: item 4 (old hook under trust) needs a hook written by v0.5.2"
)
def test_an_old_hook_waits_for_ract_trust() -> None:
    pass


@pytest.mark.skip(
    reason="not run in this pass: item 6 (legacy .rack migration) needs a legacy .rack fixture"
)
def test_a_legacy_rack_directory_is_migrated() -> None:
    pass
