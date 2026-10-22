"""B-044: every request RACT sends off the machine leaves one ledger record.

Records carry purpose, kind, host, status, time, bytes and reported tokens,
never content (no path, query, header or body).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from ract import egress_ledger
from tests.test_headless import _ract
from tests.test_session_turn import _repo

SRC = Path(__file__).resolve().parents[1] / "src" / "ract"
FIELDS = {
    "t",
    "pid",
    "purpose",
    "kind",
    "host",
    "status",
    "ms",
    "bytes_out",
    "bytes_in",
    "tokens_in",
    "tokens_out",
}


@pytest.fixture
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "egress.jsonl"
    monkeypatch.setenv("RACT_EGRESS_LEDGER", str(path))
    return path


def _records(path: Path) -> list[dict[str, Any]]:
    return egress_ledger.read(path)


def test_a_model_call_records_bytes_tokens_and_no_content(ledger: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        )

    body = {"messages": [{"role": "user", "content": "SECRET-PROMPT-TEXT"}]}
    with (
        egress_ledger.purpose("step 2"),
        egress_ledger.client("model", transport=httpx.MockTransport(handler)) as client,
    ):
        response = client.post(
            "https://models.example.invalid/v1/chat/completions?key=QUERYSECRET",
            json=body,
            headers={"Authorization": "Bearer HEADERSECRET"},
        )
    assert response.json()["usage"]["prompt_tokens"] == 12

    [record] = _records(ledger)
    assert set(record) == FIELDS
    assert record["purpose"] == "step 2" and record["kind"] == "model"
    assert record["host"] == "models.example.invalid"
    assert record["status"] == 200
    assert record["bytes_out"] > len("SECRET-PROMPT-TEXT")
    assert record["bytes_in"] == len(response.content)
    assert (record["tokens_in"], record["tokens_out"]) == (12, 5)
    raw = ledger.read_text(encoding="utf-8")
    for secret in (
        "SECRET-PROMPT-TEXT",
        "QUERYSECRET",
        "HEADERSECRET",
        "chat/completions",
    ):
        assert secret not in raw


def test_a_stream_is_recorded_when_it_closes(ledger: Path) -> None:
    sse = (
        b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
        b'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":2}}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse
        )

    with egress_ledger.client(
        "model", transport=httpx.MockTransport(handler)
    ) as client:
        with client.stream(
            "POST", "http://127.0.0.1:9/v1/chat/completions", json={}
        ) as r:
            assert not _records(ledger)  # nothing until the stream closes
            lines = list(r.iter_lines())
    assert lines

    [record] = _records(ledger)
    assert record["purpose"] == "model"  # no purpose bound: the kind
    assert record["bytes_in"] == len(sse)
    assert (record["tokens_in"], record["tokens_out"]) == (7, 2)


def test_tokens_are_null_when_the_provider_reports_none(ledger: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with egress_ledger.client(
        "model", transport=httpx.MockTransport(handler)
    ) as client:
        client.post("http://127.0.0.1:9/v1/chat/completions", json={})

    [record] = _records(ledger)
    assert (record["tokens_in"], record["tokens_out"]) == (None, None)
    assert egress_ledger.summary([record])["unreported"] == 1


def test_a_failed_connection_is_recorded_and_raised(ledger: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with egress_ledger.client("mcp", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ConnectError):
            client.post("http://mcp.example.invalid/rpc", json={})

    [record] = _records(ledger)
    assert record["status"] == "ConnectError" and record["bytes_in"] == 0


def test_an_unwritable_ledger_never_stops_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RACT_EGRESS_LEDGER", str(tmp_path))  # a directory
    monkeypatch.setattr(egress_ledger, "_warned", False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with egress_ledger.client(
        "model", transport=httpx.MockTransport(handler)
    ) as client:
        for _ in range(2):
            assert client.get("http://127.0.0.1:9/v1/models").status_code == 200

    assert capsys.readouterr().err.count("egress ledger could not be written") == 1


def test_the_ledger_rotates(ledger: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(egress_ledger, "ROTATE_BYTES", 200)
    for i in range(10):
        egress_ledger.write({"i": i, "host": "h"})

    assert ledger.with_name("egress.1.jsonl").is_file()
    assert [r["i"] for r in egress_ledger.read(ledger)][-1] == 9


def test_a_real_turn_records_the_plan_and_the_step(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    path = egress_ledger.ledger_path()  # the run's own state directory (conftest)
    before = len(egress_ledger.read(path))

    result = _ract(ws, "-p", "fix add", "--output-format", "json")

    assert result.returncode == 0, result.stderr
    new = egress_ledger.read(path)[before:]
    purposes = [r["purpose"] for r in new if r["kind"] == "model"]
    assert purposes[:2] == ["plan", "step 1"]
    assert len(purposes) == len(server.chat_requests)
    assert all(r["host"] == "127.0.0.1" for r in new)
    assert all(r["bytes_out"] and r["bytes_in"] for r in new)


# --------------------------------------------------- every site goes through it

# Files allowed to name an httpx client constructor or request function, and why.
_ALLOWED = {
    "egress_ledger.py": "the one place clients are made",
    "openapi_client_generator.py": "emits client code as text; makes no request",
}
_HTTPX_CALL = re.compile(
    r"\bhttpx\.(Client|AsyncClient|get|post|put|patch|delete|head|options|request|stream)\("
)


def test_no_httpx_request_bypasses_the_ledger() -> None:
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name in _ALLOWED:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _HTTPX_CALL.search(line):
                offenders.append(f"{path.relative_to(SRC)}:{n}: {line.strip()}")
    assert not offenders, "use ract.egress_ledger.client():\n" + "\n".join(offenders)
