"""B-194: a configuration problem exits 2 with ``error.kind: config``, in every wording.

The provider wrote "api_key in ract.yaml names ${VAR} ..." and the exit table
looked for "api key" with a space, so an unset key variable exited 1 with
``kind: internal``. The sentences now come from ``config_errors`` and the
exit table reads its patterns; each real sentence is built here and checked,
and the same through ``ract -p`` and ``ract run``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ract import config_errors, harness
from ract.headless import error_object
from ract.providers.openai_provider import OpenAICompatibleProvider
from ract.providers.router import ProviderRouter
from ract.session_turn import exit_code_for

UNSET = "RACT_B194_UNSET_KEY"


@pytest.fixture(autouse=True)
def _unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UNSET, raising=False)


def _real_sentences(tmp_path: Path) -> list[str]:
    provider = OpenAICompatibleProvider(
        {
            "url": "http://127.0.0.1:9/v1",
            "api_key": "${" + UNSET + "}",
            "max_retries": 0,
        }
    )
    refused = provider.complete([{"role": "user", "content": "hi"}])
    router = ProviderRouter({})
    return [
        refused.error or "",
        harness._load_config(tmp_path / "missing.yaml").error or "",
        router.get_adapter("absent").error or "",
        config_errors.config_unparsed("mapping values are not allowed here"),
        config_errors.unknown_adapter("nonsense"),
        config_errors.slot_misconfigured("local", "url must be a string"),
        config_errors.NO_PROVIDERS,
        "HTTP 401: invalid key",
    ]


def test_every_real_sentence_is_exit_2_and_kind_config(tmp_path: Path) -> None:
    sentences = _real_sentences(tmp_path)
    assert all(sentences), sentences
    assert "api_key in ract.yaml names" in sentences[0]  # the provider's own words
    for sentence in sentences:
        for shown in (sentence, f"Planning failed: {sentence}"):
            assert exit_code_for(shown) == 2, shown
            error = error_object(exit_code_for(shown), message=shown)
            assert error is not None and error["kind"] == "config", shown


def test_a_refusal_or_a_failure_is_not_taken_for_config() -> None:
    assert exit_code_for("refused: the path is outside the project") == 3
    assert exit_code_for("the step's tests failed") == 1


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    root.mkdir()
    (root / "ract.yaml").write_text(
        "project:\n  name: p\n"
        "manager_provider: local\n"
        "providers:\n"
        "  local:\n"
        "    url: http://127.0.0.1:9/v1\n"
        "    model: m\n"
        f"    api_key: ${{{UNSET}}}\n",
        encoding="utf-8",
    )
    return root


def _ract(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["RACT_NO_NETWORK"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def test_headless_exits_2_with_kind_config(tmp_path: Path) -> None:
    done = _ract(_project(tmp_path), "-p", "fix add", "--output-format", "json")
    result = json.loads(done.stdout.splitlines()[-1])
    assert (done.returncode, result["exit_code"]) == (2, 2), done.stderr
    assert result["error"]["kind"] == "config"
    assert UNSET in result["error"]["message"]


def test_ract_run_exits_2(tmp_path: Path) -> None:
    done = _ract(_project(tmp_path), "run", "fix add", "--yolo")
    assert done.returncode == 2, (done.stdout, done.stderr)
    assert UNSET in done.stderr + done.stdout
