#!/usr/bin/env python3
"""Smoke-check the shipped BudgetDeclaration defaults.

Depth Chain leaf (d): first live run under module_01 constructs a
canonical assembly against a small in-memory workspace and asserts the
seated total fits inside the ``edit`` default budget. When module_02
lands the fixture repo this script gains a fixture-repo path; today
it exercises a static in-memory shape so the smoke gate is executable
at module_01 close.

Usage:

    python scripts/memory/smoke_budget_defaults.py

Exits 0 when every function default passes the smoke assertions, 1
when any default trips.
"""

from __future__ import annotations

import hashlib
import sys

from ract.memory.budget import (
    BudgetAccountant,
    BudgetSection,
    WhitespaceTokenEstimator,
)
from ract.memory.budget_registry import get, load_defaults


# Canonical assembly stubs. Each entry: (section_name, roughly what
# module_09's assembler places, illustrative token cost). The token
# costs are deliberately loose so the smoke gate catches a default
# that is so tight a canonical edit cannot land.
_CANONICAL_ASSEMBLY: dict[str, list[tuple[str, str, int]]] = {
    "intake": [
        ("system_prompt", "intake_system_prompt", 200),
        ("function_contract", "intake_function_contract", 300),
        ("state_context", "brief state summary", 150),
        ("retrieved_bundle", "no retrieval on intake", 0),
        ("invocation_input", "user request text", 400),
    ],
    "research": [
        ("system_prompt", "research_system_prompt", 300),
        ("function_contract", "research_function_contract", 400),
        ("state_context", "prior research notes", 300),
        ("retrieved_bundle", "symbol + graph + semantic bundle", 1500),
        ("invocation_input", "research question", 200),
    ],
    "plan": [
        ("system_prompt", "plan_system_prompt", 300),
        ("function_contract", "plan_function_contract", 500),
        ("state_context", "intake objective + research summary", 600),
        ("retrieved_bundle", "trimmed research bundle", 2000),
        ("invocation_input", "plan instructions", 300),
    ],
    "edit": [
        ("system_prompt", "edit_system_prompt", 400),
        ("function_contract", "edit_function_contract", 600),
        ("state_context", "plan step + prior diff", 800),
        ("retrieved_bundle", "target file plus dependencies", 4000),
        ("invocation_input", "edit instructions", 400),
    ],
}


def _hash_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run_one_function(function: str) -> tuple[bool, str]:
    declaration = get(function)
    accountant = BudgetAccountant(declaration=declaration)
    for name, content, tokens in _CANONICAL_ASSEMBLY[function]:
        accountant.seat(
            BudgetSection(name=name, token_count=tokens, content_hash=_hash_of(content))
        )
    if accountant.over_ceiling():
        return False, (
            f"function {function!r} canonical assembly exceeded ceiling: "
            f"used={accountant.used()} ceiling={declaration.hard_ceiling}"
        )
    if accountant.over_max():
        return False, (
            f"function {function!r} canonical assembly exceeded input_max: "
            f"used={accountant.used()} input_max={declaration.input_max}"
        )
    return True, (
        f"function {function!r} OK: used={accountant.used()} "
        f"target={declaration.input_target} max={declaration.input_max} "
        f"ceiling={declaration.hard_ceiling}"
    )


def _run_estimator_sanity() -> tuple[bool, str]:
    """Guard the default estimator's contract: non-negative, zero on empty."""
    estimator = WhitespaceTokenEstimator()
    if estimator.estimate("") != 0:
        return False, "WhitespaceTokenEstimator: empty string produced non-zero count"
    if estimator.estimate("word") != 1:
        return False, "WhitespaceTokenEstimator: single word produced wrong count"
    return True, "WhitespaceTokenEstimator OK"


def main() -> int:
    defaults = load_defaults()
    print(f"loaded {len(defaults)} function default(s): {sorted(defaults)}")
    all_ok = True
    for function in sorted(defaults):
        ok, message = _run_one_function(function)
        print(("PASS " if ok else "FAIL ") + message)
        all_ok = all_ok and ok
    ok, message = _run_estimator_sanity()
    print(("PASS " if ok else "FAIL ") + message)
    all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
