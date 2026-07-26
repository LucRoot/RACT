"""``FakeProvider`` — a canned-response provider for the conformance harness.

Ships with the module_04 tests so ``ract conformance run --provider fake``
exercises the full loop end-to-end without live API keys. Real
providers register via a subclass of ``ProviderAdapter`` that also
satisfies the ``Provider`` protocol; the ``FakeProvider`` is scoped to
the conformance suite.

Test authors pass a ``responses`` dict keyed by ``intent_id``; the
provider returns exactly what the test author declared, so the full
gate loop (compile schema → send → parse → validate → score → write
report → router reads report → gate admits or refuses) is deterministic
in CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ract.providers.provider import ResponseShape


@dataclass
class FakeProvider:
    """A ``Provider``-shaped canned-response fixture.

    ``responses`` maps ``intent_id`` (and the ``__retry`` suffix used by
    the schema-compliance retry) to a raw response — either a dict or a
    JSON string. Unknown intent ids return the ``default_response``.
    """

    name: str = "fake"
    response_shape: ResponseShape = "structured_outputs"
    responses: dict[str, Any] = field(default_factory=dict)
    default_response: Any = field(
        default_factory=lambda: {
            "step_id": "unknown",
            "action": {
                "kind": "read_file",
                "path": "src/unknown.py",
                "rationale": "",
            },
            "depends_on": [],
            "assumptions": [],
            "postconditions": [],
        }
    )
    call_log: list[str] = field(default_factory=list)

    def send_planned_step_request(
        self,
        *,
        prompt: str,
        schema_payload: Any,
        intent_id: str,
    ) -> str | dict[str, Any]:
        _ = prompt, schema_payload  # accepted for protocol conformance
        self.call_log.append(intent_id)
        response = self.responses.get(intent_id, self.default_response)
        # If the author registered a JSON string, hand it back as-is;
        # ResponseValidator handles the decode.
        if isinstance(response, str):
            return response
        # Deep-copy via json round-trip so the caller cannot mutate the
        # registered response through the returned reference.
        return json.loads(json.dumps(response))


__all__ = ["FakeProvider"]


# RACT 0.4.0
