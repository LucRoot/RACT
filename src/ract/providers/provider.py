"""``Provider`` protocol — the shape the router dispatches on.

SUBSTRATE §5.2 (lateral chain branch D). OpenAI Structured Outputs is
response-shaped; Anthropic tool-use is turn-shaped; the JSON-schema
fallback is prompt-shaped. The converter dispatch runs at request time
and reads the provider's ``response_shape`` to pick the right
serialisation.

This module introduces a ``Provider`` ``typing.Protocol`` that names
that shape without forcing every historical ``ProviderAdapter`` to
implement it — the v0.3 adapters continue to satisfy
``ract.providers.base.ProviderAdapter`` and can additionally satisfy
``Provider`` when a subclass declares ``response_shape``.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable


ResponseShape = Literal["structured_outputs", "tool_use", "json_schema"]
"""Names the wire-format primitive the provider expects.

- ``structured_outputs`` — OpenAI Structured Outputs
  (``response_format={"type": "json_schema", ...}``).
- ``tool_use`` — Anthropic tool-use (``tools=[...]`` list).
- ``json_schema`` — plain JSON schema in the prompt for providers with
  neither primitive; the raw text reply is parsed by
  ``ResponseValidator``.
"""


@runtime_checkable
class Provider(Protocol):
    """Minimum contract the conformance harness and router require.

    Any object that names a ``response_shape`` and implements
    ``send_planned_step_request`` is a ``Provider`` for the purposes of
    module_04. Historical ``ProviderAdapter`` subclasses can satisfy
    this by adding the two members; new adapters implement this
    protocol directly.
    """

    #: The wire-format primitive this provider expects at request time.
    response_shape: ResponseShape

    #: Human-readable provider identifier — logged in report cards.
    name: str

    def send_planned_step_request(
        self,
        *,
        prompt: str,
        schema_payload: Any,
        intent_id: str,
    ) -> str | dict[str, Any]:
        """Send a planned-step request and return the raw response.

        ``schema_payload`` is the return value of the schema converter
        that matches ``response_shape``. The provider is responsible for
        wiring it into its SDK's request. The return value is either a
        JSON string (fallback / structured outputs) or a pre-parsed
        dict (tool use).

        ``intent_id`` is used only to key the response cache
        (``evals/conformance/cache/<provider>/<intent_id>.json``); it
        is opaque to the provider.
        """
        ...  # pragma: no cover — protocol


__all__ = ["Provider", "ResponseShape"]


# RACT 0.4.0
