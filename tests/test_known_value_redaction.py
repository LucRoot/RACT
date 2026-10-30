"""V7-05: a resolved provider key is masked wherever text is redacted, and never written.

The key in these tests has no telltale shape, so the secret patterns alone do
not catch it: only registration does. Hostile first: a gateway echoes the key
it rejected in its error body; a stream splits the key across deltas; the
encoded forms; and a scan of every file the run writes.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

from ract import redaction
from tests.fixtures.fake_model_server import Scenario
from tests.test_session_turn import _repo

KEY = "zx81Qq7mN3pLwT55"


@pytest.fixture(autouse=True)
def _clean_registry():
    redaction.clear_known()
    yield
    redaction.clear_known()


def _echo_run(
    tmp_path: Path, fake_model_server: Any
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    server = fake_model_server(
        Scenario.from_dict(
            {"turns": [{"reply": {"kind": "fault", "fault": "http_401_echo"}}]}
        )
    )
    ws = _repo(tmp_path, server.base_url)
    config = ws / "ract.yaml"
    # The openai adapter sends the key (local_http never sends one).
    config.write_text(
        config.read_text(encoding="utf-8")
        .replace("adapter: local_http", "adapter: openai")
        .replace(
            "    model: fake-coder\n",
            f"    model: fake-coder\n    api_key: {KEY}\n    max_retries: 0\n",
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    state.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env.update(
        {
            "LOCALAPPDATA": str(state),
            "XDG_STATE_HOME": str(state),
            "RACT_EGRESS_LEDGER": str(state / "egress.jsonl"),
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "-p",
            "--accept-edits",
            "fix add",
            "--output-format",
            "json",
        ],
        cwd=ws,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=240,
    )
    return result, ws, state


# --- hostile cases ----------------------------------------------------------


def test_a_provider_key_in_an_error_body_is_masked(
    tmp_path: Path, fake_model_server: Any
) -> None:
    result, _ws, _state = _echo_run(tmp_path, fake_model_server)
    assert result.returncode != 0
    assert KEY not in result.stdout and KEY not in result.stderr
    json.loads(result.stdout)  # the result object is still printed
    # The rejected key is shown masked where the error is shown.
    assert "invalid key [redacted]" in result.stderr + result.stdout, result.stderr


def test_the_key_is_never_in_a_file_the_run_writes(
    tmp_path: Path, fake_model_server: Any
) -> None:
    _result, ws, state = _echo_run(tmp_path, fake_model_server)
    leaked = [
        str(path)
        for root in (ws, state)
        for path in root.rglob("*")
        if path.is_file()
        and path != ws / "ract.yaml"  # the operator wrote it there
        and ".git" not in path.parts
        and KEY.encode() in path.read_bytes()
    ]
    assert not leaked, leaked


def test_the_streaming_redactor_masks_a_registered_key_split_across_deltas() -> None:
    redaction.register_known(KEY)
    stream = redaction.StreamingRedactor()
    out = ""
    for piece in ["the server said: invalid key zx81Q", "q7mN3", "pLwT55 (401)"]:
        out += stream.feed(piece)
    out += stream.close()
    assert KEY not in out and "[redacted]" in out
    assert out.startswith("the server said: invalid key ")


def test_the_encoded_forms_are_masked() -> None:
    redaction.register_known(KEY)
    encoded = base64.b64encode(KEY.encode()).decode()
    url_safe = base64.urlsafe_b64encode(KEY.encode()).decode().rstrip("=")
    for text in (KEY, quote(KEY, safe=""), encoded, url_safe):
        assert redaction.redact(f"x {text} y") == "x [redacted] y", text


def test_a_value_under_8_characters_is_not_registered() -> None:
    assert redaction.register_known("short7c") is False
    assert redaction.redact("a short7c word") == "a short7c word"
    assert redaction.register_known(None) is False


def test_without_registration_the_patterns_do_not_catch_this_key() -> None:
    # The premise of the tests above: the key has no telltale shape.
    assert KEY in redaction.redact(f"invalid key {KEY}")


def test_the_count_names_the_known_value() -> None:
    redaction.register_known(KEY)
    text, counts = redaction.redact_report(f"{KEY} and {KEY}")
    assert text == "[redacted] and [redacted]" and counts == {"known_value": 2}


def test_the_provider_registers_its_resolved_key() -> None:
    from ract.providers.openai_provider import OpenAICompatibleProvider

    OpenAICompatibleProvider(
        {"url": "http://127.0.0.1:9/v1", "model": "m", "api_key": KEY}
    )
    assert redaction.redact(KEY) == "[redacted]"
    OpenAICompatibleProvider(
        {"url": "http://127.0.0.1:9/v1", "model": "m", "api_key": "no-key"}
    )
    assert redaction.redact("no-key") == "no-key"
