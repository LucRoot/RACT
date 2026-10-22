"""S-018 (AUD-003): file content from .git/, .ract/ or a secret-shaped file
never reaches a model request.

A plan step naming ``.ract/operator.key`` or ``.git/config`` used to get the
file's content pasted into its prompt by ``_target_file_block`` before the
write check refused the step, so the operator key or a token in a remote URL
went to the provider. Context curation had the same gap for secret-shaped
names with an allowed suffix and for ``.git`` spelled in another letter case.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ract.harness import _curate_context
from ract.workspace_path import is_never_sent, resolve_workspace_path
from tests.fixtures.fake_model_server import Scenario
from tests.ux import run_baseline as rb

OPERATOR_KEY = "opkey-5ecret-7f3a91"
GIT_TOKEN = "ghp_s018TOKENs018TOKEN"
ENV_SECRET = "env-5ecret-c4d2"
CURATED_SECRET = "curated-5ecret-88e1"
CASED_GIT_SECRET = "cased-git-5ecret-1b0c"
ALL_SECRETS = (OPERATOR_KEY, GIT_TOKEN, ENV_SECRET, CURATED_SECRET, CASED_GIT_SECRET)


def _git(ws: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=ws, capture_output=True, check=True)


def _ract(ws: Path, intent: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", "--config", "ract.yaml", intent],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def _plan(target: str) -> str:
    return json.dumps(
        {
            "assumption": "a",
            "confidence": 0.9,
            "steps": [
                {
                    "action": "Update the file",
                    "provider_hint": "local",
                    "expected_artifact": target,
                }
            ],
        }
    )


def _plant_secrets(ws: Path) -> None:
    (ws / ".ract").mkdir(exist_ok=True)
    (ws / ".ract" / "operator.key").write_text(OPERATOR_KEY + "\n", encoding="utf-8")
    _git(
        ws,
        "remote",
        "add",
        "origin",
        f"https://user:{GIT_TOKEN}@example.invalid/project.git",
    )
    (ws / ".env").write_text(f"API_KEY={ENV_SECRET}\n", encoding="utf-8")
    (ws / "config").mkdir(exist_ok=True)
    (ws / "config" / ".env.local.yaml").write_text(
        f"api_key: {CURATED_SECRET}\n", encoding="utf-8"
    )


@pytest.mark.parametrize("in_place", [False, True], ids=["isolated", "in_place"])
@pytest.mark.parametrize("target", [".ract/operator.key", ".git/config", ".env"])
def test_step_naming_a_protected_file_sends_no_secret(
    tmp_path: Path, fake_model_server: Any, target: str, in_place: bool
) -> None:
    """The in-place run reads the real .ract/ and .git/; the isolated run reads
    a step worktree, which never contains them (S-011b snapshot)."""
    replies = [{"reply": {"kind": "text", "content": _plan(target)}}]
    replies += [{"reply": {"kind": "text", "content": "replaced\n"}}] * 4
    server = fake_model_server(Scenario.from_dict({"turns": replies}))
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    if in_place:
        with (ws / "ract.yaml").open("a", encoding="utf-8") as fh:
            fh.write("substrate_loop: false\n")
    _git(ws, "add", "-A")
    _git(
        ws,
        "-c",
        "user.name=d",
        "-c",
        "user.email=d@example.invalid",
        "commit",
        "-q",
        "-m",
        "c",
    )
    _plant_secrets(ws)

    result = _ract(ws, "update the file")

    if in_place:
        assert "writes directly into your files" in result.stdout
    sent = [json.dumps(r.body) for r in server.chat_requests]
    assert len(sent) >= 2, result.stdout + result.stderr  # plan and the step
    for body in sent:
        for secret in ALL_SECRETS:
            assert secret not in body, (target, secret)
    assert OPERATOR_KEY in (ws / ".ract" / "operator.key").read_text(encoding="utf-8")
    assert ENV_SECRET in (ws / ".env").read_text(encoding="utf-8")


def test_curation_skips_secret_shaped_and_git_in_any_case(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env.local.yaml").write_text(
        f"api_key: {CURATED_SECRET}\n", encoding="utf-8"
    )
    (tmp_path / "vendor" / ".GIT").mkdir(parents=True)
    (tmp_path / "vendor" / ".GIT" / "notes.txt").write_text(
        CASED_GIT_SECRET + "\n", encoding="utf-8"
    )

    context = _curate_context(tmp_path, "update the app", max_tokens=8000)

    assert "src/app.py" in context
    assert CURATED_SECRET not in context
    assert CASED_GIT_SECRET not in context


@pytest.mark.parametrize(
    "path",
    [
        ".ract/operator.key",
        ".git/config",
        ".GIT/config",
        "sub/.git/HEAD",
        ".env",
        ".ENV.local",
        "config/.env.local.yaml",
        "certs/server.pem",
        "deploy.key",
        "home/id_rsa",
        "home/id_ed25519",
    ],
)
def test_send_refuses_protected_and_secret_shaped(tmp_path: Path, path: str) -> None:
    assert is_never_sent(path)
    result = resolve_workspace_path(tmp_path, path, purpose="send")
    assert result.value is None
    assert "never sent to a model" in (result.error or "")


@pytest.mark.parametrize(
    "path", ["src/app.py", "envelope.py", ".environment.py", "docs/key.md", "README.md"]
)
def test_send_allows_ordinary_files(tmp_path: Path, path: str) -> None:
    assert not is_never_sent(path)
    assert resolve_workspace_path(tmp_path, path, purpose="send").value is not None


def test_send_keeps_the_read_checks(tmp_path: Path) -> None:
    for path in ("../outside.py", "a\x00b.py"):
        assert resolve_workspace_path(tmp_path, path, purpose="send").value is None


@pytest.mark.parametrize("path", [".env", "config/.env.local", "certs/server.pem"])
def test_write_refuses_secret_shaped(tmp_path: Path, path: str) -> None:
    result = resolve_workspace_path(tmp_path, path, purpose="write")
    assert result.value is None
    assert result.provenance[-1] == "refused:secret_shaped"
