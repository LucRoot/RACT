"""S-018b: the three remaining path-chosen reads that send file content to a
provider follow the S-018 rule (inventory rows 3, 6 and 13 in L-035).

Keyword retrieval sent 2,000 characters of every matching file, including
ract.yaml and anything under ``.GIT``; ``ract fence inspect --file .env``
sent the first 50 lines of the file; a skill name was joined into a path,
so ``../`` reached any .json file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ract.chestertons_fence import ChestertonsFence
from ract.retrieval_adapter import KeywordRetrievalAdapter
from ract.skills_registry import SkillRegistry
from ract.workspace_path import is_never_sent, resolve_workspace_path
from tests.fixtures.fake_model_server import Scenario
from tests.ux import run_baseline as rb

SECRET = "zebra-5ecret-31f9"


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


def _plant(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "zebra.py").write_text(
        "ZEBRA = 'zebra stripes'\n", encoding="utf-8"
    )
    (root / "ract.yaml").write_text(f"api_key: zebra {SECRET}\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / ".env.local.yaml").write_text(
        f"zebra: {SECRET}\n", encoding="utf-8"
    )
    (root / "vendor" / ".GIT").mkdir(parents=True)
    (root / "vendor" / ".GIT" / "notes.txt").write_text(
        f"zebra {SECRET}\n", encoding="utf-8"
    )
    (root / ".Ract").mkdir()
    (root / ".Ract" / "state.json").write_text(
        f'{{"zebra": "{SECRET}"}}\n', encoding="utf-8"
    )


def test_retrieval_never_returns_protected_files(tmp_path: Path) -> None:
    _plant(tmp_path)

    found = KeywordRetrievalAdapter(tmp_path).search("zebra", top_k=10)

    assert found.value is not None
    sources = {r.source.replace("\\", "/") for r in found.value}
    assert sources == {"src/zebra.py"}
    assert all(SECRET not in r.content for r in found.value)


@pytest.mark.parametrize(
    "target", [".env", "ract.yaml", ".git/config", "keys/deploy.key"]
)
def test_fence_refuses_without_reading_or_calling_the_provider(
    tmp_path: Path, target: str
) -> None:
    path = tmp_path / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"TOKEN={SECRET}\n", encoding="utf-8")
    provider = MagicMock()

    result = ChestertonsFence(tmp_path, provider).inspect(target)

    assert result.value == ""
    assert "never sent to a model" in (result.error or "")
    provider.complete.assert_not_called()
    assert not provider.method_calls


@pytest.mark.parametrize("name", ["../x", "a/b", "..", "", ".hidden", "a\\b", "x..y"])
def test_skill_names_must_be_one_file_name(tmp_path: Path, name: str) -> None:
    registry = SkillRegistry(tmp_path)
    with pytest.raises(ValueError, match="skill name"):
        registry.load(name)
    with pytest.raises(ValueError, match="skill name"):
        registry.register(name, "t")


def test_ordinary_skill_name_still_works(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path)
    registry.register("write-tests_v2.1", "Write tests for $intent")
    assert registry.load("write-tests_v2.1")["template"] == "Write tests for $intent"


@pytest.mark.parametrize("path", ["ract.yaml", "sub/RACT.YML"])
def test_ract_config_is_never_sent_or_written(tmp_path: Path, path: str) -> None:
    assert is_never_sent(path)
    assert resolve_workspace_path(tmp_path, path, purpose="send").value is None
    written = resolve_workspace_path(tmp_path, path, purpose="write")
    assert written.provenance[-1] == "refused:ract_config"


# ---------------------------------------------------------------- request bodies


def test_retrieval_sends_no_secret_through_a_real_run(
    tmp_path: Path, fake_model_server: Any
) -> None:
    """Row 3 through the CLI: the plan request carries retrieved snippets, and
    none of them come from a never-sent file. ract.yaml itself holds a key."""
    plan = json.dumps(
        {
            "assumption": "a",
            "confidence": 0.9,
            "steps": [
                {
                    "action": "Update zebra",
                    "provider_hint": "local",
                    "expected_artifact": "src/zebra.py",
                }
            ],
        }
    )
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {"reply": {"kind": "text", "content": plan}},
                    {"reply": {"kind": "text", "content": "ZEBRA = 'updated'\n"}},
                ]
            }
        )
    )
    ws = rb._workspace(tmp_path, "ws", git=True, files={"README.md": "# z\n"})
    _plant(ws)
    rb._configure(ws, server.base_url, "fake-coder")  # replaces _plant's ract.yaml
    (ws / "ract.yaml").write_text(
        (ws / "ract.yaml").read_text(encoding="utf-8")
        + f"# zebra key {SECRET}\n"
        + "retrieval:\n  adapter: keyword\n  top_k: 10\n"
        + "  extensions: ['.py', '.yaml', '.yml', '.txt', '.json']\n",
        encoding="utf-8",
    )

    result = _ract(ws, "update the zebra module")

    bodies = [json.dumps(r.body) for r in server.chat_requests]
    assert bodies, result.stdout + result.stderr
    plan_text = "\n".join(
        str(m.get("content", "")) for m in server.chat_requests[0].body["messages"]
    ).replace("\\", "/")
    assert "\nRetrieved snippets:\n--- " in plan_text  # the block, not the rule text
    assert "--- src/zebra.py (score:" in plan_text
    for body in bodies:
        assert SECRET not in body


# ---------------------------------------------------------------- D-014


@pytest.mark.parametrize(
    "name", [".env.example", ".env.sample", ".env.template", ".env.dist"]
)
def test_env_template_names_are_allowed(tmp_path: Path, name: str) -> None:
    for path in (name, f"config/{name}"):
        assert not is_never_sent(path)
        assert resolve_workspace_path(tmp_path, path, purpose="send").value
        assert resolve_workspace_path(tmp_path, path, purpose="write").value


@pytest.mark.parametrize(
    "name", [".env.example.local", ".ENV.EXAMPLE", ".env.local", ".env.examples"]
)
def test_other_env_names_stay_refused(tmp_path: Path, name: str) -> None:
    assert is_never_sent(name)
    assert resolve_workspace_path(tmp_path, name, purpose="write").value is None


def test_snapshot_keeps_templates_and_drops_env_files_in_any_case(
    tmp_path: Path,
) -> None:
    from ract.executor.worktree import take_snapshot

    ws = rb._workspace(
        tmp_path,
        "ws",
        git=True,
        files={".env.example": "KEY=\n", ".ENV": "KEY=real\n", "a.py": "x = 1\n"},
    )
    # rb._workspace(git=True) commits these files.
    (ws / ".env.sample").write_text("KEY=\n", encoding="utf-8")
    (ws / ".env.local").write_text("KEY=real\n", encoding="utf-8")

    snap = take_snapshot(ws)

    tree = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", snap.sha],
        cwd=ws,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert ".env.example" in tree and ".env.sample" in tree and "a.py" in tree
    assert ".ENV" not in tree and ".env.local" not in tree
