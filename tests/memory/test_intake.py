"""Tests for :func:`ract.memory.functions.intake.intake`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.memory.budget import BudgetAccountant
from ract.memory.budget_registry import get as budget_get
from ract.memory.events import NullEventSink
from ract.memory.functions import (
    INTAKE_FUNCTION_NAME,
    IntakeContext,
    ProviderContractError,
    RequestType,
    intake,
)
from ract.memory.functions.testing import MockProvider
from ract.memory.symbol_index import SymbolIndex, SymbolRow


def _seed_user_class(sym: SymbolIndex, tmp_path: Path) -> int:
    body = "class User:\n    def __init__(self, name):\n        self.name = name\n"
    file_path = tmp_path / "user.py"
    file_path.write_text(body, encoding="utf-8")
    row = SymbolRow(
        id=None,
        name="User",
        kind="class",
        file_path=str(file_path),
        start_line=1,
        end_line=3,
        signature="class User:",
        docstring=None,
        visibility="public",
        parent_symbol_id=None,
        language="python",
        content_hash="hash-User",
        token_count=8,
        updated_at=1,
    )
    return sym.insert_or_update(row)


def _rename_response() -> str:
    return json.dumps(
        {
            "request_type": "refactor",
            "scope_hints": {
                "mentioned_symbols": ["User"],
                "mentioned_files": [],
                "mentioned_directories": [],
                "keywords": ["rename", "Account"],
                "exclude_paths": [],
            },
            "success_criteria": ["all callers use Account"],
            "constraints": [],
            "priority_markers": {},
            "ambiguity_flags": [],
        }
    )


def test_intake_returns_work_order_for_rename(tmp_path: Path):
    sym = SymbolIndex(str(tmp_path / "symbols.db"))
    _seed_user_class(sym, tmp_path)
    provider = MockProvider(responses_by_function={"intake": _rename_response()})
    result = intake(
        "rename the User class to Account",
        IntakeContext(repo_root=tmp_path, symbol_index=sym),
        provider,
    )
    assert result.request_type is RequestType.REFACTOR
    assert result.scope_hints.mentioned_symbols == ("User",)
    assert result.ambiguity_flags == ()
    assert provider.call_log[0][0] == INTAKE_FUNCTION_NAME


def test_intake_ambiguity_flags_propagate(tmp_path: Path):
    sym = SymbolIndex(str(tmp_path / "symbols.db"))
    response = json.dumps(
        {
            "request_type": "other",
            "scope_hints": {
                "mentioned_symbols": [],
                "mentioned_files": [],
                "mentioned_directories": [],
                "keywords": [],
                "exclude_paths": [],
            },
            "success_criteria": [],
            "constraints": [],
            "priority_markers": {},
            "ambiguity_flags": ["target unclear"],
        }
    )
    provider = MockProvider(responses_by_function={"intake": response})
    result = intake(
        "make it better",
        IntakeContext(repo_root=tmp_path, symbol_index=sym),
        provider,
    )
    assert result.ambiguity_flags == ("target unclear",)
    assert result.request_type is RequestType.OTHER


def test_intake_raises_on_invalid_json(tmp_path: Path):
    provider = MockProvider(responses_by_function={"intake": "not json"})
    with pytest.raises(ProviderContractError):
        intake(
            "rename User",
            IntakeContext(repo_root=tmp_path),
            provider,
        )


def test_intake_raises_on_unknown_request_type(tmp_path: Path):
    provider = MockProvider(
        responses_by_function={
            "intake": json.dumps(
                {
                    "request_type": "shrug",
                    "scope_hints": {
                        "mentioned_symbols": [],
                        "mentioned_files": [],
                        "mentioned_directories": [],
                        "keywords": [],
                        "exclude_paths": [],
                    },
                    "success_criteria": [],
                    "constraints": [],
                    "priority_markers": {},
                    "ambiguity_flags": [],
                }
            )
        }
    )
    with pytest.raises(ProviderContractError):
        intake(
            "do something",
            IntakeContext(repo_root=tmp_path),
            provider,
        )


def test_intake_seats_sections_and_emits_declared(tmp_path: Path):
    sym = SymbolIndex(str(tmp_path / "symbols.db"))
    _seed_user_class(sym, tmp_path)
    provider = MockProvider(responses_by_function={"intake": _rename_response()})
    sink = NullEventSink()
    declaration = budget_get(INTAKE_FUNCTION_NAME)
    accountant = BudgetAccountant(declaration=declaration)
    intake(
        "rename User class to Account",
        IntakeContext(repo_root=tmp_path, symbol_index=sym),
        provider,
        accountant=accountant,
        sink=sink,
    )
    # All five sections seated.
    section_names = {s.name for s in accountant.sections()}
    assert section_names == {
        "system_prompt",
        "contract",
        "state",
        "retrieved_bundle",
        "inputs",
    }
    # budget.declared emitted.
    assert any(rec[0] == "budget.declared" for rec in sink.records)


def test_intake_uses_prompt_version_metadata(tmp_path: Path):
    sym = SymbolIndex(str(tmp_path / "symbols.db"))
    provider = MockProvider(responses_by_function={"intake": _rename_response()})
    result = intake(
        "rename User to Account",
        IntakeContext(repo_root=tmp_path, symbol_index=sym),
        provider,
    )
    metadata = dict(result.metadata)
    assert metadata.get("prompt_version") == "v1"
