"""B-096 (S2 D3): the context label a model copies is not written into the file.

The prompt shows a file between ``--- path ---`` and ``--- end path ---``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ract.executor.steps import Executor
from tests.fixtures.fake_model_server import Scenario
from tests.test_headless import _ract
from tests.test_session_turn import _repo

FILE = "def add(a, b):\n    return a + b\n"


def _normalize(content: str, path: str = "src/calc.py") -> str:
    return Executor._strip_context_label(content, path)


def test_the_label_for_the_steps_own_path_is_removed() -> None:
    reply = f"--- src/calc.py ---\n{FILE}--- end src/calc.py ---\n"
    assert _normalize(reply).strip() == FILE.strip()
    assert "---" not in _normalize(reply)


def test_a_reply_without_a_label_is_unchanged() -> None:
    assert _normalize(FILE) == FILE


def test_a_label_in_the_middle_of_the_file_is_content() -> None:
    reply = f"{FILE}\n--- src/calc.py ---\nx = 1\n"
    assert _normalize(reply) == reply


def test_a_windows_path_in_the_label_matches() -> None:
    assert _normalize(f"--- src\\calc.py ---\n{FILE}").strip() == FILE.strip()


def test_a_label_for_another_path_is_found() -> None:
    reply = f"--- src/other.py ---\n{FILE}"
    assert _normalize(reply) == reply
    assert Executor._label_for_another_path(reply, "src/calc.py") == "src/other.py"
    assert Executor._label_for_another_path(FILE, "src/calc.py") is None


def _plan() -> str:
    return json.dumps(
        {
            "assumption": "add() is wrong.",
            "confidence": 0.8,
            "steps": [
                {
                    "action": "Fix add() in src/calc.py so it adds",
                    "provider_hint": "local",
                    "expected_artifact": "src/calc.py",
                }
            ],
        }
    )


def _run(tmp_path: Path, fake_model_server: Any, reply: str):
    turns = [{"reply": {"kind": "text", "content": c}} for c in (_plan(), reply)]
    turns += [{"reply": {"kind": "text", "content": "Done."}}] * 3
    server = fake_model_server(Scenario.from_dict({"turns": turns}))
    ws = _repo(tmp_path, server.base_url)
    result = _ract(ws, "-p", "fix add", "--accept-edits", "--output-format", "text")
    return ws, result


def test_a_real_run_writes_the_file_without_the_label(
    tmp_path: Path, fake_model_server: Any
) -> None:
    reply = f"--- src/calc.py ---\n{FILE}\n\ndef sub(a, b):\n    return a - b\n--- end src/calc.py ---"
    ws, result = _run(tmp_path, fake_model_server, reply)
    assert result.returncode == 0, result.stdout + result.stderr
    written = (ws / "src" / "calc.py").read_text(encoding="utf-8")
    assert "---" not in written and "return a + b" in written


def test_a_real_run_refuses_a_label_for_another_file(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws, result = _run(tmp_path, fake_model_server, f"--- src/other.py ---\n{FILE}")
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "label of another file (src/other.py)" in out
    assert "return a - b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")
