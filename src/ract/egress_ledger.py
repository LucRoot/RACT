"""One record for every request RACT sends off the machine (B-044).

LR:: INTENT invariant 9 says the operator can see everything that left the
machine. Requests went out from eight places (providers, health checks,
web search, MCP over HTTP, GitHub releases, the skill marketplace) and
nothing kept a record. Every httpx client in RACT is now made here, with a
transport that records each request when its response closes: purpose,
kind, destination host and port, status, time, bytes each way and the tokens the
provider reported. Never content: no path, query, header or body is kept.

The ledger is JSON lines in the user state directory (``egress.jsonl``,
rotated to ``egress.1.jsonl`` at 10 MB); ``RACT_EGRESS_LEDGER`` names
another file. A ledger that cannot be written prints one note per process
and never stops a request.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

ROTATE_BYTES = 10 * 1024 * 1024
# Response bodies up to this size are kept until close to read `usage`;
# a longer stream keeps only its tail (where an SSE usage chunk arrives).
_BODY_LIMIT = 2 * 1024 * 1024
_TAIL = 16 * 1024

_purpose: ContextVar[str] = ContextVar("ract_egress_purpose", default="")
# V7-08: which run, plan step and role a request belongs to. Ids only.
_run: ContextVar[str] = ContextVar("ract_egress_run", default="")
_step: ContextVar[str] = ContextVar("ract_egress_step", default="")
_role: ContextVar[str] = ContextVar("ract_egress_role", default="")
# The keys /cost --by can group model requests by.
GROUP_KEYS = ("purpose", "step", "role")
# The records of the current turn, when a session collects them (cost.updated).
_turn: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "ract_egress_turn", default=None
)
# Shared with the session's heartbeat thread: the address being connected to.
_connections: ContextVar[dict[str, str | None] | None] = ContextVar(
    "ract_egress_connections", default=None
)
_lock = threading.Lock()
_warned = False


def ledger_path() -> Path:
    override = os.environ.get("RACT_EGRESS_LEDGER")
    if override:
        return Path(override)
    from ract.core.keys import _default_state_dir

    return _default_state_dir() / "egress.jsonl"


@contextmanager
def purpose(
    name: str, *, step: object = None, role: str | None = None
) -> Iterator[None]:
    """Name what the requests inside this block are for ("plan", "step 2").

    *step* (the plan step number) and *role* (manager, executor, reviewer) are
    recorded with each request (V7-08); left out, they are the enclosing
    block's.
    """
    tokens: list[tuple[ContextVar[str], Any]] = [(_purpose, _purpose.set(name))]
    if step is not None:
        tokens.append((_step, _step.set(str(step))))
    if role is not None:
        tokens.append((_role, _role.set(role)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def set_run(run_id: str) -> None:
    """The run the requests of this context belong to (a session turn: ``session:turn``)."""
    _run.set(run_id)


def _attribution() -> dict[str, str]:
    """run, step and role for a record; each may be empty (V7-08)."""
    run = _run.get()
    if not run:
        from ract.runtime import get_current_run_id  # the --loop run id, when bound

        run = get_current_run_id() or ""
    return {"run": run, "step": _step.get(), "role": _role.get()}


def _tokens(usage: Any) -> tuple[int | None, int | None]:
    if not isinstance(usage, dict):
        return None, None
    tin = usage.get("prompt_tokens", usage.get("input_tokens"))
    tout = usage.get("completion_tokens", usage.get("output_tokens"))
    return (
        tin if isinstance(tin, int) else None,
        tout if isinstance(tout, int) else None,
    )


def _usage_from_body(content_type: str, body: bytes) -> Any:
    try:
        text = body.decode("utf-8", errors="replace")
        if "json" in content_type:
            data = json.loads(text)
            return data.get("usage") if isinstance(data, dict) else None
        if "event-stream" in content_type:
            for line in reversed(text.splitlines()):
                if line.startswith("data: ") and '"usage"' in line:
                    data = json.loads(line[len("data: ") :])
                    if isinstance(data, dict) and data.get("usage"):
                        return data["usage"]
    except ValueError:
        return None
    return None


def write(record: dict[str, Any]) -> None:
    """Append one record; a failure is reported once and never raised."""
    global _warned
    path = ledger_path()
    line = json.dumps(record, ensure_ascii=False) + "\n"
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size > ROTATE_BYTES:
                os.replace(path, path.with_name(path.stem + ".1" + path.suffix))
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
    except OSError as exc:
        if not _warned:
            _warned = True
            print(
                f"note: the egress ledger could not be written ({path}): {exc}",
                file=sys.stderr,
                flush=True,
            )


@contextmanager
def collecting() -> Iterator[list[dict[str, Any]]]:
    """Collect this turn's records; each model request then reports cost.updated."""
    records: list[dict[str, Any]] = []
    token = _turn.set(records)
    try:
        yield records
    finally:
        _turn.reset(token)


@contextmanager
def watching_connections() -> Iterator[dict[str, str | None]]:
    """Track the address a request is connecting to, for the heartbeat.

    LR:: Before the first byte the heartbeat said "waiting on model" while
    the connection was still being refused (G-055). The returned mapping's
    "connecting" key holds the address while a TCP connect is in progress
    and None otherwise; the heartbeat thread reads it.
    """
    state: dict[str, str | None] = {"connecting": None}
    token = _connections.set(state)
    try:
        yield state
    finally:
        _connections.reset(token)


def _record(record: dict[str, Any]) -> None:
    write(record)
    records = _turn.get()
    if records is None:
        return
    records.append(record)
    if record.get("kind") == "model":
        from ract import turn_context

        totals = cost(records)
        turn_context.report(
            "cost.updated",
            {
                "tokens_in": totals["tokens_in"],
                "tokens_out": totals["tokens_out"],
                "by_purpose": totals["by_purpose"],
                "requests": sum(1 for r in records if r.get("kind") == "model"),
                "total_usd": None,
                "context_used": None,
                "context_limit": None,
            },
        )


def read(path: Path | None = None) -> list[dict[str, Any]]:
    """Every record, oldest first (the rotated file, then the current one)."""
    path = path or ledger_path()
    records: list[dict[str, Any]] = []
    for part in (path.with_name(path.stem + ".1" + path.suffix), path):
        try:
            lines = part.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue  # no ledger yet, or the rotated file does not exist
        for line in lines:
            try:
                records.append(json.loads(line))
            except ValueError:
                continue  # a torn last line from a killed process
    return records


# B-087b: httpx took about a quarter of a second at every start (``ract
# --version`` included) because these classes subclass its types at import.
# They are built when the first client is made; nothing they record changes.
_built: dict[str, Any] = {}


def _transport_class() -> Any:
    """The ledger's httpx transport class, built on first use."""
    with _lock:
        if "LedgerTransport" in _built:
            return _built["LedgerTransport"]
        import httpx

        class _CountingStream(httpx.SyncByteStream):
            """Counts the response bytes and records the request when closed."""

            def __init__(self, inner: httpx.SyncByteStream, finish: Any) -> None:
                self._inner = inner
                self._finish = finish
                self._count = 0
                self._body = bytearray()
                self._done = False

            def __iter__(self) -> Iterator[bytes]:
                for chunk in self._inner:
                    self._count += len(chunk)
                    self._body += chunk
                    if len(self._body) > _BODY_LIMIT:
                        del self._body[:-_TAIL]
                    yield chunk

            def close(self) -> None:
                try:
                    self._inner.close()
                finally:
                    if not self._done:
                        self._done = True
                        self._finish(self._count, bytes(self._body))

        class LedgerTransport(httpx.BaseTransport):
            """An httpx transport that records each request in the egress ledger."""

            def __init__(
                self, kind: str, inner: httpx.BaseTransport | None = None
            ) -> None:
                self.kind = kind
                self._inner = inner or httpx.HTTPTransport()

            def handle_request(self, request: httpx.Request) -> httpx.Response:
                started = time.monotonic()
                try:
                    bytes_out: int | None = len(request.content)
                except httpx.RequestNotRead:
                    bytes_out = None
                base = {
                    "t": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    "pid": os.getpid(),
                    "purpose": _purpose.get() or self.kind,
                    **_attribution(),
                    "kind": self.kind,
                    "host": request.url.host,
                    # The port tells two local servers apart; it is not secret (G-052).
                    "port": request.url.port,
                    "bytes_out": bytes_out,
                }
                state = _connections.get()
                if state is not None:
                    port = f":{request.url.port}" if request.url.port else ""
                    address = f"{request.url.scheme}://{request.url.host}{port}"

                    def trace(name: str, info: dict[str, Any]) -> None:  # noqa: ARG001
                        if name == "connection.connect_tcp.started":
                            state["connecting"] = address
                        elif name.startswith("connection.connect_tcp."):
                            state["connecting"] = None

                    request.extensions["trace"] = trace
                try:
                    response = self._inner.handle_request(request)
                except Exception as exc:
                    if state is not None:
                        state["connecting"] = None
                    _record(
                        {
                            **base,
                            "status": type(exc).__name__,
                            "ms": int((time.monotonic() - started) * 1000),
                            "bytes_in": 0,
                            "tokens_in": None,
                            "tokens_out": None,
                        }
                    )
                    raise
                content_type = response.headers.get("content-type", "")

                def finish(count: int, body: bytes) -> None:
                    tokens_in, tokens_out = _tokens(
                        _usage_from_body(content_type, body)
                    )
                    _record(
                        {
                            **base,
                            "status": response.status_code,
                            "ms": int((time.monotonic() - started) * 1000),
                            "bytes_in": count,
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                        }
                    )

                assert isinstance(response.stream, httpx.SyncByteStream)
                return httpx.Response(
                    status_code=response.status_code,
                    headers=response.headers,
                    stream=_CountingStream(response.stream, finish),
                    extensions=response.extensions,
                )

            def close(self) -> None:
                self._inner.close()

        _built["_CountingStream"] = _CountingStream
        _built["LedgerTransport"] = LedgerTransport
        return LedgerTransport


def __getattr__(name: str) -> Any:
    if name in {"LedgerTransport", "_CountingStream"}:
        _transport_class()
        return _built[name]
    raise AttributeError(f"module 'ract.egress_ledger' has no attribute {name!r}")


def client(kind: str, **kwargs: Any) -> httpx.Client:
    """An httpx.Client whose every request is recorded in the ledger."""
    import httpx

    inner = kwargs.pop("transport", None)
    return httpx.Client(transport=_transport_class()(kind, inner), **kwargs)


def summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals for a set of records, overall and by host."""
    by_host: dict[str, dict[str, Any]] = {}
    total = {
        "requests": 0,
        "bytes_out": 0,
        "bytes_in": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "unreported": 0,
    }
    for record in records:
        host = by_host.setdefault(
            str(record.get("host", "?")),
            {
                "requests": 0,
                "bytes_out": 0,
                "bytes_in": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "unreported": 0,
            },
        )
        for bucket in (total, host):
            bucket["requests"] += 1
            bucket["bytes_out"] += int(record.get("bytes_out") or 0)
            bucket["bytes_in"] += int(record.get("bytes_in") or 0)
            if record.get("kind") == "model":
                if record.get("tokens_in") is None and record.get("tokens_out") is None:
                    bucket["unreported"] += 1
                bucket["tokens_in"] += int(record.get("tokens_in") or 0)
                bucket["tokens_out"] += int(record.get("tokens_out") or 0)
    return {**total, "by_host": by_host}


# Sites that send no content, so the secret scan has nothing to check.
EXEMPT: tuple[tuple[str, str], ...] = (
    (
        "provider health check (GET /models)",
        "sends only the API key, to its own provider",
    ),
    ("GitHub release list", "sends only the token"),
    ("skill marketplace catalog and downloads", "downloads only"),
    (
        "embedding model download (ract memory, RACT_EMBED_ONLINE=1)",
        "made by the sentence-transformers library; not recorded",
    ),
    ("language-server downloads (ract memory)", "made by multilspy; not recorded"),
)


def now() -> str:
    """The current time in the ledger's format, for ``since``."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def since(
    records: list[dict[str, Any]], start: str, *, this_process: bool = False
) -> list[dict[str, Any]]:
    """Records at or after ``start`` (from ``now()``), optionally this process's only."""
    pid = os.getpid()
    return [
        r
        for r in records
        if str(r.get("t", "")) >= start and (not this_process or r.get("pid") == pid)
    ]


def cost(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The ``cost`` object of ract.result/1 for these records.

    Token totals are null when no model request reported any; a partly
    reported set counts what was reported and says how many were not.
    """
    totals = summary(records)
    model = [r for r in records if r.get("kind") == "model"]
    reported = len(model) - totals["unreported"]
    by_purpose: dict[str, int] = {}
    for r in model:
        n = int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0)
        by_purpose[str(r.get("purpose"))] = by_purpose.get(str(r.get("purpose")), 0) + n
    return {
        "tokens_in": totals["tokens_in"] if reported else None,
        "tokens_out": totals["tokens_out"] if reported else None,
        "by_purpose": by_purpose if reported else {},
        "total_usd": None,
        "requests": totals["requests"],
        "unreported": totals["unreported"],
        "bytes_out": totals["bytes_out"],
        "bytes_in": totals["bytes_in"],
    }


def describe(records: list[dict[str, Any]], by: str = "purpose") -> list[str]:
    """Plain lines for /cost and `ract doctor --egress`.

    The model requests are grouped by *by*: purpose (the default), step or role
    (V7-08). A record written before those keys existed groups as "(none)".
    """
    if not records:
        return ["no requests left this machine"]
    totals = summary(records)

    def line(label: str, s: dict[str, Any]) -> str:
        tokens = (
            "tokens not reported"
            if s["tokens_in"] == 0 and s["tokens_out"] == 0 and s["unreported"]
            else f"{s['tokens_in']} tokens in, {s['tokens_out']} out"
            + (
                f" ({s['unreported']} requests did not report)"
                if s["unreported"]
                else ""
            )
        )
        return (
            f"{label}: {s['requests']} request{'s' if s['requests'] != 1 else ''}, "
            f"{tokens}, {s['bytes_out']} bytes sent, {s['bytes_in']} received"
        )

    lines = [line("total", totals)]
    for host, s in sorted(totals["by_host"].items()):
        lines.append("  " + line(host, s))
    # INTENT invariant 9: every model call by purpose (G-053), or by step or role.
    key = by if by in GROUP_KEYS else "purpose"
    model = [r for r in records if r.get("kind") == "model"]
    names = sorted({str(r.get(key) or "") for r in model})
    if names:
        lines.append(f"model requests by {key}:")
        for name in names:
            subset = [r for r in model if str(r.get(key) or "") == name]
            lines.append("  " + line(name or "(none)", summary(subset)))
    return lines


__all__ = [
    "EXEMPT",
    "LedgerTransport",  # noqa: F822 -- built on first use, served by __getattr__
    "collecting",
    "watching_connections",
    "cost",
    "describe",
    "now",
    "since",
    "client",
    "ledger_path",
    "purpose",
    "read",
    "summary",
    "write",
]
