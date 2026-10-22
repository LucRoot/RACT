"""S-003: hook commands do not receive the operator's credentials.

`.ract/hooks/*.json` commands ran with a copy of the whole environment, so a
hook (which a cloned repository can ship) saw every API key and token. Hooks
now get the sandbox default allowlist, with credential-shaped and
library-injection names removed, RACT's own variables removed, and the
RACT_<CONTEXT> values the hook contract promises added back. A repository's
own `.ract/sandbox_env.allowlist` does not widen it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ract.hook_system import HookManager

DUMP_ENV = [
    sys.executable,
    "-c",
    "import json, os; print(json.dumps(dict(os.environ)))",
]


@pytest.fixture
def hooks(tmp_path: Path) -> HookManager:
    manager = HookManager(base_dir=tmp_path / ".ract" / "hooks")
    manager.register("pre", "dump", DUMP_ENV)
    return manager


def _hook_env(hooks: HookManager) -> dict[str, str]:
    results = hooks.run_hooks("pre", {"step_index": "3", "intent": "fix it"})
    assert results and results[0]["returncode"] == 0, results
    return json.loads(str(results[0]["stdout"]))


def test_credentials_and_injection_vars_do_not_reach_hooks(
    hooks: HookManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-test-not-real")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-test-not-real")
    monkeypatch.setenv("LD_PRELOAD", "/tmp/evil.so")
    monkeypatch.setenv("RACT_OPERATOR_KEY", "00" * 32)
    monkeypatch.setenv("SOME_RANDOM_VAR", "x")

    env = _hook_env(hooks)

    for name in (
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "LD_PRELOAD",
        "RACT_OPERATOR_KEY",
        "SOME_RANDOM_VAR",
    ):
        assert name not in env, name


def test_hooks_keep_path_and_their_context(hooks: HookManager) -> None:
    env = _hook_env(hooks)
    assert any(k.upper() == "PATH" for k in env)
    assert env["RACT_STEP_INDEX"] == "3"
    assert env["RACT_INTENT"] == "fix it"


def test_repository_allowlist_file_does_not_widen_hook_env(
    hooks: HookManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_PROJECT_TOKEN", "should-not-pass")
    allowlist = tmp_path / ".ract" / "sandbox_env.allowlist"
    allowlist.write_text('"MY_PROJECT_TOKEN"\n', encoding="utf-8")

    env = _hook_env(hooks)

    assert "MY_PROJECT_TOKEN" not in env
