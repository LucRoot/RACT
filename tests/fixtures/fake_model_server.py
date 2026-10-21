"""Scripted fake OpenAI-compatible model server for tests and walkthroughs.

The server plays back a scenario: an ordered list of turns, each with an
optional match rule and a reply. Replies cover the shapes real servers
produce (streamed text, native tool calls with fragmented arguments, the JSON
envelope fallback, reasoning in a field or inline, truncation, stalls) and the
faults they produce rarely and at the worst moment (429, 500, 503, a reset
mid-stream, a server that never answers, bodies that are not JSON, a response
with no choices, an empty message).

Output bytes depend only on the scenario. Ids, ``created`` timestamps and
chunk boundaries are fixed, and delays change timing only, so the same
scenario produces the same bytes on every run and every platform.

Every request is recorded (method, path, headers without ``authorization``,
parsed body) so a test can assert what the client sent.

Standard library only. Binds to 127.0.0.1 on an ephemeral port.

Two entry points:

- the pytest fixture ``fake_model_server`` (registered in ``tests/conftest.py``),
  a factory: ``server = fake_model_server("j3_ask_code")``;
- the command line, for human walkthroughs::

      python -m tests.fixtures.fake_model_server --scenario j3_ask_code

Nothing under ``src/`` may import this module.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import struct
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"

REPLY_KINDS = frozenset(
    {"text", "tool_calls", "json_envelope", "reasoning", "truncated", "fault"}
)
FAULTS = frozenset(
    {
        "http_429",
        "http_500",
        "http_503",
        "reset_mid_stream",
        "truncated_close",
        "never_respond",
        "non_json",
        "missing_choices",
        "empty_message",
    }
)
DEFAULT_CREATED = 1700000000
DEFAULT_CHUNK_SIZE = 16


class ScenarioError(ValueError):
    """A scenario file is malformed. The message names the turn and field."""


# ---------------------------------------------------------------------------
# Scenario model
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    """One scripted reply and the rule that selects it."""

    index: int
    reply: dict[str, Any]
    match_turn: int | None = None
    match_regex: re.Pattern[str] | None = None
    repeat: bool = False
    used: bool = False

    def matches(self, ordinal: int, last_text: str) -> bool:
        if self.match_turn is not None and self.match_turn != ordinal:
            return False
        if self.match_regex is not None and not self.match_regex.search(last_text):
            return False
        return True


@dataclass
class Scenario:
    """A parsed scenario: server-level settings plus ordered turns."""

    name: str
    model: str = "fake-model"
    tools_supported: bool = True
    usage: bool = True
    created: int = DEFAULT_CREATED
    turns: list[Turn] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, name: str = "") -> Scenario:
        if not isinstance(data, dict):
            raise ScenarioError("scenario root must be a JSON object")
        raw_turns = data.get("turns")
        if not isinstance(raw_turns, list) or not raw_turns:
            raise ScenarioError("scenario needs a non-empty 'turns' list")
        scenario = cls(
            name=str(data.get("name") or name or "unnamed"),
            model=str(data.get("model", "fake-model")),
            tools_supported=bool(data.get("tools_supported", True)),
            usage=bool(data.get("usage", True)),
            created=int(data.get("created", DEFAULT_CREATED)),
        )
        for i, raw in enumerate(raw_turns, start=1):
            if not isinstance(raw, dict) or not isinstance(raw.get("reply"), dict):
                raise ScenarioError(f"turn {i}: needs a 'reply' object")
            reply = raw["reply"]
            kind = reply.get("kind")
            if kind not in REPLY_KINDS:
                raise ScenarioError(
                    f"turn {i}: reply kind {kind!r} is not one of {sorted(REPLY_KINDS)}"
                )
            if kind == "fault" and reply.get("fault") not in FAULTS:
                raise ScenarioError(
                    f"turn {i}: fault {reply.get('fault')!r} is not one of {sorted(FAULTS)}"
                )
            if kind == "tool_calls" and not scenario.tools_supported:
                raise ScenarioError(
                    f"turn {i}: tool_calls reply in a scenario with tools_supported=false"
                )
            match = raw.get("match") or {}
            regex = match.get("last_message")
            scenario.turns.append(
                Turn(
                    index=i,
                    reply=reply,
                    match_turn=match.get("turn"),
                    match_regex=re.compile(regex) if regex else None,
                    repeat=bool(raw.get("repeat", False)),
                )
            )
        return scenario

    @classmethod
    def load(cls, name_or_path: str | Path) -> Scenario:
        path = Path(name_or_path)
        if not path.suffix:
            path = SCENARIO_DIR / f"{name_or_path}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            available = sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))
            raise ScenarioError(
                f"no scenario {str(name_or_path)!r}; available: {', '.join(available)}"
            ) from None
        return cls.from_dict(data, name=path.stem)

    def select(self, ordinal: int, last_text: str) -> Turn | None:
        for turn in self.turns:
            if turn.used and not turn.repeat:
                continue
            if turn.matches(ordinal, last_text):
                turn.used = True
                return turn
        return None


def _last_message_text(body: Any) -> str:
    """Text of the last user or tool message, for ``match.last_message``."""
    if not isinstance(body, dict):
        return ""
    for message in reversed(body.get("messages") or []):
        if isinstance(message, dict) and message.get("role") in {"user", "tool"}:
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict)
                )
    return ""


# ---------------------------------------------------------------------------
# Rendering replies into chat-completion payloads
# ---------------------------------------------------------------------------


def _chunks(text: str, size: int) -> list[str]:
    size = max(1, size)
    return [text[i : i + size] for i in range(0, len(text), size)] if text else []


def _tool_call_objects(reply: dict[str, Any], ordinal: int) -> list[dict[str, Any]]:
    calls = []
    for i, call in enumerate(reply.get("calls") or []):
        arguments = call.get("arguments", {})
        calls.append(
            {
                "id": call.get("id") or f"call_{ordinal}_{i}",
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": arguments
                    if isinstance(arguments, str)
                    else json.dumps(arguments, separators=(",", ":"), sort_keys=True),
                },
            }
        )
    return calls


def _content_and_reasoning(reply: dict[str, Any]) -> tuple[str, str]:
    """Return (content, reasoning_field) for text-like replies."""
    kind = reply["kind"]
    content = str(reply.get("content", ""))
    reasoning = str(reply.get("reasoning", ""))
    if kind == "json_envelope":
        if "raw" in reply:
            content = str(reply["raw"])
        else:
            content = json.dumps(
                reply.get("envelope", {}), separators=(",", ":"), sort_keys=True
            )
        return content, ""
    if reasoning and reply.get("style", "field") == "inline":
        closed = reply.get("close_think", True)
        inline = f"<think>{reasoning}</think>" if closed else f"<think>{reasoning}"
        return inline + content, ""
    return content, reasoning


def _finish_reason(reply: dict[str, Any]) -> str:
    if "finish_reason" in reply:
        return str(reply["finish_reason"])
    if reply["kind"] == "truncated":
        return "length"
    if reply["kind"] == "tool_calls":
        return "tool_calls"
    return "stop"


def _usage(scenario: Scenario, body: Any, completion_text: str) -> dict[str, int]:
    prompt_chars = (
        len(json.dumps(body.get("messages", []), sort_keys=True))
        if isinstance(body, dict)
        else 0
    )
    prompt_tokens = max(1, prompt_chars // 4)
    completion_tokens = max(1, len(completion_text) // 4) if completion_text else 0
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def render_completion(
    scenario: Scenario, reply: dict[str, Any], ordinal: int, body: Any
) -> dict[str, Any]:
    """Non-streaming chat-completion body for a reply."""
    message: dict[str, Any] = {"role": "assistant"}
    if reply["kind"] == "tool_calls":
        message["content"] = reply.get("content") or None
        message["tool_calls"] = _tool_call_objects(reply, ordinal)
        completion_text = json.dumps(message["tool_calls"], sort_keys=True)
    else:
        content, reasoning = _content_and_reasoning(reply)
        message["content"] = content
        if reasoning:
            message["reasoning_content"] = reasoning
        completion_text = content + reasoning
    payload: dict[str, Any] = {
        "id": f"chatcmpl-fake-{ordinal}",
        "object": "chat.completion",
        "created": scenario.created,
        "model": scenario.model,
        "choices": [
            {"index": 0, "message": message, "finish_reason": _finish_reason(reply)}
        ],
    }
    if scenario.usage:
        payload["usage"] = _usage(scenario, body, completion_text)
    return payload


def render_stream_events(
    scenario: Scenario, reply: dict[str, Any], ordinal: int, body: Any
) -> list[dict[str, Any]]:
    """Streaming chunk objects for a reply, in order, without the [DONE] line."""
    size = int(reply.get("chunk_size", DEFAULT_CHUNK_SIZE))
    base = {
        "id": f"chatcmpl-fake-{ordinal}",
        "object": "chat.completion.chunk",
        "created": scenario.created,
        "model": scenario.model,
    }

    def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
        return {
            **base,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    events = [chunk({"role": "assistant", "content": ""})]
    completion_text = ""
    if reply["kind"] == "tool_calls":
        text = reply.get("content") or ""
        for piece in _chunks(text, size):
            events.append(chunk({"content": piece}))
        completion_text += text
        frag = int(reply.get("arg_fragment_size", size))
        for i, call in enumerate(_tool_call_objects(reply, ordinal)):
            events.append(
                chunk(
                    {
                        "tool_calls": [
                            {
                                "index": i,
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["function"]["name"],
                                    "arguments": "",
                                },
                            }
                        ]
                    }
                )
            )
            for piece in _chunks(call["function"]["arguments"], frag):
                events.append(
                    chunk(
                        {"tool_calls": [{"index": i, "function": {"arguments": piece}}]}
                    )
                )
            completion_text += call["function"]["arguments"]
    else:
        content, reasoning = _content_and_reasoning(reply)
        for piece in _chunks(reasoning, size):
            events.append(chunk({"reasoning_content": piece}))
        for piece in _chunks(content, size):
            events.append(chunk({"content": piece}))
        completion_text = content + reasoning
    final = chunk({}, _finish_reason(reply))
    if scenario.usage:
        final["usage"] = _usage(scenario, body, completion_text)
    events.append(final)
    return events


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordedRequest:
    """One request as the server received it."""

    ordinal: int
    method: str
    path: str
    headers: dict[str, str]
    body: Any


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _FakeHTTPServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if self.server.owner.verbose:
            sys.stderr.write("fake-model: " + (format % args) + "\n")

    # -- helpers

    def _record(self, body: Any) -> int:
        headers = {
            k.lower(): v
            for k, v in self.headers.items()
            if k.lower() != "authorization"
        }
        return self.server.owner._record(self.command, self.path, headers, body)

    def _send_json(
        self, status: int, payload: Any, extra: dict[str, str] | None = None
    ) -> None:
        data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        self._send_bytes(status, data, "application/json", extra)

    def _send_bytes(
        self, status: int, data: bytes, ctype: str, extra: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def _reset(self) -> None:
        """Abort the connection with a TCP reset."""
        try:
            self.connection.setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
            )
        except OSError:
            pass
        self.connection.close()
        self.close_connection = True

    # -- routes

    def do_GET(self) -> None:  # noqa: N802
        self._record(None)
        if self.path.rstrip("/") in {"/v1/models", "/models"}:
            model = self.server.owner.scenario.model
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [{"id": model, "object": "model", "owned_by": "fake"}],
                },
            )
            return
        self._send_json(
            404, {"error": {"message": f"no route {self.path}", "type": "not_found"}}
        )

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body: Any = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = raw.decode("utf-8", "replace")
        ordinal = self._record(body)
        if self.path.rstrip("/") not in {"/v1/chat/completions", "/chat/completions"}:
            self._send_json(
                404,
                {"error": {"message": f"no route {self.path}", "type": "not_found"}},
            )
            return
        owner = self.server.owner
        chat_ordinal = owner._next_chat_ordinal()
        turn = owner.scenario.select(chat_ordinal, _last_message_text(body))
        if turn is None:
            self._send_json(
                500,
                {
                    "error": {
                        "message": "fake server: scenario has no turn for this request",
                        "type": "scenario_exhausted",
                    }
                },
            )
            return
        reply = turn.reply
        owner._log_turn(ordinal, turn.index)
        delay = float(reply.get("first_byte_delay", 0))
        if delay and owner._stopping.wait(delay):
            self._reset()
            return
        if reply["kind"] == "fault":
            self._fault(reply, body, chat_ordinal)
            return
        stream = isinstance(body, dict) and bool(body.get("stream"))
        if stream:
            self._stream(reply, body, chat_ordinal)
        else:
            self._send_json(
                200, render_completion(owner.scenario, reply, chat_ordinal, body)
            )

    def _fault(self, reply: dict[str, Any], body: Any, ordinal: int) -> None:
        fault = reply["fault"]
        if fault == "http_429":
            extra = {}
            if "retry_after" in reply:
                extra["Retry-After"] = str(reply["retry_after"])
            self._send_json(
                429, {"error": {"message": "rate limited", "type": "rate_limit"}}, extra
            )
        elif fault in {"http_500", "http_503"}:
            code = int(fault[-3:])
            self._send_json(
                code,
                {
                    "error": {
                        "message": f"fake server error {code}",
                        "type": "server_error",
                    }
                },
            )
        elif fault == "non_json":
            self._send_bytes(200, b"<html>gateway says no</html>", "text/html")
        elif fault == "missing_choices":
            self._send_json(
                200, {"id": f"chatcmpl-fake-{ordinal}", "object": "chat.completion"}
            )
        elif fault == "empty_message":
            payload = render_completion(
                self.server.owner.scenario,
                {"kind": "text", "content": ""},
                ordinal,
                body,
            )
            self._send_json(200, payload)
        elif fault == "never_respond":
            self.server.owner._stopping.wait(float(reply.get("hold_seconds", 3600)))
            self._reset()
        elif fault in {"reset_mid_stream", "truncated_close"}:
            stream_reply = {
                **reply,
                "kind": "text",
                "content": reply.get("content", "partial answer that will be cut"),
            }
            cut = int(reply.get("after_chunks", 2))
            if fault == "reset_mid_stream":
                self._stream(stream_reply, body, ordinal, reset_after=cut)
            else:
                self._stream(stream_reply, body, ordinal, close_after=cut)

    def _stream(
        self,
        reply: dict[str, Any],
        body: Any,
        ordinal: int,
        *,
        reset_after: int | None = None,
        close_after: int | None = None,
    ) -> None:
        owner = self.server.owner
        events = render_stream_events(owner.scenario, reply, ordinal, body)
        newline = "\r\n" if reply.get("crlf") else "\n"
        chunked = not reply.get("close_after")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        if chunked:
            self.send_header("Transfer-Encoding", "chunked")
        else:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()

        def write(text: str) -> None:
            data = text.encode("utf-8")
            if chunked:
                self.wfile.write(f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n")
            else:
                self.wfile.write(data)
            self.wfile.flush()

        stall = reply.get("stall") or {}
        chunk_delay = float(reply.get("chunk_delay", 0))
        lines = [
            f"data: {json.dumps(e, separators=(',', ':'), sort_keys=True)}{newline}{newline}"
            for e in events
        ]
        if reply.get("done", True):
            lines.append(f"data: [DONE]{newline}{newline}")
        try:
            for n, line in enumerate(lines):
                if reset_after is not None and n >= reset_after:
                    # A reset may make the client's kernel drop data it has
                    # not read yet, so how many lines a client sees before
                    # the error is not deterministic. Use truncated_close
                    # when a test needs exact counts.
                    self._reset()
                    return
                if close_after is not None and n >= close_after:
                    # Clean close (FIN) without the terminating chunk: every
                    # line sent so far reaches the client, then the body ends
                    # early. Models a server process that exited mid-answer.
                    self.wfile.flush()
                    try:
                        self.connection.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    self.close_connection = True
                    return
                if stall and n == int(stall.get("after_chunk", 0)):
                    if owner._stopping.wait(float(stall.get("seconds", 0))):
                        self._reset()
                        return
                elif chunk_delay and n and owner._stopping.wait(chunk_delay):
                    self._reset()
                    return
                write(line)
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # The client went away (an interrupt test). Nothing to clean up.
            self.close_connection = True


class _FakeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, owner: FakeModelServer) -> None:
        self.owner = owner
        super().__init__(("127.0.0.1", 0), _Handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A client that hangs up (interrupt and timeout tests, keep-alive
        # sockets closed at teardown) is expected. Anything else is a bug in
        # the fake server and should be loud.
        exc = sys.exc_info()[1]
        if isinstance(
            exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)
        ):
            return
        super().handle_error(request, client_address)


class FakeModelServer:
    """A running fake server. Use as a context manager or call start/stop."""

    def __init__(
        self, scenario: Scenario | str | Path, *, verbose: bool = False
    ) -> None:
        self.scenario = (
            scenario if isinstance(scenario, Scenario) else Scenario.load(scenario)
        )
        self.verbose = verbose
        self._lock = threading.Lock()
        self._requests: list[RecordedRequest] = []
        self._turn_log: list[tuple[int, int]] = []
        self._chat_ordinal = 0
        self._stopping = threading.Event()
        self._httpd: _FakeHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- lifecycle

    def start(self) -> FakeModelServer:
        self._httpd = _FakeHTTPServer(self)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stopping.set()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self) -> FakeModelServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- addresses

    @property
    def port(self) -> int:
        assert self._httpd is not None, "server not started"
        return int(self._httpd.server_address[1])

    @property
    def root_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def base_url(self) -> str:
        """OpenAI-style base URL, ending in ``/v1``."""
        return f"{self.root_url}/v1"

    # -- recording

    def _record(
        self, method: str, path: str, headers: dict[str, str], body: Any
    ) -> int:
        with self._lock:
            ordinal = len(self._requests) + 1
            self._requests.append(RecordedRequest(ordinal, method, path, headers, body))
            return ordinal

    def _next_chat_ordinal(self) -> int:
        with self._lock:
            self._chat_ordinal += 1
            return self._chat_ordinal

    def _log_turn(self, request_ordinal: int, turn_index: int) -> None:
        with self._lock:
            self._turn_log.append((request_ordinal, turn_index))

    @property
    def requests(self) -> list[RecordedRequest]:
        with self._lock:
            return list(self._requests)

    @property
    def chat_requests(self) -> list[RecordedRequest]:
        return [
            r
            for r in self.requests
            if r.method == "POST" and r.path.rstrip("/").endswith("chat/completions")
        ]

    @property
    def turns_served(self) -> list[tuple[int, int]]:
        """(request ordinal, scenario turn index) for every reply served."""
        with self._lock:
            return list(self._turn_log)


def iter_scenario_names() -> Iterator[str]:
    yield from sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.fixtures.fake_model_server",
        description="Serve a scripted OpenAI-compatible model on 127.0.0.1 for walkthroughs.",
    )
    parser.add_argument(
        "--scenario", help="scenario name (see --list) or path to a JSON file"
    )
    parser.add_argument(
        "--list", action="store_true", help="list bundled scenarios and exit"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="log each request to stderr"
    )
    args = parser.parse_args(argv)
    if args.list or not args.scenario:
        print("scenarios: " + ", ".join(iter_scenario_names()))
        return 0 if args.list else 2
    try:
        server = FakeModelServer(args.scenario, verbose=args.verbose).start()
    except ScenarioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"fake model server: {server.base_url}  scenario: {server.scenario.name}",
        flush=True,
    )
    print(
        f"use it with: RACT_DEMO_BASE_URL={server.base_url} RACT_DEMO_MODEL={server.scenario.model}",
        flush=True,
    )
    print("Ctrl-C stops it.", flush=True)
    try:
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print(f"stopped after {len(server.requests)} requests", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
