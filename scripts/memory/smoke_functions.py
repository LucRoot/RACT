"""Smoke script for the four v0.5.0 function contracts.

Runs a round-trip against the mock provider using the tiny_repo
fixture at ``tests/memory/fixtures/tiny_repo``. Exits 0 on success;
non-zero on any function raising unexpectedly.

Usage:

    python -m scripts.memory.smoke_functions

or

    python scripts/memory/smoke_functions.py

The script mirrors the DoD "smoke script completes a round-trip"
item and stays independent of pytest so a fresh machine with just
``pip install -e .[dev]`` can exercise the pipeline.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


def _bootstrap_path() -> None:
    here = Path(__file__).resolve()
    root = here.parent.parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


_bootstrap_path()


from ract.memory.functions import (  # noqa: E402
    IndexBundle,
    IntakeContext,
    edit,
    intake,
    plan,
    research,
)
from ract.memory.functions.testing import MockProvider  # noqa: E402
from ract.memory.session import SessionMemory  # noqa: E402
from ract.memory.symbol_index import SymbolIndex, SymbolRow  # noqa: E402


def _seed_symbol_index(sym: SymbolIndex, tmp_root: Path) -> int:
    body = "def greet():\n    return 'hi'\n"
    file_path = tmp_root / "greet.py"
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
        token_count=6,
        updated_at=1,
    )
    return sym.insert_or_update(row)


def _canned_provider() -> MockProvider:
    return MockProvider(
        responses_by_function={
            "intake": json.dumps(
                {
                    "request_type": "refactor",
                    "scope_hints": {
                        "mentioned_symbols": ["greet"],
                        "mentioned_files": [],
                        "mentioned_directories": [],
                        "keywords": ["rename"],
                        "exclude_paths": [],
                    },
                    "success_criteria": ["all callers use the new name"],
                    "constraints": ["public API compatibility"],
                    "priority_markers": {},
                    "ambiguity_flags": [],
                }
            ),
            "research": json.dumps(
                {
                    "relevant_symbols": [
                        {
                            "name": "greet",
                            "file_path": "greet.py",
                            "kind": "function",
                            "rationale": "target of the rename",
                        }
                    ],
                    "call_neighborhood": [],
                    "architectural_context": "one-function module.",
                    "similar_prior_work": [],
                    "risk_zones": [],
                }
            ),
            "plan": json.dumps(
                {
                    "target_symbols": [
                        {
                            "name": "greet",
                            "file_path": "greet.py",
                            "kind": "function",
                            "action": "rename",
                            "notes": "greet -> say_hello",
                        }
                    ],
                    "load_manifest": [
                        {"name": "greet", "file_path": "greet.py", "kind": "function"}
                    ],
                    "invariants": [],
                    "verification_criteria": [
                        {"predicate_id": "P1", "kind": "test_passes", "payload": {}}
                    ],
                    "risk_assessment": {"level": "low", "rationale": "one call site."},
                    "iteration_bound": 1,
                }
            ),
            "edit": json.dumps(
                {
                    "unified_diff": (
                        "--- a/greet.py\n"
                        "+++ b/greet.py\n"
                        "@@ -1,2 +1,2 @@\n"
                        "-def greet():\n"
                        "+def say_hello():\n"
                        "     return 'hi'\n"
                    ),
                    "hunks": [
                        {
                            "file_path": "greet.py",
                            "start_line": 1,
                            "end_line": 2,
                            "summary": "rename greet to say_hello",
                        }
                    ],
                }
            ),
        },
    )


def main() -> int:
    td = tempfile.mkdtemp(prefix="ract_smoke_")
    tmp_root = Path(td)
    sym = SymbolIndex(str(tmp_root / "symbols.db"))
    try:
        _seed_symbol_index(sym, tmp_root)
        indexes = IndexBundle(symbol_index=sym)
        provider = _canned_provider()
        session = SessionMemory(session_path=tmp_root / "session.json")

        work_order = intake(
            "rename greet to say_hello",
            IntakeContext(repo_root=tmp_root, symbol_index=sym),
            provider,
        )
        session.set_work_order(work_order)

        research_bundle = research(work_order, indexes, provider)
        session.set_research_bundle(research_bundle)

        change_plan = plan(work_order, research_bundle, indexes, provider)
        session.set_change_plan(change_plan)

        candidate_diff = edit(change_plan, indexes, provider)
        session.set_candidate_diff(candidate_diff)

        print(
            f"smoke ok: {len(candidate_diff.hunks)} hunk(s); "
            f"session persisted to {session.session_path}"
        )
    finally:
        sym.close()
        import shutil

        shutil.rmtree(td, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
