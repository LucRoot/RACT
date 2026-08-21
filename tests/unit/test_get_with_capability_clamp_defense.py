"""Defense-in-depth for get_with_capability_clamp (SP Q6.4 amendment).

If :func:`ract.memory.composition.apply_runtime_narrowing` ever
refuses a narrowing the clamp helper computed (e.g. a future refactor
tightens the floor policy), the helper must log + emit +
return the base declaration rather than raise. The primary path
already respects the current floor so this test exercises the
defense-in-depth branch by monkeypatching a narrowing-refusal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.memory.budget import BudgetDeclaration
from ract.memory.budget_registry import get, get_with_capability_clamp
from ract.memory.probes.scheduler import (
    CAPABILITY_RECORD_PATH,
    CAPABILITY_SCHEMA_VERSION,
)


def _write_capability(root: Path, usable: int) -> None:
    target = root / CAPABILITY_RECORD_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "schema_version": CAPABILITY_SCHEMA_VERSION,
                "usable_context_window": usable,
                "reasoning_quality_bound": 4,
                "persistence_bound": 4,
                "recorded_at": 1_700_000_000,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_clamp_returns_base_when_apply_runtime_narrowing_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract.memory import composition

    base = get("intake")
    _write_capability(tmp_path, base.input_max // 2)

    def _always_refuses(base_decl: BudgetDeclaration, narrowings) -> BudgetDeclaration:
        raise composition.RuntimeNarrowingFloorError(
            "simulated floor policy tightening"
        )

    monkeypatch.setattr(composition, "apply_runtime_narrowing", _always_refuses)
    # Re-import from budget_registry's inline import path: the
    # inline import reads the fresh symbol on each call so the
    # monkeypatch on the module module attribute takes effect.
    got = get_with_capability_clamp("intake", tmp_path)
    assert got == base, (
        "clamp must fall back to un-clamped base when the composition "
        "layer refuses the narrowings we computed"
    )
