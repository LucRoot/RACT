"""B-044: every request RACT sends off the machine leaves one ledger record.

Records carry purpose, kind, host, status, time, bytes and reported tokens,
never content (no path, query, header or body).
"""

from __future__ import annotations

import json
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
    "port",
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

    result = _ract(ws, "-p", "--accept-edits", "fix add", "--output-format", "json")

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


# ------------------------------------------------------------------ readers


def _plan_and_fix(usage: bool) -> Any:
    from tests.fixtures.fake_model_server import Scenario
    from tests.test_session_turn import FIXED, _plan

    return Scenario.from_dict(
        {
            "usage": usage,
            "turns": [
                {"reply": {"kind": "text", "content": _plan("src/calc.py")}},
                {"reply": {"kind": "text", "content": FIXED}},
            ],
        }
    )


def test_headless_json_cost_comes_from_the_ledger(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_plan_and_fix(usage=True))
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "--accept-edits", "fix add", "--output-format", "json")

    assert result.returncode == 0, result.stderr
    cost = json.loads(result.stdout)["cost"]
    assert cost["requests"] == 2 and cost["unreported"] == 0
    assert cost["tokens_in"] > 0 and cost["tokens_out"] > 0
    assert set(cost["by_purpose"]) == {"plan", "step 1"}
    assert cost["total_usd"] is None


def test_unreported_tokens_are_null_not_zero(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_plan_and_fix(usage=False))
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "--accept-edits", "fix add", "--output-format", "json")

    cost = json.loads(result.stdout)["cost"]
    assert (cost["tokens_in"], cost["tokens_out"]) == (None, None)
    assert cost["requests"] == 2 and cost["unreported"] == 2


def test_cost_in_the_session_shows_only_this_session(ledger: Path) -> None:
    import os

    from tests.test_repl import _session

    egress_ledger.write(
        {
            "t": "2000-01-01T00:00:00.000+00:00",
            "pid": os.getpid(),
            "kind": "model",
            "host": "old.example",
            "tokens_in": 9,
        }
    )
    session, _, console = _session()
    egress_ledger.write(
        {
            "t": egress_ledger.now(),
            "pid": os.getpid(),
            "kind": "model",
            "host": "127.0.0.1",
            "purpose": "plan",
            "bytes_out": 10,
            "bytes_in": 20,
            "tokens_in": 3,
            "tokens_out": 4,
        }
    )

    session.handle("/cost")

    assert (
        "total: 1 request, 3 tokens in, 4 out, 10 bytes sent, 20 received"
        in console.text
    )
    assert "old.example" not in console.text
    assert str(ledger) in console.text


def test_doctor_egress_lists_history_and_exempt_sites(
    ledger: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from ract import cli

    egress_ledger.write(
        {
            "t": egress_ledger.now(),
            "pid": 1,
            "kind": "mcp",
            "host": "mcp.example.invalid",
            "bytes_out": 5,
            "bytes_in": 6,
        }
    )

    assert cli.main(["doctor", "--egress", "--json"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["ledger"] == str(ledger)
    assert out["summary"]["by_host"]["mcp.example.invalid"]["requests"] == 1
    assert {e["site"] for e in out["exempt"]} >= {"GitHub release list"}


def test_credentials_in_a_url_never_reach_the_ledger(ledger: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with egress_ledger.client("mcp", transport=httpx.MockTransport(handler)) as client:
        client.get("http://alice:hunter2pass@mcp.example.invalid:8123/rpc")

    [record] = _records(ledger)
    assert (record["host"], record["port"]) == ("mcp.example.invalid", 8123)
    raw = ledger.read_text(encoding="utf-8")
    assert "alice" not in raw and "hunter2pass" not in raw


def test_a_repository_config_cannot_redirect_the_ledger(
    tmp_path: Path, fake_model_server: Any
) -> None:
    import yaml

    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    config = yaml.safe_load((ws / "ract.yaml").read_text(encoding="utf-8"))
    planted = ws / "planted-ledger.jsonl"
    config["egress_ledger"] = str(planted)
    config["egress"] = {"ledger": str(planted), "path": str(planted)}
    (ws / "ract.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    before = len(egress_ledger.read())

    result = _ract(ws, "-p", "--accept-edits", "fix add", "--output-format", "json")

    assert result.returncode == 0, result.stderr
    assert not planted.exists()
    assert len(egress_ledger.read()) > before


# ------------------------------------------------- G-053: purpose, cost.updated


def test_cost_lists_model_requests_by_purpose(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_plan_and_fix(usage=True))
    ws = _repo(tmp_path, server.base_url)
    before = len(egress_ledger.read())

    result = _ract(
        ws, "-p", "--accept-edits", "fix add", "--output-format", "stream-json"
    )

    assert result.returncode == 0, result.stderr
    lines = egress_ledger.describe(egress_ledger.read()[before:])
    assert "model requests by purpose:" in lines
    by_purpose = [
        line.strip() for line in lines[lines.index("model requests by purpose:") + 1 :]
    ]
    assert [line.split(":")[0] for line in by_purpose] == ["plan", "step 1"]
    assert all(" tokens in, " in line for line in by_purpose)

    events = [json.loads(line) for line in result.stdout.splitlines()]
    updates = [e["data"] for e in events if e["kind"] == "cost.updated"]
    assert len(updates) == 2  # one after each model request
    assert set(updates[-1]["by_purpose"]) == {"plan", "step 1"}
    assert updates[-1]["tokens_in"] > updates[0]["tokens_in"] > 0


def test_cost_updated_tokens_are_null_when_unreported(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_plan_and_fix(usage=False))
    ws = _repo(tmp_path, server.base_url)

    result = _ract(
        ws, "-p", "--accept-edits", "fix add", "--output-format", "stream-json"
    )

    events = [json.loads(line) for line in result.stdout.splitlines()]
    updates = [e["data"] for e in events if e["kind"] == "cost.updated"]
    assert updates and all(
        u["tokens_in"] is None and u["tokens_out"] is None for u in updates
    )


def test_the_heartbeat_names_the_address_while_connecting() -> None:
    from ract.session_events import EventStream, Heartbeat
    from ract.session_render import PlainRenderer

    out: list[str] = []
    stream = EventStream(session="s")
    stream.subscribe(PlainRenderer(out.append))
    with Heartbeat(
        stream,
        turn=1,
        waiting_on="model",
        interval=0.05,
        connecting=lambda: "http://127.0.0.1:9",
    ):
        import time as _time

        _time.sleep(0.2)

    assert "connecting to http://127.0.0.1:9 (" in "".join(out)


def test_the_transport_reports_the_connect_phase(fake_model_server: Any) -> None:
    server = fake_model_server("baseline_j4_today")
    seen: list[str | None] = []

    class Recording(dict):  # type: ignore[type-arg]
        def __setitem__(self, key: str, value: Any) -> None:
            seen.append(value)
            super().__setitem__(key, value)

    token = egress_ledger._connections.set(Recording(connecting=None))
    try:
        with egress_ledger.client("model") as client:
            client.get(f"{server.base_url}/models")
    finally:
        egress_ledger._connections.reset(token)

    assert seen[0] == server.root_url and seen[-1] is None
