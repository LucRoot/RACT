"""Budget clamping via capability probe (v0.5.1 wiring module_08, MEM-E-03).

The v0.5.0 probe scheduler wrote ``.rack/probes/capability.json`` but
no caller ever read it. Module_08 adds
:func:`ract.memory.budget_registry.get_with_capability_clamp` which
reads the record and narrows ``input_target`` / ``input_max`` down to
the probed usable window. Budget-consuming call sites can migrate
call-by-call from :func:`get` to :func:`get_with_capability_clamp`.
"""

from __future__ import annotations

import json
from pathlib import Path

from ract.memory.budget_registry import get, get_with_capability_clamp
from ract.memory.probes.scheduler import (
    CAPABILITY_RECORD_PATH,
    CAPABILITY_SCHEMA_VERSION,
)


def _write_capability_record(
    root: Path, *, usable: int, reasoning: int = 4, persistence: int = 4
) -> None:
    target = root / CAPABILITY_RECORD_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "usable_context_window": usable,
        "reasoning_quality_bound": reasoning,
        "persistence_bound": persistence,
        "recorded_at": 1_700_000_000,
    }
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def test_clamp_narrows_input_max_when_probe_shrinks_it(tmp_path: Path) -> None:
    """input_max shrinks to the probed usable window (no floor policy)."""
    base = get("intake")
    # Pick a usable window well below the intake defaults so the clamp
    # actually fires. Stay above the input_target floor so no policy
    # clamp is needed for the target side.
    usable = min(base.input_target, base.input_max) - 1
    _write_capability_record(tmp_path, usable=usable)
    clamped = get_with_capability_clamp("intake", tmp_path)
    assert clamped.input_max <= usable
    assert clamped.function == base.function


def test_clamp_respects_input_target_floor(tmp_path: Path) -> None:
    """A very small probed window clamps input_target to the floor.

    ``composition.apply_runtime_narrowing`` refuses a runtime
    narrowing that pushes ``input_target`` below
    ``base.input_target // 2``. The clamp helper honors that policy
    by clamping to the floor rather than raising.
    """
    base = get("intake")
    floor = base.input_target // 2
    usable = max(1, floor // 4)  # well below the floor
    _write_capability_record(tmp_path, usable=usable)
    clamped = get_with_capability_clamp("intake", tmp_path)
    assert clamped.input_target == floor
    # input_max clamps down alongside input_target so the invariant
    # input_target <= input_max stays satisfied.
    assert clamped.input_max == floor


def test_clamp_is_noop_when_probe_absent(tmp_path: Path) -> None:
    base = get("intake")
    got = get_with_capability_clamp("intake", tmp_path)
    assert got.input_target == base.input_target
    assert got.input_max == base.input_max


def test_clamp_is_noop_when_root_none() -> None:
    base = get("intake")
    got = get_with_capability_clamp("intake", None)
    assert got.input_target == base.input_target


def test_clamp_is_noop_when_probe_wider_than_defaults(tmp_path: Path) -> None:
    base = get("intake")
    _write_capability_record(tmp_path, usable=base.input_max * 2)
    got = get_with_capability_clamp("intake", tmp_path)
    assert got.input_target == base.input_target
    assert got.input_max == base.input_max
