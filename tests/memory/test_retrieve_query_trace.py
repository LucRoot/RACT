"""Tests for :mod:`ract.memory.query_trace`."""

from __future__ import annotations

import json

from ract.memory.query_trace import (
    CascadeStep,
    IndexHit,
    QueryTrace,
    to_canonical_json,
)


def test_default_query_trace_is_empty():
    trace = QueryTrace()
    assert trace.index_hits == ()
    assert trace.cascade_steps == ()
    assert trace.final_level == 0
    assert trace.cache_hit is False
    assert trace.error == ""
    assert trace.depth == 0


def test_to_canonical_json_sorted_and_stable():
    trace = QueryTrace(
        index_hits=(
            IndexHit(
                index_kind="symbol",
                operation="find_by_name",
                candidate_count=3,
                elapsed_ms=1,
            ),
            IndexHit(
                index_kind="graph",
                operation="callers_of",
                candidate_count=2,
                elapsed_ms=2,
            ),
        ),
        cascade_steps=(
            CascadeStep(
                from_level=1, to_level=2, dropped_symbols_count=0, candidate_count=5
            ),
        ),
        final_level=2,
        cache_hit=False,
        dropped_symbols=("obsolete_helper",),
        error="",
        depth=0,
        parent_call_id="",
    )
    canon = to_canonical_json(trace)
    parsed = json.loads(canon)
    assert parsed["final_level"] == 2
    assert parsed["index_hits"][0]["index_kind"] == "symbol"
    assert parsed["cascade_steps"][0]["from_level"] == 1
    # Byte-stable: same trace produces same string.
    assert canon == to_canonical_json(trace)


def test_to_canonical_json_carries_error_marker():
    trace = QueryTrace(error="index_not_populated")
    canon = to_canonical_json(trace)
    assert '"error":"index_not_populated"' in canon
