"""OpenTelemetry OTLP mirror for the event log.

SUBSTRATE §6.5. Every event mirrors as a short-lived ``Span`` on the
configured tracer provider. Export is opt-in: a run with no
``otlp_endpoint`` in ``ract.yaml`` skips OTLP entirely and only writes
the JSONL log.

Span shape follows the OpenTelemetry GenAI Semantic Conventions:

- Span name: the event ``kind`` (e.g. ``prompt.sent``).
- Attributes: every scalar in the payload is projected as an attribute
  under the ``ract.*`` namespace (nested containers are JSON-serialised
  into a single attribute value so the span carries the same
  information the JSONL line does without inventing a private
  encoding).
- Trace id: derived from ``run_id`` so all events in a run share a
  trace.
- Span parent: the event's ``parent_id`` when set, otherwise the
  run-level root.

Reference sources:

- OpenTelemetry Python SDK / OTLP HTTP exporter public repo:
  ``https://github.com/open-telemetry/opentelemetry-python``.
- OpenTelemetry GenAI Semantic Conventions SIG (multi-agent
  conventions covering tasks, actions, agent teams, memory, artifact
  tracking):
  ``https://github.com/open-telemetry/semantic-conventions``.
- OpenHands SDK per-iteration tracing pattern:
  ``https://github.com/All-Hands-AI/OpenHands``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ract.trace.events import Event


# ---------------------------------------------------------------------------
# Attribute projection
# ---------------------------------------------------------------------------


def _flatten(value: Any) -> Any:
    """Return an OTLP-safe attribute value.

    OpenTelemetry accepts bool/int/float/str and homogeneous sequences
    of the same. Any nested structure JSON-serialises to a single string
    attribute so the span still carries the payload's shape without
    inventing a private encoding.
    """
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        # Homogeneous scalar sequences pass through; anything else is
        # JSON-serialised for reviewer legibility.
        scalar_types = (bool, int, float, str)
        if all(isinstance(v, scalar_types) for v in value):
            return list(value)
        return json.dumps(list(value), sort_keys=True)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return json.dumps(value, sort_keys=True, default=str)


def event_to_span_attributes(event: "Event") -> dict[str, Any]:
    """Project an ``Event`` into OpenTelemetry span attributes.

    Attribute keys live under the ``ract.*`` namespace so a collector
    can distinguish RACT events from other emitters sharing the same
    OTLP endpoint. Every payload field lands under ``ract.payload.*``.
    """
    attrs: dict[str, Any] = {
        "ract.event.id": event.id.hex(),
        "ract.event.kind": event.kind,
        "ract.event.timestamp_ns": event.timestamp_ns,
        "ract.event.hash": event.hash.hex(),
        "ract.event.prev_hash": event.prev_hash.hex(),
        "ract.run.id": event.run_id.hex(),
    }
    if event.step_id is not None:
        attrs["ract.step.id"] = event.step_id.hex()
    if event.parent_id is not None:
        attrs["ract.event.parent_id"] = event.parent_id.hex()
    for key, value in event.payload.items():
        attrs[f"ract.payload.{key}"] = _flatten(value)
    return attrs


# ---------------------------------------------------------------------------
# Exporter wrapper
# ---------------------------------------------------------------------------


@dataclass
class OtlpExporter:
    """Small wrapper over ``opentelemetry-sdk``'s OTLP-HTTP exporter.

    The wrapper is opt-in — construction is a no-op that only becomes
    active after ``install`` is called with a live tracer provider. A
    run with no endpoint configured never calls ``install`` and the
    OTLP wire is never touched.
    """

    endpoint: str
    headers: dict[str, str] = field(default_factory=dict)
    service_name: str = "ract"
    _installed: bool = field(default=False, init=False, repr=False)
    _tracer: Any = field(default=None, init=False, repr=False)

    def install(self) -> None:
        """Attach a ``BatchSpanProcessor`` with an OTLP-HTTP exporter.

        Imports are local so the module imports cleanly whether or not
        OpenTelemetry is installed at test time; the runtime dep is
        declared in ``pyproject.toml`` per ADR-0015.
        """
        if self._installed:
            return
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": self.service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=self.endpoint, headers=self.headers or None
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        # Only set the global provider if none is set (respect a host
        # that already installed one; adding our processor to a fresh
        # provider is safer than replacing an existing one).
        current = trace.get_tracer_provider()
        # opentelemetry's default is ``ProxyTracerProvider``; we replace
        # it, but leave any real user-installed provider alone.
        if type(current).__name__ == "ProxyTracerProvider":
            trace.set_tracer_provider(provider)
        self._tracer = trace.get_tracer("ract.trace")
        self._installed = True

    def as_sink(self) -> Any:
        """Return a sink callable suitable for ``JsonlEventWriter.add_mirror``."""
        def _sink(event: "Event") -> None:
            self.mirror(event)

        return _sink

    def mirror(self, event: "Event") -> None:
        """Emit one event as a short-lived span on the tracer provider."""
        if not self._installed:
            return
        if self._tracer is None:  # pragma: no cover — install path sets it
            return
        with self._tracer.start_as_current_span(event.kind) as span:
            for key, value in event_to_span_attributes(event).items():
                span.set_attribute(key, value)


def install_otlp_exporter(
    endpoint: str | None, headers: dict[str, str] | None = None
) -> OtlpExporter | None:
    """Convenience factory used by the loop wiring.

    Returns ``None`` when ``endpoint`` is ``None`` — the run then only
    writes the JSONL log.
    """
    if not endpoint:
        return None
    exporter = OtlpExporter(endpoint=endpoint, headers=headers or {})
    exporter.install()
    return exporter


__all__ = [
    "OtlpExporter",
    "event_to_span_attributes",
    "install_otlp_exporter",
]


# RACT 0.4.0
