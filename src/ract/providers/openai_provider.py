from __future__ import annotations


"""OpenAI-compatible provider adapter for RACT.

Works with OpenAI, Azure OpenAI, and any server that exposes an OpenAI-compatible
chat completions endpoint (e.g., llama-server, vLLM, or a local proxy).
"""

import json
import os
import re
import sys
import time
from collections.abc import Iterator
from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx
else:
    from ract.lazy_import import lazy_module

    httpx = lazy_module("httpx")  # B-087b: imported at first use, not at start

from ract.providers.base import ProviderAdapter
from ract.providers import reasoning
from ract.providers.rate_limit import TokenBucket
from ract import egress_ledger, egress_scan, redaction, turn_context
from ract import run_token_budget as token_budget
from ract.retry_policy import (
    MAX_RETRY_AFTER_S,
    RetryConfig,
    RetryPolicy,
    parse_retry_after,
    wait_interruptibly,
)
from ract.rooted import Rooted


_NO_CAP_WORDS = {"none", "null", "off", "unlimited", "unbounded", "no"}


def _parse_max_tokens(raw: Any) -> int | None:
    """Return the configured output cap, or ``None`` for "no cap".

    ``max_tokens: none`` (or ``0``, ``unlimited``) means the request omits the
    field entirely and the server decides. A positive integer is a hard cap.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in _NO_CAP_WORDS:
            return None
        try:
            raw = int(text)
        except ValueError:
            raise ValueError(
                f"max_tokens must be a positive integer or 'none', got {raw!r}"
            ) from None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(
            f"max_tokens must be a positive integer or 'none', got {raw!r}"
        )
    if raw <= 0:
        return None
    return raw


_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def key_hosts(env_var: str) -> set[str]:
    """Hosts a key read from ``env_var`` may be sent to.

    The provider presets pair each key variable with its provider's URL; the
    operator's own OPENAI_BASE_URL pairs OPENAI_API_KEY with that host; and
    RACT_KEY_HOSTS (``VAR=host[,VAR=host]``) adds pairs the operator chooses.
    All three live outside the project, so a repository cannot add a pair.
    """
    from ract.provider_presets import PRESETS

    hosts: set[str] = set()
    for preset in PRESETS.values():
        for spec in (preset.get("providers") or {}).values():
            if not isinstance(spec, dict):
                continue
            ref = _ENV_REFERENCE.fullmatch(str(spec.get("api_key", "")))
            if ref and ref.group(1) == env_var and spec.get("url"):
                hosts.add(_host(str(spec["url"])))
    if env_var == "OPENAI_API_KEY":
        hosts.add(_host(os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")))
    for pair in os.environ.get("RACT_KEY_HOSTS", "").split(","):
        name, _, host = pair.strip().partition("=")
        if name == env_var and host:
            hosts.add(host.strip().lower())
    return hosts


# Connect timeout for a server on this machine. A listening socket on
# loopback is accepted by the kernel in well under a millisecond; nothing
# listening on Windows is reported only after about 2 s (4 s for
# "localhost", which tries ::1 first). B-043 wants a refused local
# connection to fail in under 3 s with one retry.
_LOOPBACK_CONNECT_TIMEOUT = 0.5


def _is_loopback(url: str) -> bool:
    import ipaddress
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _host(url: str) -> str:
    """Lowercased host and port of ``url`` (the part a key is paired with)."""
    from urllib.parse import urlsplit

    return urlsplit(url).netloc.lower()


def _body(text: str, limit: int = 200) -> str:
    """A response body for an error line: redacted whole, then cut (B-165).

    LR:: A gateway that echoes the request's Authorization header in its 401
    body put the key into the error text, and setup printed it in full
    (MASON's wrong-key walk). The known-value redaction (V7-05) matches the
    whole key, so the body is redacted before it is cut; cut first, a key at
    the cut would pass half masked.
    """
    return redaction.redact(text)[:limit]


def _aborter(client: httpx.Client):  # type: ignore[no-untyped-def]
    """The cancel abort for a request on ``client``: end its blocked read now.

    LR:: On Windows a closed client ends the blocked read in about a
    millisecond, but only a closed socket does that: the egress ledger's
    transport has no close of its own, so closing the client left the
    sockets open. On Linux a socket closed from another thread does not wake
    the thread reading it either, so the worker of a turn cancelled
    mid-stream sat out the server's stall and the session ended with its
    step worktree still listed (B-146, G-249). Each open connection's socket
    is shut down (which wakes the read on Linux) and closed (which wakes it
    on Windows); the client's close follows.
    """

    def abort() -> None:
        import socket

        for sock in _open_sockets(client):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                sock.close()  # already shut or never connected: the close ends it
                continue
            sock.close()
        client.close()

    return abort


def _open_sockets(client: httpx.Client) -> list[Any]:
    """The sockets of ``client``'s pooled connections, through wrapping transports."""
    transport: Any = getattr(client, "_transport", None)
    for _ in range(4):  # the ledger's transport wraps httpx's; follow a few layers
        if transport is None or hasattr(transport, "_pool"):
            break
        transport = getattr(transport, "_inner", None)
    pool = getattr(transport, "_pool", None)
    found = []
    for conn in list(getattr(pool, "connections", None) or []):
        stream = getattr(getattr(conn, "_connection", None), "_network_stream", None)
        sock = getattr(stream, "_sock", None)
        if sock is not None:
            found.append(sock)
    return found


class OpenAICompatibleProvider(ProviderAdapter):
    """Adapter for OpenAI-compatible HTTP endpoints."""

    # Subclasses for servers the user runs themselves (llama.cpp, vLLM) set this
    # so that, absent an explicit ``max_tokens``, the request carries no output
    # cap and the server's own limit applies. Reasoning models spend an
    # unpredictable share of any fixed cap on thinking before they answer.
    _uncapped_by_default = False

    def __init__(self, config: dict[str, Any]) -> None:
        reasoning.check_config(config.get("reasoning_effort", "off"))
        self._max_tokens_configured = "max_tokens" in config
        self._max_tokens_override = _parse_max_tokens(config.get("max_tokens"))
        self.url = config.get(
            "url",
            config.get(
                "base_url",
                os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            ),
        ).rstrip("/")
        # LR:: A key from the operator's environment went to whatever host the
        # project's ract.yaml named, so a cloned repository could set
        # `url: https://attacker` and receive OPENAI_API_KEY on the first
        # planning call (S-025). And `api_key: ${VAR}`, which the presets and
        # `ract doctor` use, was never expanded: the literal text was sent as
        # the key, so preset cloud providers could not authenticate. Now an
        # environment key, by fallback or by `${VAR}`, is read and sent only
        # to its own host (key_hosts); a literal key in ract.yaml goes where
        # ract.yaml says.
        raw_key = config.get("api_key")
        reference = (
            _ENV_REFERENCE.fullmatch(raw_key) if isinstance(raw_key, str) else None
        )
        env_var = (
            reference.group(1)
            if reference
            else ("OPENAI_API_KEY" if raw_key is None else None)
        )
        self._env_key_withheld = False
        self._env_var = env_var
        # The variable an explicit ``api_key: ${VAR}`` names, when it is unset.
        self._missing_key_var = (
            env_var
            if reference is not None and not os.environ.get(env_var or "")
            else None
        )
        if env_var is None:
            self.api_key = str(raw_key)
        else:
            value = os.environ.get(env_var)
            if value and _host(self.url) in key_hosts(env_var):
                self.api_key = value
            else:
                self.api_key = "no-key"
                self._env_key_withheld = bool(value)
        self._withheld_notice_sent = False
        if self.api_key != "no-key":
            # V7-05: the resolved key is masked wherever text is redacted (memory only).
            redaction.register_known(self.api_key)
        self.model = config.get("model", "gpt-4o-mini")
        self.timeout = float(config.get("timeout", 60.0))
        self.max_retries = int(config.get("max_retries", 3))
        self.retry_delay = float(config.get("retry_delay", 1.0))
        self.retry_backoff = float(config.get("retry_backoff", 2.0))
        self.retry_max_delay = float(config.get("retry_max_delay", 60.0))
        self.retry_on_429 = bool(config.get("retry_on_429", True))
        self._input_cost: float | None = (
            float(config["input_cost_per_1k"])
            if "input_cost_per_1k" in config
            else None
        )
        self._output_cost: float | None = (
            float(config["output_cost_per_1k"])
            if "output_cost_per_1k" in config
            else None
        )
        self._client: httpx.Client | None = None
        self._retry_policy = RetryPolicy(
            RetryConfig(
                max_retries=self.max_retries,
                base_delay=self.retry_delay,
                max_delay=self.retry_max_delay,
                jitter=True,
                backoff=self.retry_backoff,
            )
        )
        # Optional client-side rate limiter (module_05 finding 5). Omit
        # the ``rate_limit`` config block entirely to disable — the
        # provider then makes calls at the network's natural cadence.
        rl_cfg = config.get("rate_limit")
        self._rate_bucket: TokenBucket | None = None
        self._rate_acquire_timeout: float = 30.0
        if isinstance(rl_cfg, dict):
            capacity = int(rl_cfg.get("capacity", 0) or 0)
            refill = float(rl_cfg.get("refill_rate_per_sec", 0.0) or 0.0)
            if capacity > 0 and refill > 0.0:
                self._rate_bucket = TokenBucket(
                    capacity=capacity,
                    refill_rate_per_sec=refill,
                )
                self._rate_acquire_timeout = float(
                    rl_cfg.get("acquire_timeout_seconds", 30.0)
                )

    @property
    def name(self) -> str:
        return "openai_compatible"

    def models(self) -> list[str]:
        return [self.model]

    def capabilities(self) -> set[str]:
        return {"chat", "code", "streaming"}

    def input_cost_per_1k(self) -> float | None:
        return self._input_cost

    def output_cost_per_1k(self) -> float | None:
        return self._output_cost

    def _untrusted_host_refusal(self) -> Rooted[dict[str, Any]] | None:
        """The refusal for a repository-named host in an untrusted run (S-030).

        LR:: The URL comes from the repository's ract.yaml. When the
        repository is not trusted and the host is neither loopback nor one
        the operator chose (``trust.repository_named_host``), nothing is
        sent: not the request, not the project context, not a health probe.
        """
        if not turn_context.extensions_off():
            return None
        from ract.trust import repository_named_host

        host = repository_named_host(self.url)
        if host is None:
            return None
        return Rooted(
            value=None,
            assumption="The configured model host may receive this request.",
            confidence=0.0,
            provenance=[self.name],
            error=(
                f"refused: this repository's ract.yaml sends your requests to {host}, "
                "and the repository is not trusted"
            ),
            hint=(
                "run `ract trust` here if you chose that host, or set the provider "
                "url to a host you chose"
            ),
        )

    def _missing_key_refusal(self) -> Rooted[dict[str, Any]] | None:
        """The refusal for ``api_key: ${VAR}`` when VAR is not set (B-074 FOUND).

        LR:: The request went out without the key and the turn failed with no
        cause. The configuration asks for a key by name, so the name is the
        cause: say it, and send nothing.
        """
        if self._missing_key_var is None:
            return None
        return Rooted(
            value=None,
            assumption="The key the provider block names is set.",
            confidence=0.0,
            provenance=[self.name],
            error=(
                f"api_key in ract.yaml names ${{{self._missing_key_var}}}, and "
                f"{self._missing_key_var} is not set in this environment; nothing was sent"
            ),
            hint=(
                f"set {self._missing_key_var}, or remove api_key from this provider's "
                "block in ract.yaml if the server needs no key"
            ),
        )

    def health_check(self) -> bool:
        """Return True if the OpenAI-compatible endpoint responds to /models."""
        if self._untrusted_host_refusal() is not None:
            return False
        try:
            with egress_ledger.purpose("health"):
                response = self.client.get(
                    f"{self.url}/models",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                    },
                )
            response.raise_for_status()
        except Exception:  # noqa: BLE001
            return False
        return True

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            connect = (
                min(self.timeout, _LOOPBACK_CONNECT_TIMEOUT)
                if _is_loopback(self.url)
                else self.timeout
            )
            self._client = egress_ledger.client(
                "model", timeout=httpx.Timeout(self.timeout, connect=connect)
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()

    def _nothing_listening(self, exc: Exception) -> bool:
        """A connection that failed outright: refused, no route, unknown host.

        On loopback a connect timeout means the same (see
        _LOOPBACK_CONNECT_TIMEOUT). Read and write timeouts are not this.
        """
        if isinstance(exc, httpx.ConnectError):
            return True
        return isinstance(exc, httpx.ConnectTimeout) and _is_loopback(self.url)

    def describe_error(self, exc: Exception) -> str:
        """The plain reason for a failed request, with no OS error text (B-043)."""
        if self._nothing_listening(exc):
            if _is_loopback(self.url):
                return f"nothing is answering at {self.url} (connection refused)"
            return f"could not connect to {self.url}"
        if isinstance(exc, httpx.TimeoutException):
            return f"{self.url} did not answer within {self.timeout:g} s"
        if isinstance(exc, httpx.HTTPStatusError):
            if exc.response.status_code == 429:
                return "the provider is rate-limiting"
            return f"HTTP {exc.response.status_code} from {self.url}"
        if isinstance(exc, httpx.RequestError):
            return f"the request to {self.url} failed ({type(exc).__name__})"
        return type(exc).__name__

    def _is_retryable(self, exc: Exception) -> bool:
        """Return True when the exception warrants a retry.

        Server errors, 408 and (when enabled) 429 retry. Other 4xx never do.
        """
        if isinstance(exc, httpx.RequestError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            if code >= 500 or code == 408:
                return True
            if code == 429 and self.retry_on_429:
                return True
        return False

    def _retry_after(self, exc: Exception) -> float | None:
        """The server's requested wait for an HTTP error, or None (B-055)."""
        if not isinstance(exc, httpx.HTTPStatusError):
            return None
        headers = getattr(exc.response, "headers", None)
        if headers is None:
            return None
        return parse_retry_after(headers.get("Retry-After"))

    def _effective_max_tokens(self, requested: int) -> int | None:
        """Decide the output cap for one request.

        An explicit ``max_tokens`` in the provider config always wins (``none``
        removes the cap). Otherwise self-hosted adapters send no cap, and
        hosted adapters use the caller's default.
        """
        if self._max_tokens_configured:
            return self._max_tokens_override
        if self._uncapped_by_default:
            return None
        return requested

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None,
        max_tokens: int,
        temperature: float,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        cap = self._effective_max_tokens(max_tokens)
        if cap is not None:
            payload["max_tokens"] = cap
        payload = reasoning.apply(payload, url=self.url, provider=self.name)
        # S-022: the last check before anything leaves for the provider, over
        # every string in the payload (tool-call arguments included).
        payload, redacted = egress_scan.scan_payload(payload)
        egress_scan.notify(redacted, f"provider {self.name!r}")
        return payload

    def _post_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a single chat-completions request and return parsed JSON."""
        self._notify_withheld_key()
        if self._rate_bucket is not None:
            self._rate_bucket.acquire(1, timeout=self._rate_acquire_timeout)
        response = self.client.post(
            f"{self.url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict[str, Any]]:
        refusal = self._untrusted_host_refusal() or self._missing_key_refusal()
        if refusal is not None:
            return refusal
        payload = self._build_payload(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )
        budget = token_budget.current()
        if budget is not None and budget.exhausted():
            return Rooted(
                value=None,
                assumption="The run is within its token budget.",
                confidence=0.0,
                provenance=["openai.complete"],
                error=budget.stop_message(),
            )
        start = time.perf_counter()
        with turn_context.on_abort(_aborter(self.client)):
            data, last_error = self._retry_policy.execute(
                lambda: self._post_completion(payload),
                lambda exc: not turn_context.cancelled() and self._is_retryable(exc),
                on_retry=turn_context.on_retry,
                quick=self._nothing_listening,
                describe=self.describe_error,
                retry_after=self._retry_after,
                cancelled=turn_context.cancelled,
            )
        latency_ms = int((time.perf_counter() - start) * 1000)

        if last_error is None and budget is not None and data is not None:
            budget.add_usage(data.get("usage"), self.name)

        if last_error is not None:
            if isinstance(last_error, egress_ledger.NetworkRefused):
                # V7-06: the offline switch refused it before any connection.
                return Rooted(
                    value=None,
                    assumption="The run may reach the provider's host.",
                    confidence=0.0,
                    provenance=["openai.complete"],
                    error=str(last_error),
                )
            if isinstance(last_error, httpx.HTTPStatusError):
                status = last_error.response.status_code
                where = f" from {self.url}" if status == 429 else ""
                asked = self._retry_after(last_error)
                too_long = ""
                if asked is not None and asked > MAX_RETRY_AFTER_S:
                    too_long = f"; the provider asked to wait {asked:g} s; stopping"
                return Rooted(
                    value=None,
                    assumption="The OpenAI-compatible endpoint accepts the request and returns valid JSON.",
                    confidence=0.0,
                    provenance=["openai.complete"],
                    error=f"HTTP {status}{where}: {_body(last_error.response.text)}{too_long}",
                )
            if isinstance(last_error, httpx.RequestError):
                return Rooted(
                    value=None,
                    assumption="The OpenAI-compatible endpoint is reachable.",
                    confidence=0.0,
                    provenance=["openai.complete"],
                    error=f"Request failed: {self.describe_error(last_error)}.",
                )
            return Rooted(
                value=None,
                assumption="The provider completed without an unhandled exception.",
                confidence=0.0,
                provenance=["openai.complete"],
                error=f"Unexpected error after {self.max_retries} attempts: "
                f"{redaction.redact(str(last_error))}",
            )

        assert data is not None
        data["_ract_latency_ms"] = latency_ms
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return Rooted(
                value=None,
                assumption="The response contains at least one choice.",
                confidence=0.0,
                provenance=["openai.complete"],
                error="Response missing choices array.",
            )

        return Rooted(
            value=data,
            assumption="The provider returned a valid chat completion response.",
            confidence=1.0,
            provenance=["openai.complete"],
        )

    def _notify_withheld_key(self) -> None:
        """Say once that the environment key was not sent to this host."""
        if not self._env_key_withheld or self._withheld_notice_sent:
            return
        self._withheld_notice_sent = True
        text = (
            f"{self._env_var} was not sent to {_host(self.url)}: a key from your "
            "environment goes only to its own provider's host. To use this host, "
            f"name it in RACT_KEY_HOSTS ({self._env_var}={_host(self.url)})"
            + (
                ", or set OPENAI_BASE_URL to it"
                if self._env_var == "OPENAI_API_KEY"
                else ""
            )
            + "."
        )
        if turn_context.has_reporter():
            turn_context.report("notice", {"level": "warning", "text": text})
        else:
            # B-164: wrapped to the terminal (outside a session, for example the
            # setup health check); a session's renderer wraps the notice itself.
            from ract.cell_wrap import wrap_cells
            from ract.tui import terminal_width

            lines = wrap_cells(
                f"note: {text}", terminal_width(), subsequent_indent="  "
            )
            print("\n".join(lines), file=sys.stderr, flush=True)

    def _stream_headers(self) -> dict[str, str]:
        """Return headers used for streaming chat-completions requests.

        Subclasses may override this to omit authentication for local servers.
        """
        self._notify_withheld_key()
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def complete_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Iterator[Rooted[dict[str, Any]]]:
        """Stream a chat completion and yield Rooted chunks.

        Each yielded value is a single server-sent event chunk.  The caller is
        responsible for accumulating ``choices[0].delta.content`` values.
        """
        refusal = self._untrusted_host_refusal() or self._missing_key_refusal()
        if refusal is not None:
            yield refusal
            return
        budget = token_budget.current()
        if budget is not None and budget.exhausted():
            yield Rooted(
                value=None,
                assumption="The run is within its token budget.",
                confidence=0.0,
                provenance=["openai.complete_stream"],
                error=budget.stop_message(),
            )
            return
        payload = self._build_payload(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        attempt = 0
        while True:
            # A retry is only safe before the first chunk: after text has
            # reached the user, a second attempt would repeat it (B-055).
            streamed = False
            try:
                with (
                    turn_context.on_abort(_aborter(self.client)),
                    self.client.stream(
                        "POST",
                        f"{self.url}/chat/completions",
                        headers=self._stream_headers(),
                        json=payload,
                    ) as response,
                ):
                    if response.is_error:
                        # Read the error body while the stream is open, so the
                        # failure can quote it (an unread body raises on .text).
                        response.read()
                    response.raise_for_status()
                    for line in response.iter_lines():
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if line == "data: [DONE]":
                            break
                        if line.startswith("data: "):
                            data_str = line[len("data: ") :]
                            try:
                                chunk = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            streamed = True
                            if budget is not None and chunk.get("usage"):
                                budget.add_usage(chunk["usage"], self.name)
                            yield Rooted(
                                value=chunk,
                                assumption="The provider returned a valid streaming chunk.",
                                confidence=1.0,
                                provenance=["openai.complete_stream"],
                            )
                        else:
                            # Unknown line format; surface it once rather than crashing.
                            yield Rooted(
                                value=None,
                                assumption="The provider returned a valid streaming chunk.",
                                confidence=0.0,
                                provenance=["openai.complete_stream"],
                                error=f"Unexpected SSE line: {_body(line)}",
                            )
                return
            except egress_ledger.NetworkRefused as refused:
                # V7-06: refused before any connection; no retry.
                yield Rooted(
                    value=None,
                    assumption="The run may reach the provider's host.",
                    confidence=0.0,
                    provenance=["openai.complete_stream"],
                    error=str(refused),
                )
                return
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                wait = None
                if (
                    not streamed
                    and attempt < self.max_retries
                    and not turn_context.cancelled()
                    and not self._nothing_listening(exc)
                    and self._is_retryable(exc)
                ):
                    attempt += 1
                    wait = self._retry_policy.wait_before(
                        attempt, self._retry_after(exc)
                    )
                if wait is None:
                    yield self._stream_failure(exc)
                    return
                turn_context.on_retry(
                    attempt, self.max_retries, self.describe_error(exc), wait
                )
                wait_interruptibly(wait, turn_context.cancelled)
                if turn_context.cancelled():
                    yield self._stream_failure(exc)
                    return

    def _stream_failure(self, exc: Exception) -> Rooted[dict[str, Any]]:
        """The Rooted error that ends a failed stream."""
        if isinstance(exc, httpx.HTTPStatusError):
            return Rooted(
                value=None,
                assumption="The OpenAI-compatible endpoint accepts the streaming request.",
                confidence=0.0,
                provenance=["openai.complete_stream"],
                error=f"HTTP {exc.response.status_code}: {_body(exc.response.text)}",
            )
        return Rooted(
            value=None,
            assumption="The OpenAI-compatible endpoint is reachable.",
            confidence=0.0,
            provenance=["openai.complete_stream"],
            error=f"Request failed: {self.describe_error(exc)}.",
        )


# RACT 0.1.1 - Trust and tooling
