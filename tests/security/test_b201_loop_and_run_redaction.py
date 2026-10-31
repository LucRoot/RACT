"""B-201: the loop's test run gets no provider key, and what RACT stores is redacted.

``loop_controller._run_tests`` ran the tests with the whole environment (every
provider key) and stored their output raw in the loop state and
``loop_report.json``; ``.ract/sessions/*.json`` and ``error_memory.jsonl`` held
unredacted text; ``ract run --stream`` printed deltas raw. The key here is a
throwaway value registered the way a resolved provider key is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ract import redaction
from ract.error_memory import ErrorMemory
from ract.loop_controller import LoopController
from ract.session_store import SessionStore

KEY = "sk-b201-" + "W" * 28


@pytest.fixture(autouse=True)
def registered(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    redaction.register_known(KEY)
    yield
    redaction.clear_known()


def _tests_printing(tmp_path: Path, code: str) -> str:
    fake = SimpleNamespace(
        python_executable=sys.executable, test_command=["-c", code], project_dir=tmp_path
    )
    _code, summary, output = LoopController._run_tests(fake)  # type: ignore[arg-type]
    return summary + "\n" + output


def test_the_loop_test_run_does_not_inherit_the_provider_key(tmp_path: Path) -> None:
    out = _tests_printing(
        tmp_path, "import os; print(os.environ.get('OPENAI_API_KEY', '<not passed>'))"
    )
    assert "<not passed>" in out and KEY not in out


def test_the_loop_test_output_is_redacted(tmp_path: Path) -> None:
    out = _tests_printing(tmp_path, f"print('the key is {KEY}')")
    assert KEY not in out and redaction.REPLACEMENT in out


def test_a_session_file_holds_no_key_and_still_loads(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.save("s1", {"intent": f"use {KEY} for the call", "turns": [{"answer": KEY}]})
    text = (tmp_path / "sessions" / "s1.json").read_text(encoding="utf-8")
    assert KEY not in text
    assert store.load("s1")["intent"].startswith("use ")


def test_the_error_memory_holds_no_key(tmp_path: Path) -> None:
    memory = ErrorMemory(tmp_path)
    memory._save([{"pattern": f"FAILED auth with {KEY}", "count": 1}])
    text = memory.memory_path.read_text(encoding="utf-8")
    assert KEY not in text
    assert json.loads(text.splitlines()[0])["count"] == 1


def test_the_command_record_holds_no_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # G-292: .../commands.jsonl kept the raw argv (tools/command.py _record).
    from ract.key_paths import repo_key_dir
    from ract.tools.command import CommandResult, _record

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    result = CommandResult(
        argv=["curl", "-H", f"Authorization: Bearer {KEY}", "https://x.invalid"],
        executable="curl", executable_sha256=None, cwd=".", env_names=[],
        env_allowlist_digest="d", grant_digest=None, rule_id="r1", approval_id=None,
        approver=None, sandbox="best_effort", enforced=False, limits={}, network="on",
        runner="process", exit_code=0, duration_ms=1, killed_by=None, stdout="",
        stderr="", stdout_bytes=0, stderr_bytes=0, stdout_sha256="", stderr_sha256="",
        stdout_truncated=False, stderr_truncated=False,
    )
    project = tmp_path / "project"
    project.mkdir()
    _record(project, result)
    text = (repo_key_dir(project, "commands").parent / "commands.jsonl").read_text(encoding="utf-8")
    assert KEY not in text and "curl" in text
