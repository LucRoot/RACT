"""What one provider can do, measured with a few tiny requests (B-056).

``ract doctor --check-providers`` calls :func:`probe_provider` once per
configured provider. Each finding is a fact from a request RACT made, or
"unknown" with the reason. A gap carries a next step in plain words.

The probe uses the provider object the way the session does: the same
client, the same header builder and the same outbound secret scan. It sends
at most four requests per provider (chat, streaming, tool calling, a models
listing) and never retries. Reasoning text is read from the chat reply, so it
costs no request of its own. The key never leaves the provider's own headers,
and any copy of it that a server echoes back is replaced before the report.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx
else:
    from ract.lazy_import import lazy_module

    httpx = lazy_module("httpx")  # B-087b: imported at first use, not at start

from ract import egress_ledger, egress_scan, redaction
from ract.providers.openai_provider import (
    USERINFO_REFUSED,
    OpenAICompatibleProvider,
    has_userinfo,
    shown_url,
)
from ract.providers.router import ProviderRouter
from ract.retry_policy import RetryConfig, RetryPolicy
from ract.trust import repository_named_host

PROBE_TIMEOUT_S = 15.0
CHAT_PROMPT = "reply with the word ok"
TOOL_PROMPT = "call the echo tool with text hi"
ECHO_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "echo",
        "description": "Return the text it is given.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
}
# Keys a server may use for a model's context length in its /models listing.
CONTEXT_KEYS = ("context_length", "max_context_length", "max_model_len", "n_ctx_train")
TOOLS_FALLBACK = "RACT will use its text fallback, which works for small steps."
CONTEXT_NEXT_STEP = (
    "Set context_budget_tokens in ract.yaml to the size the server runs with."
)
NOT_TRIED = "not tried"


@dataclass(frozen=True)
class Finding:
    """One line of the report: a label, what was seen, and a next step if any."""

    label: str
    status: str
    detail: str = ""
    next_step: str = ""
    # The number behind a known context window, else None.
    number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "next_step": self.next_step,
            "number": self.number,
        }


@dataclass
class ProviderProbe:
    """The findings for one configured provider."""

    name: str
    url: str
    model: str
    findings: list[Finding] = field(default_factory=list)
    # False when the adapter is not an HTTP chat endpoint: nothing to probe.
    probed: bool = True
    # True when only this repository's ract.yaml chose the host (S-030).
    repo_named: bool = False

    @property
    def chat_works(self) -> bool:
        return any(f.label == "chat" and f.status == "works" for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "url": self.url,
            "model": self.model,
            "probed": self.probed,
            "repo_named": self.repo_named,
            "chat_works": self.chat_works,
            "findings": [f.to_dict() for f in self.findings],
        }


def not_tried(
    name: str, url: str, model: str, reason: str, *, probed: bool = True
) -> ProviderProbe:
    """A provider that was not contacted, with the reason and the next step."""
    probe = ProviderProbe(name=name, url=url, model=model, probed=probed)
    probe.findings.append(Finding("chat", "not tried", reason))
    for label in ("streaming", "tool calling", "reasoning text", "context window"):
        probe.findings.append(Finding(label, NOT_TRIED))
    return probe


def probe_provider(name: str, adapter: Any, *, url: str, model: str) -> ProviderProbe:
    """Send the probe requests to one OpenAI-compatible provider.

    Every request is recorded in the egress ledger with the purpose "probe".
    """
    with egress_ledger.purpose("probe"):
        return _run_probes(name, adapter, url=url, model=model)


def _run_probes(name: str, adapter: Any, *, url: str, model: str) -> ProviderProbe:
    probe = ProviderProbe(name=name, url=url, model=model)
    scrub = _Scrubber(getattr(adapter, "api_key", ""))

    started = time.perf_counter()
    try:
        reply = _post(adapter, name, _chat_payload(model, CHAT_PROMPT, 8))
        content = _message(reply).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("no chat content")
        chat_ms = int((time.perf_counter() - started) * 1000)
        probe.findings.append(Finding("chat", "works", f"{chat_ms / 1000:.1f} s"))
    except Exception as exc:  # noqa: BLE001 - every failure becomes a finding
        probe.findings.append(
            Finding(
                "chat", "failed", _explain(exc, adapter, scrub), _chat_next_step(exc)
            )
        )
        for label in ("streaming", "tool calling", "reasoning text", "context window"):
            probe.findings.append(Finding(label, NOT_TRIED))
        return probe

    probe.findings.append(_probe_streaming(adapter, name, model, scrub))
    probe.findings.append(_probe_tools(adapter, name, model, scrub))
    probe.findings.append(_reasoning_finding(_message(reply)))
    probe.findings.append(_probe_context(adapter, model, scrub))
    return probe


class _Scrubber:
    """Masks the provider's key in any text the report shows, then cuts it.

    B-198: the body was cut and then masked, so a key across the cut passed
    half shown. The provider's own key is replaced first (any length), then
    ``redaction.body`` masks the registered keys, their encoded forms and the
    key shapes in the whole text, and only then cuts it.
    """

    def __init__(self, key: object) -> None:
        self._key = key if isinstance(key, str) and len(key) >= 4 else ""

    def __call__(self, text: str, limit: int | None = None) -> str:
        if self._key and self._key in text:
            text = text.replace(self._key, "********")
        return redaction.body(text, limit)


def _chat_payload(model: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
    }


def _post(adapter: Any, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST one probe request through the provider's client and headers."""
    payload, redacted = egress_scan.scan_payload(payload)
    egress_scan.notify(redacted, f"probe {name!r}")
    adapter._notify_withheld_key()
    response = adapter.client.post(
        f"{adapter.url}/chat/completions",
        headers=adapter._stream_headers(),
        json=payload,
        timeout=PROBE_TIMEOUT_S,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("choices"), list):
        raise ValueError("not a chat reply")
    if not data["choices"]:
        raise ValueError("no choices")
    return data


def _message(reply: dict[str, Any]) -> dict[str, Any]:
    choice = reply["choices"][0]
    message = choice.get("message") if isinstance(choice, dict) else None
    return message if isinstance(message, dict) else {}


def _chat_next_step(exc: Exception) -> str:
    """The plain next step for a failed chat request."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "check the key variable named in ract.yaml for this provider"
        if code == 404:
            return "check the url and the model name in ract.yaml"
        if code == 429:
            return (
                "wait a minute, or lower the request rate in the rate_limit block "
                "of ract.yaml"
            )
        return "read the server log for this request"
    if isinstance(exc, httpx.TimeoutException):
        return "check that the server is not busy, or raise timeout in ract.yaml"
    if isinstance(exc, httpx.RequestError):
        return "start your model server, or fix the provider url in ract.yaml"
    return "the url in ract.yaml must serve the OpenAI chat format"


def _explain(exc: Exception, adapter: Any, scrub: _Scrubber) -> str:
    """The plain reason a probe request failed. Never a traceback, never a key."""
    if isinstance(exc, httpx.HTTPStatusError):
        body = scrub(exc.response.text, 120).strip()
        return f"HTTP {exc.response.status_code}" + (f": {body}" if body else "")
    if isinstance(exc, httpx.TimeoutException):
        return f"did not answer within {PROBE_TIMEOUT_S:g} s"
    if isinstance(exc, httpx.RequestError):
        return scrub(adapter.describe_error(exc))
    if isinstance(exc, (ValueError, KeyError, TypeError, IndexError)):
        return "the server answered but not in the chat format"
    return scrub(type(exc).__name__)


def _probe_streaming(adapter: Any, name: str, model: str, scrub: _Scrubber) -> Finding:
    policy = adapter._retry_policy
    # A probe reports the first failure as it is; it does not retry.
    adapter._retry_policy = RetryPolicy(
        RetryConfig(max_retries=0, base_delay=0.0, max_delay=0.0, jitter=False)
    )
    try:
        deltas = 0
        for item in adapter.complete_stream(
            [{"role": "user", "content": CHAT_PROMPT}], max_tokens=8, temperature=0
        ):
            if not item.is_ok():
                return Finding("streaming", "failed", scrub(str(item.error)))
            choices = (item.unwrap() or {}).get("choices") or [{}]
            if (choices[0].get("delta") or {}).get("content"):
                deltas += 1
        if deltas:
            noun = "text piece" if deltas == 1 else "text pieces"
            return Finding("streaming", "works", f"{deltas} {noun}")
        return Finding(
            "streaming",
            "failed",
            "the stream ended without any text",
            "Use a non-streaming setup for this server, or check its stream settings.",
        )
    except Exception as exc:  # noqa: BLE001 - every failure becomes a finding
        return Finding("streaming", "failed", _explain(exc, adapter, scrub))
    finally:
        adapter._retry_policy = policy


def _probe_tools(adapter: Any, name: str, model: str, scrub: _Scrubber) -> Finding:
    payload = _chat_payload(model, TOOL_PROMPT, 32)
    payload["tools"] = [ECHO_TOOL]
    payload["tool_choice"] = "auto"
    try:
        reply = _post(adapter, name, payload)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400 and "tool" in exc.response.text.lower():
            return Finding(
                "tool calling",
                "not supported",
                "the server rejects tool requests",
                TOOLS_FALLBACK,
            )
        return Finding("tool calling", "failed", _explain(exc, adapter, scrub))
    except httpx.TimeoutException:
        # No answer is not a refusal: the server may be busy or may not get to the
        # tool request in time. The probe does not know, so it says unknown (B-094).
        return Finding(
            "tool calling",
            "unknown",
            f"no answer in {PROBE_TIMEOUT_S:g} s",
            "check that the server is not busy, or raise timeout in ract.yaml",
        )
    except Exception as exc:  # noqa: BLE001 - every failure becomes a finding
        return Finding("tool calling", "failed", _explain(exc, adapter, scrub))

    calls = _message(reply).get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return Finding(
            "tool calling",
            "not supported",
            "the server answered without a tool call",
            TOOLS_FALLBACK,
        )
    function = calls[0].get("function") if isinstance(calls[0], dict) else None
    try:
        arguments = json.loads((function or {}).get("arguments") or "")
    except (TypeError, ValueError):
        arguments = None
    if (function or {}).get("name") == "echo" and isinstance(arguments, dict):
        return Finding("tool calling", "works")
    return Finding(
        "tool calling",
        "not supported",
        "the server returned a tool call with arguments RACT cannot read",
        TOOLS_FALLBACK,
    )


def _reasoning_finding(message: dict[str, Any]) -> Finding:
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return Finding("reasoning text", "returned")
    return Finding("reasoning text", "not returned")


def _probe_context(adapter: Any, model: str, scrub: _Scrubber) -> Finding:
    try:
        adapter._notify_withheld_key()
        response = adapter.client.get(
            f"{adapter.url}/models",
            headers=adapter._stream_headers(),
            timeout=PROBE_TIMEOUT_S,
        )
        response.raise_for_status()
        listing = response.json()
    except Exception as exc:  # noqa: BLE001 - every failure becomes a finding
        return Finding(
            "context window",
            "unknown",
            f"could not read /models: {_explain(exc, adapter, scrub)}",
            CONTEXT_NEXT_STEP,
        )
    entries = listing.get("data") if isinstance(listing, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("id") != model:
            continue
        for key in CONTEXT_KEYS:
            value = entry.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return Finding(
                    "context window",
                    "known",
                    f"{value} tokens, from the server",
                    number=value,
                )
    return Finding(
        "context window",
        "unknown",
        "the server does not say",
        CONTEXT_NEXT_STEP,
    )


def probe_configured(providers: dict[str, Any]) -> list[ProviderProbe]:
    """Probe every provider in a ``ract.yaml`` ``providers`` block.

    A provider whose key variable is unset is not contacted: the report names
    the variable to set. A provider that is not an HTTP chat adapter is not
    probed either.
    """
    probes: list[ProviderProbe] = []
    names = [n for n, s in providers.items() if isinstance(s, dict)]
    if not names:
        return probes
    router = ProviderRouter({n: providers[n] for n in names})
    for name in names:
        settings = providers[name]
        raw_url = str(settings.get("url") or settings.get("base_url") or "")
        url = shown_url(raw_url)
        model = str(settings.get("model", ""))
        if has_userinfo(raw_url):
            # B-199: not contacted, and the report shows the url without it.
            probes.append(not_tried(name, url, model, USERINFO_REFUSED, probed=False))
            continue
        missing = _missing_key_variable(settings)
        if missing:
            probes.append(
                not_tried(
                    name,
                    url,
                    model,
                    f"the key variable {missing} is not set",
                )
            )
            continue
        adapter = router.get_adapter(name)
        if not adapter.is_ok():
            probes.append(not_tried(name, url, model, adapter.error or "no adapter"))
            continue
        provider = adapter.unwrap()
        if not isinstance(provider, OpenAICompatibleProvider):
            probes.append(
                not_tried(
                    name,
                    url,
                    model,
                    "this adapter has no HTTP chat endpoint to probe",
                    probed=False,
                )
            )
            continue
        if not url:
            # Never guess a host: a provider with no url is not contacted.
            probes.append(
                not_tried(
                    name, url, model, "no url is set for this provider in ract.yaml"
                )
            )
            continue
        probes.append(probe_provider(name, provider, url=url, model=model))
    for probe in probes:
        probe.repo_named = (
            bool(probe.url) and repository_named_host(probe.url) is not None
        )
    return probes


def _missing_key_variable(settings: dict[str, Any]) -> str:
    """The ``${VAR}`` name in ``api_key`` when that variable is unset, else ''."""
    key = settings.get("api_key")
    if not isinstance(key, str):
        return ""
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", key)
    if match and not os.environ.get(match.group(1)):
        return match.group(1)
    return ""
