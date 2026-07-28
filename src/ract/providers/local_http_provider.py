from __future__ import annotations


"""Local HTTP provider adapter for RACT.

A thin wrapper for local inference servers that expose an OpenAI-compatible
endpoint without authentication. It delegates to OpenAICompatibleProvider with
api_key='no-key' so the harness can treat local servers as a distinct slot.
"""

from typing import Any

from ract.providers.openai_provider import OpenAICompatibleProvider


class LocalHttpProvider(OpenAICompatibleProvider):
    """Adapter for a local OpenAI-compatible HTTP server."""

    def __init__(self, config: dict[str, Any]) -> None:
        # LR:: Force no authentication for local servers and default model to 'local'.
        config.setdefault("api_key", "no-key")
        config.setdefault("model", "local")
        super().__init__(config)

    @property
    def name(self) -> str:
        return "local_http"

    def capabilities(self) -> set[str]:
        return {"chat", "code", "streaming"}

    def health_check(self) -> bool:
        """Return True if the local endpoint responds to /models without auth."""
        try:
            response = self.client.get(f"{self.url}/models")
            response.raise_for_status()
        except Exception:  # noqa: BLE001
            return False
        return True

    def _post_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a single chat-completions request without authentication.

        LR:: Local servers (llama-server, vLLM, or any OpenAI-compatible local
        proxy) often reject an Authorization header even when the key is empty.
        We omit it entirely.
        """
        response = self.client.post(
            f"{self.url}/chat/completions",
            headers={"Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def _stream_headers(self) -> dict[str, str]:
        """Omit the Authorization header for local, unauthenticated servers."""
        return {"Content-Type": "application/json"}

    def close(self) -> None:
        if hasattr(self, "client") and self.client is not None:
            self.client.close()


# RACT 0.1.1 - Trust and tooling
