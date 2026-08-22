"""v0.5.1 spec-completeness module_04 SP Q4 DEFECT amendment.

Two :class:`RetrievalQuery` values that differ ONLY in
``grouping_enabled`` produce different bundles (one seats
companions; the other does not). The canonical query projection
consumed by
:func:`ract.memory.cache._cache_key` MUST distinguish them, else
a cache HIT from the ``True`` setting would silently return a
grouped bundle to a caller that asked for the ungrouped one (and
vice versa).

Verifies that :func:`ract.memory.retrieve.canonical_query_payload`
carries ``grouping_enabled`` and that
:func:`ract.memory.retrieve.query_digest` produces distinct
digests for the two settings.
"""

from __future__ import annotations

from ract.memory.retrieve import (
    RetrievalQuery,
    canonical_query_payload,
    query_digest,
)


def test_canonical_payload_includes_grouping_enabled_flag():
    q_on = RetrievalQuery(symbol_names=("Foo",), grouping_enabled=True)
    q_off = RetrievalQuery(symbol_names=("Foo",), grouping_enabled=False)
    payload_on = canonical_query_payload(q_on)
    payload_off = canonical_query_payload(q_off)
    assert "grouping_enabled" in payload_on
    assert "grouping_enabled" in payload_off
    assert payload_on["grouping_enabled"] is True
    assert payload_off["grouping_enabled"] is False


def test_query_digest_differs_for_grouping_enabled_toggle():
    q_on = RetrievalQuery(symbol_names=("Foo",), grouping_enabled=True)
    q_off = RetrievalQuery(symbol_names=("Foo",), grouping_enabled=False)
    d_on = query_digest(q_on)
    d_off = query_digest(q_off)
    assert d_on != d_off, (
        "grouping_enabled must be part of the cache key; otherwise a "
        "cached grouped bundle could be returned to a caller that opted "
        "out of grouping, and vice versa"
    )


def test_canonical_payload_deterministic_for_same_grouping_flag():
    q1 = RetrievalQuery(symbol_names=("Foo",), grouping_enabled=True)
    q2 = RetrievalQuery(symbol_names=("Foo",), grouping_enabled=True)
    assert canonical_query_payload(q1) == canonical_query_payload(q2)
    assert query_digest(q1) == query_digest(q2)
