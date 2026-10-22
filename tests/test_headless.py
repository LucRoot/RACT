"""B-035: headless `ract -p` (UX-09: `-p` was an argparse error and piped
stdin was ignored). One test per exit code, the output formats checked line
by line, stdout carrying only the result."""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from ract.headless import build_prompt, run_headless
from ract.session_events import KINDS
from tests.fixtures.fake_model_server import Scenario
from tests.test_session_turn import FIXED, _plan, _repo

ANSI = "\x1b["


def _ract(
    ws: Path, *args: str, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        input=stdin,
        stdin=None if stdin is not None else subprocess.DEVNULL,
    )


def _scenario(*replies: str) -> Scenario:
    return Scenario.from_dict(
        {"turns": [{"reply": {"kind": "text", "content": r}} for r in replies]}
    )


# ---------------------------------------------------------------- 0: done


def test_json_result_on_stdout_progress_on_stderr(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "fix add", "--output-format", "json")

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 1  # stdout carries only the result
    obj = json.loads(lines[0])
    assert obj["schema"] == "ract.result/1"
    assert (obj["outcome"], obj["exit_code"], obj["turns"]) == ("done", 0, 1)
    assert obj["changed"] == ["src/calc.py"]
    assert obj["verification"] == {"status": "not-run", "runs": []}
    assert obj["provenance"] == {"signed": False, "unsigned_files": ["src/calc.py"]}
    assert set(obj) >= {"session", "verdict", "final_text", "cost", "denials"}
    assert ANSI not in result.stdout
    assert "[step 1]" in result.stderr  # progress went to stderr
    assert "return a + b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")


def test_stream_json_is_the_session_event_stream(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "fix add", "--output-format", "stream-json")

    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert all(e["v"] == 2 and e["kind"] in KINDS for e in events)
    assert events[0]["kind"] == "session.started"
    assert events[-1]["kind"] == "session.ended"
    kinds = [e["kind"] for e in events]
    assert {"turn.started", "plan.proposed", "step.finished", "turn.finished"} <= set(
        kinds
    )


def test_text_output_is_the_answer_or_the_verdict(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "fix add")  # text is the default

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Done: 1 step ran; no tests were run.\n"


def test_stdin_is_the_prompt_or_labeled_context(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)

    result = _ract(
        ws, "-p", "fix add", "--output-format", "json", stdin="log line one\n"
    )

    assert result.returncode == 0, result.stderr
    body = json.dumps(server.chat_requests[0].body)
    assert "fix add" in body and "<stdin>" in body and "log line one" in body
    assert build_prompt(None, "only stdin\n") == "only stdin"
    assert build_prompt("ask", "") == "ask"


# ---------------------------------------------------------------- failures


def test_exit_2_for_usage_and_configuration_errors(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    no_prompt = _ract(ws, "-p")
    assert no_prompt.returncode == 2
    assert "hint:" in no_prompt.stderr and no_prompt.stdout == ""
    bad_flag = _ract(ws, "-p", "x", "--output-format", "xml")
    assert bad_flag.returncode == 2
    no_config = _ract(ws, "-p", "x")
    assert no_config.returncode == 2
    assert "ract --init-provider local" in no_config.stderr


def test_exit_6_when_the_provider_is_unavailable(tmp_path: Path) -> None:
    ws = _repo(tmp_path, "http://127.0.0.1:9/v1")
    (ws / "ract.yaml").write_text(
        (ws / "ract.yaml")
        .read_text(encoding="utf-8")
        .replace(
            "    model: fake-coder\n", "    model: fake-coder\n    max_retries: 0\n"
        ),
        encoding="utf-8",
    )

    result = _ract(ws, "-p", "fix add", "--output-format", "json")

    assert result.returncode == 6, result.stderr
    obj = json.loads(result.stdout)
    assert (obj["outcome"], obj["exit_code"]) == ("failed", 6)
    assert "hint:" in result.stderr


def test_exit_3_when_a_step_is_refused(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server(_scenario(_plan("settings.env.txt"), "x\n"))
    ws = _repo(tmp_path, server.base_url)
    (ws / "settings.env.txt").write_text(
        "API_TOKEN=" + "tok_9f8e7d6c5b4a3210\n", encoding="utf-8"
    )

    result = _ract(ws, "-p", "tidy settings", "--output-format", "json")

    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)["exit_code"] == 3


def test_exit_1_when_the_task_fails(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server(_scenario("this is not a plan", "still not a plan"))
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "fix add", "--output-format", "json")

    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["outcome"] == "failed"


# ---------------------------------------------------------------- signals


def _held_run(
    tmp_path: Path, fake_model_server: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Any]:
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {
                        "reply": {
                            "kind": "text",
                            "content": _plan("src/calc.py"),
                            "wait_for": "plan",
                        }
                    },
                    {"reply": {"kind": "text", "content": FIXED}},
                ]
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)
    monkeypatch.chdir(ws)
    return ws, server


def _when_requested(server: Any, action: Any) -> threading.Thread:
    def run() -> None:
        deadline = time.monotonic() + 60
        while not server.chat_requests and time.monotonic() < deadline:
            time.sleep(0.01)
        action()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_exit_5_on_sigint(
    tmp_path: Path, fake_model_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import _thread

    ws, server = _held_run(tmp_path, fake_model_server, monkeypatch)
    out, err = io.StringIO(), io.StringIO()
    _when_requested(server, _thread.interrupt_main)

    code = run_headless(
        ["-p", "fix add", "--output-format", "json"],
        stdin=io.StringIO(""),
        stdout=out,
        stderr=err,
    )

    assert code == 5
    obj = json.loads(out.getvalue())
    assert (obj["outcome"], obj["exit_code"]) == ("interrupted", 5)
    assert "return a - b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")


@pytest.mark.skipif(not hasattr(signal, "raise_signal"), reason="needs raise_signal")
def test_exit_143_on_sigterm(
    tmp_path: Path, fake_model_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, server = _held_run(tmp_path, fake_model_server, monkeypatch)
    out, err = io.StringIO(), io.StringIO()
    _when_requested(server, lambda: signal.raise_signal(signal.SIGTERM))

    code = run_headless(
        ["-p", "fix add", "--output-format", "json"],
        stdin=io.StringIO(""),
        stdout=out,
        stderr=err,
    )

    assert code == 143
    assert json.loads(out.getvalue())["exit_code"] == 143
    assert "return a - b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- trust and flags


def _plant_hook(ws: Path, marker: Path) -> None:
    hooks = ws / ".ract" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-c", f"open({str(marker)!r}, 'a').write('ran')"]
    (hooks / "pre_audit.json").write_text(
        json.dumps({"phase": "pre", "name": "audit", "command": command}),
        encoding="utf-8",
    )


@pytest.mark.parametrize("bare", [False, True])
def test_a_repository_hook_does_not_run_headless(
    tmp_path: Path, fake_model_server: Any, bare: bool
) -> None:
    """B-035 acceptance D: a cloned repository that ships a hook runs it
    neither under `ract -p` nor `ract -p --bare` (no trust store exists)."""
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    marker = tmp_path / "hook.ran"
    _plant_hook(ws, marker)

    flags = ["--bare"] if bare else []
    result = _ract(ws, "-p", "fix add", "--output-format", "stream-json", *flags)

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    started = json.loads(result.stdout.splitlines()[0])
    assert started["data"]["extensions"]["skipped"] == [
        {
            "kind": "hook",
            "name": "pre_audit",
            "reason": "untrusted project (headless run)",
        }
    ]
    assert "not loaded in a headless run" in result.stderr


def test_the_same_hook_runs_on_the_interactive_run_path(
    tmp_path: Path, fake_model_server: Any
) -> None:
    """Control for the test above: the planted hook is a working hook."""
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    marker = tmp_path / "hook.ran"
    _plant_hook(ws, marker)

    result = _ract(ws, "--config", "ract.yaml", "fix add")

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.exists()


@pytest.mark.parametrize(
    "flags, reason",
    [
        (["--allowed-tools", "read_file"], "no tools in this release"),
        (["--json-schema", "s.json"], "structured output is not supported"),
        (["--max-budget-usd", "1"], "cost is not measured"),
        (["--max-turns", "0"], "--max-turns must be 1 or more"),
    ],
)
def test_flags_this_release_cannot_honor_exit_2(
    tmp_path: Path, flags: list[str], reason: str
) -> None:
    result = _ract(tmp_path, "-p", "x", *flags)
    assert result.returncode == 2
    assert reason in result.stderr and result.stdout == ""


def test_accepted_flags(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "fix add", "--fail-on-denial", "--max-turns", "1")

    assert result.returncode == 0, result.stderr
