"""S-022: every serialized provider request passes a last-line secret scan.

S-018 keeps known secret paths out of requests. This catches values inside
files the operator legitimately asked about: they arrive at the provider
as ``[redacted]``, a notice names the pattern and count (never the value),
and a step whose own target file holds one is refused before any request,
because the model would return the file with the placeholder.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ract import egress_scan
from ract.redaction import redact_report
from tests.fixtures.fake_model_server import Scenario
from tests.ux import run_baseline as rb

REPO = Path(__file__).resolve().parents[2]

SHAPES = {
    "OpenAI-style key": "sk-proj-" + "Q1w2E3r4T5y6U7i8O9p0",
    "GitHub token": "ghp_" + "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2Rr1Qq0",
    "AWS access key id": "AKIA" + "QWERTYUIOPASDFGH",
    "Hugging Face token": "hf_" + "abcdefghijklmnopqrstuvwxyzABCDEF",
    "URL credentials": "deploy:" + "s3cr3t-pass-word",
    "secret assignment": "BILLING_SECRET_KEY=" + "q9w8e7r6t5y4u3i2",
    "private key block": "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIB" + "x" * 40,
}


def _value(name: str, text: str) -> str:
    """The part of ``text`` that must never reach a request."""
    if name == "URL credentials":
        return "s3cr3t-pass-word"
    if name == "secret assignment":
        return "q9w8e7r6t5y4u3i2"
    if name == "private key block":
        return "MHcCAQEEIB"
    return text


def _ract(ws: Path, intent: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", "--config", "ract.yaml", "--yolo", intent],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def _plan(target: str) -> str:
    return json.dumps(
        {
            "assumption": "a",
            "confidence": 0.9,
            "steps": [
                {
                    "action": "Update the file",
                    "provider_hint": "local",
                    "expected_artifact": target,
                }
            ],
        }
    )


def _notes() -> str:
    lines = ["# deploy notes", ""]
    for name, text in SHAPES.items():
        if name == "URL credentials":
            text = f"clone with https://{text}@git.example.invalid/app.git"
        lines.append(text)
        lines.append("")
    return "\n".join(lines) + "\n"


def test_each_shape_reaches_the_provider_redacted_with_a_notice(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {"reply": {"kind": "text", "content": _plan("README.md")}},
                    {"reply": {"kind": "text", "content": "# app\n\nUpdated.\n"}},
                ]
            }
        )
    )
    ws = rb._workspace(
        tmp_path, "ws", git=True, files={"README.md": "# app\n", "notes.md": _notes()}
    )
    rb._configure(ws, server.base_url, "fake-coder")

    result = _ract(ws, "update the readme from the deploy notes")

    bodies = [json.dumps(r.body) for r in server.chat_requests]
    assert len(bodies) >= 2, result.stdout + result.stderr
    assert "deploy notes" in bodies[0]  # the file was curated into the request
    for name, text in SHAPES.items():
        for body in bodies:
            assert _value(name, text) not in body, name
    assert "[redacted]" in bodies[0]
    assert "redacted secret-shaped values before sending to provider" in result.stderr
    for name in SHAPES:
        assert name in result.stderr
    for name, text in SHAPES.items():
        assert _value(name, text) not in result.stdout + result.stderr


def test_a_step_whose_target_holds_a_secret_is_refused_before_any_request(
    tmp_path: Path, fake_model_server: Any
) -> None:
    config = "# settings\nAPI_TOKEN=" + "tok_9f8e7d6c5b4a3210\n"
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {"reply": {"kind": "text", "content": _plan("settings.env.txt")}},
                    {"reply": {"kind": "text", "content": "API_TOKEN=[redacted]\n"}},
                ]
            }
        )
    )
    ws = rb._workspace(
        tmp_path, "ws", git=True, files={"settings.env.txt": config, "README.md": "#\n"}
    )
    rb._configure(ws, server.base_url, "fake-coder")

    result = _ract(ws, "tidy the settings file")

    assert len(server.chat_requests) == 1  # the plan only; no step request
    assert (ws / "settings.env.txt").read_text(encoding="utf-8") == config
    out = result.stdout + result.stderr
    # The console wraps long lines to the terminal width (UX package A), so the
    # sentence can break across lines; the words are compared, not the breaks.
    assert "holds secret-shaped values (1 secret assignment)" in " ".join(out.split())
    assert "tok_9f8e7d6c5b4a3210" not in out


def test_the_source_tree_scans_clean() -> None:
    """False-positive corpus: RACT's own code, docs, prompts and fixtures."""
    skip = {"redaction.py", "egress_scan.py"}
    flagged = {}
    for root in ("src/ract", "docs", "prompts", "tests/fixtures"):
        for path in (REPO / root).rglob("*"):
            if path.suffix not in {".py", ".md", ".txt", ".yaml", ".yml", ".json"}:
                continue
            if path.name in skip or "__pycache__" in path.parts:
                continue
            counts = redact_report(path.read_text(encoding="utf-8", errors="replace"))[
                1
            ]
            if counts:
                flagged[str(path.relative_to(REPO))] = counts
    assert flagged == {}


def _jwt() -> str:
    return ".".join(
        ["eyJ" + "hbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjM0In0", "abcDEF123ghiJKL456"]
    )


# G-030: eleven shapes that leaked from the first pattern list. Each fake
# secret is built from parts so this file does not trip a secret scanner.
LEAKED_SHAPES = [
    (
        'export API_TOKEN="' + "abcd1234" + 'efgh5678"',
        "abcd1234efgh5678",
        "secret assignment",
    ),
    (
        "api_key: " + "abcd1234efgh" + "5678ijkl",
        "abcd1234efgh5678ijkl",
        "secret assignment",
    ),
    (
        '{"client_secret": "' + "abcd1234efgh" + '5678ijkl"}',
        "abcd1234efgh5678ijkl",
        "secret assignment",
    ),
    ('DB_PASSWORD = "' + "hunter2" + 'hunter2"', "hunter2hunter2", "secret assignment"),
    ("token " + _jwt(), "abcDEF123ghiJKL456", "JWT"),
    ("sk_" + "live_" + "abcdef1234567890", "abcdef1234567890", "Stripe-style key"),
    ("sk_" + "test_" + "abcdef1234567890", "abcdef1234567890", "Stripe-style key"),
    (
        "DefaultEndpointsProtocol=https;AccountName=x;AccountKey=" + "Q" * 40 + "==;",
        "Q" * 40,
        "connection string key",
    ),
    (
        "https://api.example.invalid/v1?token=" + "abcd1234efgh5678",
        "abcd1234efgh5678",
        "URL query secret",
    ),
    (
        "https://x.invalid/?access_token=" + "abcd1234efgh5678&x=1",
        "abcd1234efgh5678",
        "URL query secret",
    ),
    (
        "Authorization: Basic " + "dXNlcjpwYXNz" + "d29yZDEyMw==",
        "dXNlcjpwYXNzd29yZDEyMw",
        "basic auth",
    ),
]


@pytest.mark.parametrize("text, value, name", LEAKED_SHAPES)
def test_each_g030_shape_is_redacted(text: str, value: str, name: str) -> None:
    cleaned, counts = redact_report(text)
    assert value not in cleaned
    assert counts == {name: 1}


@pytest.mark.parametrize(
    "text",
    [
        "token = tokenizer.next()",
        "secret = load_secret(path)",
        'api_key = os.environ["API_KEY"]',
        "API_KEY=${API_KEY}",
        "password: <your-password-here>",
        "api_key: your-key-here-please",
        "token=token_provider.get()",
        "author: Somebody Longname123",
        "monkey: banana1234567890",
        "the basic understanding12345 of it",
        "self.api_key = api_key",
        "DB_PASSWORD=short",
    ],
)
def test_near_misses_stay_untouched(text: str) -> None:
    assert redact_report(text) == (text, {})


@pytest.mark.parametrize("cut_shape", [s[0] for s in LEAKED_SHAPES])
def test_g030_shapes_split_at_every_offset_in_a_stream(cut_shape: str) -> None:
    """The streaming redactor shares the list; multi-token shapes must hold."""
    from ract.redaction import StreamingRedactor

    text = f"config:\n{cut_shape}\nthat is all\n"
    value = next(v for t, v, _ in LEAKED_SHAPES if t == cut_shape)
    for cut in range(1, len(text)):
        r = StreamingRedactor()
        out = r.feed(text[:cut]) + r.feed(text[cut:]) + r.close()
        assert value[:12] not in out, cut


def test_tool_call_arguments_and_other_fields_are_scanned() -> None:
    token = "ghp_" + "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2Rr1Qq0"
    payload = {
        "model": "m",
        "prompt": "use " + token,
        "system": "key " + token,
        "messages": [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": '{"path": "a", "content": "T=' + token + '"}',
                        },
                    }
                ],
            }
        ],
    }
    cleaned, counts = egress_scan.scan_payload(payload)
    assert token not in json.dumps(cleaned)
    assert counts == {"GitHub token": 3}
    call = cleaned["messages"][0]["tool_calls"][0]
    assert (call["id"], call["type"], call["function"]["name"]) == (
        "call_1",
        "function",
        "write_file",
    )
    assert token in payload["prompt"]  # the caller's payload is not mutated


def test_list_form_content_parts_are_scanned_and_roles_kept() -> None:
    messages = [
        {"role": "system", "content": "be brief"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "key " + SHAPES["GitHub token"]},
                {"type": "image_url", "image_url": {"url": "data:..."}},
            ],
        },
    ]
    cleaned, counts = egress_scan.scan_messages(messages)
    assert counts == {"GitHub token": 1}
    assert cleaned[0] == messages[0]
    assert cleaned[1]["content"][0]["text"] == "key [redacted]"
    assert cleaned[1]["content"][1] == messages[1]["content"][1]
    assert SHAPES["GitHub token"] in messages[1]["content"][0]["text"]  # not mutated


def test_the_web_search_query_is_scanned(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from ract.retrieval_adapter import WebSearchAdapter

    sent: dict[str, Any] = {}

    class Response:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict[str, Any]:
            return {"results": []}

    def post(self: Any, url: str, json: Any = None, **kwargs: Any) -> Response:
        sent["payload"] = json
        return Response()

    monkeypatch.setattr(httpx.Client, "post", post)
    adapter = WebSearchAdapter(api_key="k", endpoint="https://search.example.invalid")
    adapter.search("why does " + SHAPES["AWS access key id"] + " fail")
    assert SHAPES["AWS access key id"] not in json.dumps(sent["payload"])


@pytest.mark.parametrize(
    "text, value",
    [
        ("password: " + "correcthorse" + "batterystaple", "correcthorsebatterystaple"),
        ("PASSWORD=" + "correcthorse" + "batterystaple", "correcthorsebatterystaple"),
        (
            "client_secret: " + "Correcthorse" + "batterystaple",
            "orrecthorsebatterystaple",
        ),
        ("SK" + "0123456789abcdef" + "0123456789abcdef", "0123456789abcdef0123"),
    ],
)
def test_g031_passphrases_and_twilio_keys(text: str, value: str) -> None:
    cleaned, counts = redact_report(text)
    assert value not in cleaned
    assert sum(counts.values()) == 1


@pytest.mark.parametrize(
    "text",
    [
        "token: tokenizerfactory",
        "password: str",
        "password: PasswordManager",
        "password: getpassword(user)",
        "password_hash: abcdefabcdefabcdef",
    ],
)
def test_g031_passphrase_near_misses(text: str) -> None:
    assert redact_report(text) == (text, {})
