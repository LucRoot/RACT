# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""OpenAI-compatible provider adapter for RootAct.

Works with OpenAI, Azure OpenAI, and any server that exposes an OpenAI-compatible
chat completions endpoint (e.g., llama-server, vLLM, or a local proxy).
"""

import json
import os
import time
from collections.abc import Iterator
from typing import Any

import httpx

from rootact.providers.base import ProviderAdapter
from rootact.retry_policy import RetryConfig, RetryPolicy
from rootact.rooted import Rooted


class OpenAICompatibleProvider(ProviderAdapter):
    """Adapter for OpenAI-compatible HTTP endpoints."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.url = config.get(
            "url",
            config.get(
                "base_url",
                os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            ),
        ).rstrip("/")
        self.api_key = config.get("api_key", os.environ.get("OPENAI_API_KEY", "no-key"))
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
                jitter=False,
            )
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

    def health_check(self) -> bool:
        """Return True if the OpenAI-compatible endpoint responds to /models."""
        try:
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
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()

    def _is_retryable(self, exc: Exception) -> bool:
        """Return True when the exception warrants a retry."""
        if isinstance(exc, httpx.RequestError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            if code >= 500:
                return True
            if code == 429 and self.retry_on_429:
                return True
        return False

    def _post_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a single chat-completions request and return parsed JSON."""
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
        payload = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        start = time.perf_counter()
        data, last_error = self._retry_policy.execute(
            lambda: self._post_completion(payload),
            self._is_retryable,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        if last_error is not None:
            if isinstance(last_error, httpx.HTTPStatusError):
                return Rooted(
                    value=None,
                    assumption="The OpenAI-compatible endpoint accepts the request and returns valid JSON.",
                    confidence=0.0,
                    provenance=["openai.complete"],
                    error=f"HTTP {last_error.response.status_code}: {last_error.response.text[:200]}",
                )
            if isinstance(last_error, httpx.RequestError):
                return Rooted(
                    value=None,
                    assumption="The OpenAI-compatible endpoint is reachable.",
                    confidence=0.0,
                    provenance=["openai.complete"],
                    error=f"Request failed after {self.max_retries} attempts: {last_error}",
                )
            return Rooted(
                value=None,
                assumption="The provider completed without an unhandled exception.",
                confidence=0.0,
                provenance=["openai.complete"],
                error=f"Unexpected error after {self.max_retries} attempts: {last_error}",
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

    def _stream_headers(self) -> dict[str, str]:
        """Return headers used for streaming chat-completions requests.

        Subclasses may override this to omit authentication for local servers.
        """
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
        payload = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        try:
            with self.client.stream(
                "POST",
                f"{self.url}/chat/completions",
                headers=self._stream_headers(),
                json=payload,
            ) as response:
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
                            error=f"Unexpected SSE line: {line[:200]}",
                        )
        except httpx.HTTPStatusError as exc:
            yield Rooted(
                value=None,
                assumption="The OpenAI-compatible endpoint accepts the streaming request.",
                confidence=0.0,
                provenance=["openai.complete_stream"],
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
            )
            return
        except httpx.RequestError as exc:
            yield Rooted(
                value=None,
                assumption="The OpenAI-compatible endpoint is reachable.",
                confidence=0.0,
                provenance=["openai.complete_stream"],
                error=f"Request failed: {exc}",
            )
            return


# RACT 0.1.1 - Trust and Tooling
