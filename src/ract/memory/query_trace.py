"""Query trace value type for the retrieve primitive.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §The
retrieve primitive + §Signals items 3-6. Every :func:`retrieve` call
constructs a :class:`QueryTrace` and returns it inside the
:class:`~ract.memory.retrieve.RetrievalBundle`. The trace records
which indexes were queried, how many candidates each returned, which
cascade level the primitive ended at, and every dropped symbol name.

:func:`to_canonical_json` renders a trace as a canonical JSON string
(sorted keys, no whitespace). Used both by the query cache (as part
of the cache key digest) and by the event trace's null-sink emitter.

The trace is deliberately dataclass-free of any provider handle so
serialisation is closed over primitive types. Sink emitters project
the trace through :func:`to_canonical_json`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ract.canonical import dumps_jcs


@dataclass(frozen=True)
class IndexHit:
    """One index invocation inside a retrieve call.

    - ``index_kind`` — ``symbol`` / ``graph`` / ``semantic``.
    - ``operation`` — the specific query method that fired (e.g.
      ``find_by_name`` / ``callers_of`` / ``search`` /
      ``blast_radius``).
    - ``candidate_count`` — how many rows the index returned before
      cascade formatting and packing.
    - ``elapsed_ms`` — wall-clock cost of the invocation.
    """

    index_kind: str
    operation: str
    candidate_count: int
    elapsed_ms: int


@dataclass(frozen=True)
class CascadeStep:
    """One cascade downgrade event.

    - ``from_level`` — cascade level that failed to fit under budget.
    - ``to_level`` — cascade level the primitive fell through to.
    - ``dropped_symbols_count`` — symbols dropped at ``from_level``.
    - ``candidate_count`` — candidate pool at the new level.
    """

    from_level: int
    to_level: int
    dropped_symbols_count: int
    candidate_count: int


@dataclass(frozen=True)
class QueryTrace:
    """Trace record for one :func:`retrieve` call.

    - ``index_hits`` — every index invocation in call order.
    - ``cascade_steps`` — every downgrade event in occurrence order.
    - ``final_level`` — the cascade level the bundle was drawn from
      (1-4, or 0 when the query was refused).
    - ``cache_hit`` — ``True`` when the bundle came from
      :class:`~ract.memory.cache.RetrievalCache` rather than a fresh
      cascade.
    - ``dropped_symbols`` — names of every symbol dropped at the
      final level (empty on a satisfied Level-1 bundle).
    - ``error`` — non-empty string when the retrieve returned an
      empty bundle for a structural reason (index not populated,
      empty query). Callers inspect this before treating an empty
      bundle as "nothing matched".
    - ``depth`` — mid-invocation nesting depth (Lateral Chain B). ``0``
      for top-level retrieves; ``1`` for a plan-driven sub-retrieve.
      Values above 1 are refused with
      :class:`~ract.memory.retrieve.NestedRetrievalError`.
    - ``parent_call_id`` — hex id of the parent retrieve when nested;
      empty on top-level calls.
    """

    index_hits: tuple[IndexHit, ...] = field(default_factory=tuple)
    cascade_steps: tuple[CascadeStep, ...] = field(default_factory=tuple)
    final_level: int = 0
    cache_hit: bool = False
    dropped_symbols: tuple[str, ...] = field(default_factory=tuple)
    error: str = ""
    depth: int = 0
    parent_call_id: str = ""


def to_canonical_json(trace: QueryTrace) -> str:
    """Return a canonical JSON representation of ``trace``.

    Keys are sorted; separators use ``(,, :)`` (no whitespace) so the
    output is byte-stable across Python versions and dict-ordering
    changes. The cache-key digest reads this projection so equivalent
    traces produce equivalent keys.
    """
    payload = {
        "cache_hit": trace.cache_hit,
        "cascade_steps": [
            {
                "from_level": step.from_level,
                "to_level": step.to_level,
                "dropped_symbols_count": step.dropped_symbols_count,
                "candidate_count": step.candidate_count,
            }
            for step in trace.cascade_steps
        ],
        "depth": trace.depth,
        "dropped_symbols": list(trace.dropped_symbols),
        "error": trace.error,
        "final_level": trace.final_level,
        "index_hits": [
            {
                "index_kind": hit.index_kind,
                "operation": hit.operation,
                "candidate_count": hit.candidate_count,
                "elapsed_ms": hit.elapsed_ms,
            }
            for hit in trace.index_hits
        ],
        "parent_call_id": trace.parent_call_id,
    }
    # v0.5.1 module_03: RFC 8785 JCS canonical bytes.
    return dumps_jcs(payload).decode("utf-8")


__all__ = [
    "CascadeStep",
    "IndexHit",
    "QueryTrace",
    "to_canonical_json",
]


from ract.core.module_identity import _module_knot, register_module_knot  # noqa: E402

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
