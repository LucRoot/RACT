"""B-083b: `ract -p --output-format json` carries an `error` object.

`error` is null on success; otherwise exactly `kind`, `message`, `hint` and
`exit_code`. One real `ract -p` run per kind, the old keys unchanged (a reader
that ignores `error` still works), a hostile message shown escaped, and a long
one cut to 300 characters.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ract.headless import ERROR_KINDS, error_object, result_object
from ract.session_events import SessionEvent
from tests.test_headless import _held_run, _ract, _scenario, _when_requested
from tests.test_session_turn import _plan, _repo

# The keys and their types before B-083b: a reader written then still works.
GOLDEN = {
    "schema": str,
    "outcome": str,
    "exit_code": int,
    "session": str,
    "turns": int,
    "verdict": str,
    "final_text": str,
    "changed": list,
    "verification": dict,
    "provenance": dict,
    "cost": dict,
    "denials": list,
    "notices": list,
    "events_path": type(None),
    "plan": list,
}


def _json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(result.stdout)


def _error(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    obj = _json(result)
    error = obj["error"]
    assert set(error) == {"kind", "message", "hint", "exit_code"}, error
    assert error["exit_code"] == obj["exit_code"] == result.returncode
    assert error["kind"] in ERROR_KINDS
    return error


# --- hostile text and limits ------------------------------------------------


def test_a_message_with_an_escape_sequence_is_escaped() -> None:
    error = error_object(1, message="bad \x1b[2J\x07 reply", hint="see ‮ this")
    assert error is not None
    assert "\x1b" not in error["message"] and "\x07" not in error["message"]
    assert "‮" not in error["hint"]


def test_a_message_over_300_characters_is_cut() -> None:
    error = error_object(1, message="x" * 1000, hint="y" * 1000)
    assert error is not None
    assert len(error["message"]) == 300 and error["message"].endswith("...")
    assert len(error["hint"]) == 300


def test_an_unknown_kind_is_refused() -> None:
    import pytest

    with pytest.raises(AssertionError):
        error_object(2, kind="disk_full")


# --- success and the old keys ----------------------------------------------


def test_success_has_error_null_and_the_old_keys(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    result = _ract(ws, "-p", "--accept-edits", "fix add", "--output-format", "json")
    assert result.returncode == 0, result.stderr
    obj = _json(result)
    assert obj["error"] is None
    for key, kind in GOLDEN.items():
        assert isinstance(obj[key], kind), (key, obj[key])
    assert obj["schema"] == "ract.result/1"
    # An old reader: it takes the keys it knows and ignores the rest.
    old = {k: obj[k] for k in GOLDEN}
    assert old["outcome"] == "done" and old["exit_code"] == 0


def test_the_error_is_read_from_the_last_error_event() -> None:
    events = [
        SessionEvent(
            v=1,
            seq=1,
            t="",
            session="s",
            turn=1,
            kind="error.surfaced",
            data={
                "message": "it broke",
                "hint": "do this",
                "workspace": "",
                "log": None,
            },
        )
    ]
    obj = result_object(events, session="s", exit_code=6)
    assert obj["error"] == {
        "kind": "provider",
        "message": "it broke",
        "hint": "do this",
        "exit_code": 6,
    }


# --- one real run per kind ---------------------------------------------------


def test_kind_usage(tmp_path: Path) -> None:
    no_prompt = _ract(tmp_path, "-p", "--output-format", "json")
    assert _error(no_prompt)["kind"] == "usage"
    assert "hint:" in no_prompt.stderr  # the text line on stderr stays
    bad_flag = _ract(tmp_path, "-p", "x", "--output-format", "json", "--bogus")
    assert _error(bad_flag)["kind"] == "usage"


def test_kind_config(tmp_path: Path) -> None:
    result = _ract(tmp_path, "-p", "x", "--output-format", "json")
    error = _error(result)
    assert error["kind"] == "config"
    assert "configuration file not found" in error["message"]
    assert "ract setup" in error["hint"]


def test_kind_provider(tmp_path: Path) -> None:
    ws = _repo(tmp_path, "http://127.0.0.1:9/v1")
    config = ws / "ract.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "    model: fake-coder\n", "    model: fake-coder\n    max_retries: 0\n"
        ),
        encoding="utf-8",
    )
    result = _ract(ws, "-p", "--accept-edits", "fix add", "--output-format", "json")
    error = _error(result)
    assert (error["kind"], error["exit_code"]) == ("provider", 6)
    assert error["hint"]


def test_kind_refused(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    # The default mode with nobody to ask refuses the change (B-034).
    result = _ract(ws, "-p", "fix add", "--output-format", "json")
    error = _error(result)
    assert (error["kind"], error["exit_code"]) == ("refused", 3)


def test_kind_budget(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    result = _ract(
        ws,
        "-p",
        "--accept-edits",
        "fix add",
        "--token-budget",
        "10",
        "--output-format",
        "json",
    )
    error = _error(result)
    assert (error["kind"], error["exit_code"]) == ("budget", 4)


def test_kind_cancelled(
    tmp_path: Path, fake_model_server: Any, monkeypatch: Any
) -> None:
    import _thread
    import io

    from ract.headless import run_headless

    ws, server = _held_run(tmp_path, fake_model_server, monkeypatch)
    out, err = io.StringIO(), io.StringIO()
    _when_requested(server, _thread.interrupt_main)
    code = run_headless(
        ["-p", "--accept-edits", "fix add", "--output-format", "json"],
        stdin=io.StringIO(""),
        stdout=out,
        stderr=err,
    )
    error = json.loads(out.getvalue())["error"]
    assert code == 5 and (error["kind"], error["exit_code"]) == ("cancelled", 5)


def test_kind_stdin_stall(tmp_path: Path, fake_model_server: Any) -> None:
    from tests.test_headless_stdin_with_intent import _wait

    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["RACT_STDIN_IDLE_TIMEOUT"] = "2"
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-m", "ract.cli", "-p", "fix add", "--output-format", "json"],
        cwd=ws,
        env=env,
        stdin=subprocess.PIPE,  # open and silent until the run gives up
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        out, _err = _wait(proc)
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
    assert time.monotonic() - started < 60
    error = json.loads(out)["error"]
    assert (error["kind"], error["exit_code"]) == ("stdin_stall", 2)
    assert "--no-stdin" in error["hint"]


def test_kind_internal(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server(_scenario("this is not a plan", "still not a plan"))
    ws = _repo(tmp_path, server.base_url)
    result = _ract(ws, "-p", "--accept-edits", "fix add", "--output-format", "json")
    error = _error(result)
    assert (error["kind"], error["exit_code"]) == ("internal", 1)
    assert error["message"]


def test_every_kind_has_a_test() -> None:
    tested = {
        name.removeprefix("test_kind_")
        for name in globals()
        if name.startswith("test_kind_")
    }
    assert tested == set(ERROR_KINDS)
    assert _plan  # the shared plan helper stays importable for the refused case
