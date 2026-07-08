# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Base provider adapter for RootAct.

Every LLM or tool provider implements this small protocol. The harness and router
consume the protocol, not concrete SDKs, so users can add new providers without
changing core code.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from rootact.rooted import Rooted


class ProviderAdapter(ABC):
    """Abstract adapter for a language model or tool provider."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Adapters are constructed from their config slot."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider identifier, e.g. 'openai' or 'local'."""

    @abstractmethod
    def models(self) -> list[str]:
        """Return the model identifiers this adapter can reach."""

    @abstractmethod
    def capabilities(self) -> set[str]:
        """Return capability tags, e.g. {'chat', 'code', 'embed'}."""

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict[str, Any]]:
        """Run a chat completion and return a Rooted raw response dict."""

    def complete_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Iterator[Rooted[dict[str, Any]]]:
        """Optional streaming completion.

        Default implementation yields a single failure chunk so callers can
        fall back to ``complete`` when the adapter does not support streaming.
        """
        yield Rooted(
            value=None,
            assumption=f"Provider '{self.name}' supports streaming completions.",
            confidence=0.0,
            provenance=["complete_stream"],
            error=f"Provider '{self.name}' does not support streaming completions.",
        )

    def embed(self, text: str) -> Rooted[list[float]]:
        """Optional embedding support. Default: fail fast with a clear reason."""
        return Rooted(
            value=None,
            assumption=f"Provider '{self.name}' supports embeddings.",
            confidence=0.0,
            provenance=["embed"],
            error=f"Provider '{self.name}' does not support embeddings.",
        )

    def health_check(self) -> bool:
        """Return True if the provider appears reachable.

        Default implementation returns True so conservative adapters are not
        penalized. Adapters that open connections should override this with a
        lightweight probe (e.g., list models).
        """
        return True

    def close(self) -> None:
        """Release any persistent resources. Adapters that keep clients open
        should override this."""
        pass

    def input_cost_per_1k(self) -> float | None:
        """Optional input-token cost in currency units per 1K tokens."""
        return None

    def output_cost_per_1k(self) -> float | None:
        """Optional output-token cost in currency units per 1K tokens."""
        return None


# RACT 0.1.0 - Initial Public Release
