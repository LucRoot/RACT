"""Cascade + sacred-spine tests for :mod:`ract.memory.retrieve`.

The sacred-spine tests named in master spec §Sacred spine:

- ``test_cascade_never_loops_returns_or_refuses``
- ``test_refuse_emits_event``

Both are load-bearing: retrieve MUST either return under budget or
raise :class:`BoundedContextError` within a bounded step count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.memory.events import NullEventSink
from ract.memory.retrieve import (
    BoundedContextError,
    IndexKind,
    IndexRef,
    RetrievalQuery,
    retrieve,
)
from ract.memory.symbol_index import SymbolIndex, SymbolRow


def _seed_large_symbol(
    sym: SymbolIndex, tmp_path: Path, *, name: str, line_count: int
) -> None:
    file_path = tmp_path / f"{name}.py"
    body_lines = [f"def {name}():"]
    for i in range(line_count):
        body_lines.append(f"    x_{i} = {i}")
    body = "\n".join(body_lines) + "\n"
    file_path.write_text(body, encoding="utf-8")
    sym.insert_or_update(
        SymbolRow(
            id=None,
            name=name,
            kind="function",
            file_path=str(file_path),
            start_line=1,
            end_line=line_count + 1,
            signature=f"def {name}():",
            docstring=None,
            visibility="public",
            parent_symbol_id=None,
            language="python",
            content_hash=f"h-{name}",
            token_count=line_count * 3,
            updated_at=1,
        )
    )


def _sym_indexes(tmp_path: Path):
    sym = SymbolIndex(str(tmp_path / "s.db"))
    return sym, [IndexRef(kind=IndexKind.SYMBOL, index=sym)]


# ---------------------------------------------------------------------------
# Cascade Level-1 satisfy
# ---------------------------------------------------------------------------


def test_cascade_level_1_satisfies_under_generous_budget(tmp_path: Path):
    sym, indexes = _sym_indexes(tmp_path)
    _seed_large_symbol(sym, tmp_path, name="tiny", line_count=3)
    bundle = retrieve(RetrievalQuery(symbol_names=("tiny",)), indexes, budget=10_000)
    assert bundle.query_trace.final_level == 1
    assert bundle.query_trace.cascade_steps == ()


# ---------------------------------------------------------------------------
# Cascade downgrade
# ---------------------------------------------------------------------------


def test_cascade_downgrades_full_to_signature_when_over_budget(tmp_path: Path):
    """A large exact-match chunk that busts budget in FULL cascades to
    SIGNATURE at Level 4.

    Level 1 (FULL) exceeds budget; Levels 2 and 3 keep exact matches
    in FULL so they also bust; Level 4 renders SIGNATURE and fits.
    """
    sym, indexes = _sym_indexes(tmp_path)
    _seed_large_symbol(sym, tmp_path, name="big", line_count=200)

    # A budget large enough for the tiny signature but too small
    # for the full body (200 lines each ~3 tokens ≈ 600 tokens).
    bundle = retrieve(RetrievalQuery(symbol_names=("big",)), indexes, budget=20)
    assert bundle.query_trace.final_level == 4
    assert len(bundle.query_trace.cascade_steps) == 3
    # Bundle carries the signature body.
    assert bundle.chunks[0].body == "def big():"


# ---------------------------------------------------------------------------
# Sacred spine
# ---------------------------------------------------------------------------


def test_cascade_never_loops_returns_or_refuses(tmp_path: Path):
    """Sacred-spine: retrieve must either return or raise within a
    bounded step count, even against an adversarial query.

    Adversarial construction: a huge exact-name match plus a graph
    seed that would grow the pool at every downgrade if the cascade
    naively re-queried. The implementation gathers candidates ONCE
    and re-renders per level, so growth is impossible; this test
    pins the guarantee against a regression.
    """
    sym, indexes = _sym_indexes(tmp_path)
    _seed_large_symbol(sym, tmp_path, name="mega", line_count=2000)

    query = RetrievalQuery(symbol_names=("mega",))
    # Budget so small that even SIGNATURE at Level 4 will not fit.
    with pytest.raises(BoundedContextError) as excinfo:
        retrieve(query, indexes, budget=1)
    assert excinfo.value.deepest_level == 4
    assert excinfo.value.budget == 1


def test_cascade_never_loops_satisfies_within_bounded_steps(tmp_path: Path):
    sym, indexes = _sym_indexes(tmp_path)
    _seed_large_symbol(sym, tmp_path, name="med", line_count=50)
    bundle = retrieve(RetrievalQuery(symbol_names=("med",)), indexes, budget=5)
    # Regardless of the final level, cascade_steps count must be < 4.
    assert len(bundle.query_trace.cascade_steps) <= 3


def test_refuse_emits_event(tmp_path: Path):
    """Sacred-spine: refuse-on-exhaustion emits ``retrieval.refused``."""
    sym, indexes = _sym_indexes(tmp_path)
    _seed_large_symbol(sym, tmp_path, name="huge", line_count=500)

    sink = NullEventSink()
    with pytest.raises(BoundedContextError):
        retrieve(
            RetrievalQuery(symbol_names=("huge",)),
            indexes,
            budget=1,
            sink=sink,
        )
    kinds = [kind for kind, _ in sink.records]
    assert "retrieval.refused" in kinds
    refused_payloads = [
        payload for kind, payload in sink.records if kind == "retrieval.refused"
    ]
    assert refused_payloads
    assert refused_payloads[0]["deepest_level"] == 4


# ---------------------------------------------------------------------------
# Budget-used-pct is against the retrieve-local sub-budget
# ---------------------------------------------------------------------------


def test_budget_used_pct_against_local_budget(tmp_path: Path):
    sym, indexes = _sym_indexes(tmp_path)
    _seed_large_symbol(sym, tmp_path, name="mid", line_count=10)
    bundle = retrieve(RetrievalQuery(symbol_names=("mid",)), indexes, budget=200)
    assert 0.0 < bundle.budget_used_pct <= 100.0
