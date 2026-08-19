"""Tests for :func:`ract.memory.functions.research.research`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.memory.functions import (
    EmptyResearchError,
    IndexBundle,
    RequestType,
    ScopeHints,
    WorkOrder,
    research,
)
from ract.memory.functions.testing import MockProvider
from ract.memory.symbol_index import SymbolIndex, SymbolRow


def _seed_greet(sym: SymbolIndex, tmp_path: Path) -> int:
    body = "def greet():\n    return 'hi'\n"
    file_path = tmp_path / "greet.py"
    file_path.write_text(body, encoding="utf-8")
    row = SymbolRow(
        id=None,
        name="greet",
        kind="function",
        file_path=str(file_path),
        start_line=1,
        end_line=2,
        signature="def greet():",
        docstring=None,
        visibility="public",
        parent_symbol_id=None,
        language="python",
        content_hash="hash-greet",
        token_count=5,
        updated_at=1,
    )
    return sym.insert_or_update(row)


def _greet_work_order() -> WorkOrder:
    return WorkOrder(
        request_type=RequestType.REFACTOR,
        scope_hints=ScopeHints(mentioned_symbols=("greet",), keywords=("rename",)),
        success_criteria=("call sites use new name",),
        constraints=(),
    )


def _canned_research() -> str:
    return json.dumps(
        {
            "relevant_symbols": [
                {
                    "name": "greet",
                    "file_path": "greet.py",
                    "kind": "function",
                    "rationale": "target of the rename",
                }
            ],
            "call_neighborhood": [
                {
                    "name": "main",
                    "file_path": "main.py",
                    "signature": "def main():",
                    "direction": "caller",
                }
            ],
            "architectural_context": "one-function module.",
            "similar_prior_work": [],
            "risk_zones": [],
        }
    )


def test_research_returns_bundle_for_tiny_repo(tmp_path: Path):
    sym = SymbolIndex(str(tmp_path / "symbols.db"))
    _seed_greet(sym, tmp_path)
    indexes = IndexBundle(symbol_index=sym)
    provider = MockProvider(responses_by_function={"research": _canned_research()})
    bundle = research(_greet_work_order(), indexes, provider)
    assert len(bundle.relevant_symbols) == 1
    assert bundle.relevant_symbols[0].symbol.name == "greet"
    assert bundle.relevant_symbols[0].rationale
    assert len(bundle.call_neighborhood) == 1
    assert bundle.call_neighborhood[0].direction == "caller"


def test_research_empty_relevant_raises(tmp_path: Path):
    sym = SymbolIndex(str(tmp_path / "symbols.db"))
    _seed_greet(sym, tmp_path)
    indexes = IndexBundle(symbol_index=sym)
    empty_response = json.dumps(
        {
            "relevant_symbols": [],
            "call_neighborhood": [],
            "architectural_context": "nothing.",
            "similar_prior_work": [],
            "risk_zones": [],
        }
    )
    provider = MockProvider(responses_by_function={"research": empty_response})
    with pytest.raises(EmptyResearchError):
        research(_greet_work_order(), indexes, provider)


def test_research_prompt_version_metadata(tmp_path: Path):
    sym = SymbolIndex(str(tmp_path / "symbols.db"))
    _seed_greet(sym, tmp_path)
    indexes = IndexBundle(symbol_index=sym)
    provider = MockProvider(responses_by_function={"research": _canned_research()})
    bundle = research(_greet_work_order(), indexes, provider)
    metadata = dict(bundle.metadata)
    assert metadata.get("prompt_version") == "v1"


def test_research_runs_without_indexes(tmp_path: Path):
    provider = MockProvider(responses_by_function={"research": _canned_research()})
    bundle = research(_greet_work_order(), IndexBundle(), provider)
    assert bundle.relevant_symbols
