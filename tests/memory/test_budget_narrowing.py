"""Narrow-only invariant: composition and runtime paths refuse widening.

Master spec §Budget sources:

    Runtime adjustment always narrows, never widens. Widening is a
    design change and requires a fresh function-default commit.

The invariant applies at both boundaries: composition (playbook
override YAML) and runtime (self-adjustment layer). Lateral Chain
branch B adds a runtime floor: a narrowing that would push
``input_target`` below half its base value is refused.
"""

from __future__ import annotations

import pytest

from ract.memory.budget import (
    BudgetDeclaration,
    BudgetNarrowing,
    WideningRefusedError,
    narrow,
)
from ract.memory.composition import (
    CompositionSchemaError,
    RuntimeNarrowingFloorError,
    apply_composition_override,
    apply_runtime_narrowing,
)


def _declaration() -> BudgetDeclaration:
    return BudgetDeclaration(
        function="edit",
        input_min=100,
        input_target=1000,
        input_max=2000,
        output_min=100,
        output_target=500,
        output_max=500,
        reasoning_headroom=500,
        hard_ceiling=3000,
    )


# ---------------------------------------------------------------------------
# Composition override
# ---------------------------------------------------------------------------


def test_composition_override_narrows_flat_shape() -> None:
    base = _declaration()
    narrowed = apply_composition_override(base, {"input_max": 1500})
    assert narrowed.input_max == 1500
    # Other fields unchanged.
    assert narrowed.input_target == base.input_target
    assert narrowed.hard_ceiling == base.hard_ceiling


def test_composition_override_narrows_nested_shape() -> None:
    base = _declaration()
    narrowed = apply_composition_override(base, {"input": {"max": 1500, "target": 800}})
    assert narrowed.input_max == 1500
    assert narrowed.input_target == 800


def test_composition_override_refuses_widening_at_flat_level() -> None:
    base = _declaration()
    with pytest.raises(WideningRefusedError) as exc_info:
        apply_composition_override(base, {"input_max": 5000})
    assert exc_info.value.field_name == "input_max"
    assert exc_info.value.new == 5000
    assert exc_info.value.old == 2000


def test_composition_override_refuses_widening_at_nested_level() -> None:
    base = _declaration()
    with pytest.raises(WideningRefusedError) as exc_info:
        apply_composition_override(base, {"output": {"max": 9999}})
    assert exc_info.value.field_name == "output_max"


def test_composition_override_refuses_unknown_field_typo() -> None:
    """Second Pass Q3: an override that misspells ``input_max`` as
    ``input_maxx`` must NOT silently fall through with the default."""
    base = _declaration()
    with pytest.raises(CompositionSchemaError, match="input_maxx"):
        apply_composition_override(base, {"input_maxx": 1500})


def test_composition_override_refuses_unknown_nested_field() -> None:
    base = _declaration()
    with pytest.raises(CompositionSchemaError, match="unknown composition override"):
        apply_composition_override(base, {"output": {"maxx": 100}})


def test_composition_override_refuses_bool_where_int_expected() -> None:
    base = _declaration()
    with pytest.raises(CompositionSchemaError, match="must be int"):
        apply_composition_override(base, {"input_max": True})


def test_composition_override_refuses_non_mapping_input() -> None:
    base = _declaration()
    with pytest.raises(CompositionSchemaError, match="must be a mapping"):
        apply_composition_override(base, "not a dict")  # type: ignore[arg-type]


def test_composition_override_empty_dict_returns_base_unchanged() -> None:
    base = _declaration()
    result = apply_composition_override(base, {})
    assert result == base


def test_composition_override_refuses_double_key_flat_and_nested() -> None:
    base = _declaration()
    with pytest.raises(CompositionSchemaError, match="sets 'input_max' twice"):
        apply_composition_override(base, {"input_max": 1500, "input": {"max": 1500}})


# ---------------------------------------------------------------------------
# Runtime narrowing
# ---------------------------------------------------------------------------


def _runtime(field_name: str, old: int, new: int) -> BudgetNarrowing:
    return BudgetNarrowing(
        function="edit", field_name=field_name, old=old, new=new, source="runtime"
    )


def test_runtime_narrowing_narrows_without_widening() -> None:
    base = _declaration()
    narrowed = apply_runtime_narrowing(base, [_runtime("input_target", 1000, 800)])
    assert narrowed.input_target == 800


def test_runtime_narrowing_refuses_widening_at_construct_time() -> None:
    """The narrowing dataclass refuses widening in ``__post_init__``.

    Second Pass Q2: is the narrow-only invariant enforced at construct
    time, or is it a runtime check the caller could bypass? Answer:
    both. Construct time (this test) AND the composition/runtime
    helper's own check.
    """
    with pytest.raises(WideningRefusedError) as exc_info:
        BudgetNarrowing(
            function="edit",
            field_name="input_target",
            old=1000,
            new=1500,
            source="runtime",
        )
    assert exc_info.value.field_name == "input_target"


def test_runtime_narrowing_refuses_below_input_target_floor() -> None:
    """Lateral Chain branch B: runaway narrowing is bounded.

    Floor is ``input_target // 2`` computed against the BASE, so
    repeated narrowings cannot chain past the floor.
    """
    base = _declaration()
    # Base input_target = 1000; floor = 500. New = 400 is below.
    with pytest.raises(RuntimeNarrowingFloorError) as exc_info:
        apply_runtime_narrowing(base, [_runtime("input_target", 1000, 400)])
    assert "500" in str(exc_info.value)


def test_runtime_narrowing_at_floor_is_allowed() -> None:
    base = _declaration()
    # Exactly at floor (500) is allowed.
    narrowed = apply_runtime_narrowing(base, [_runtime("input_target", 1000, 500)])
    assert narrowed.input_target == 500


def test_runtime_narrowing_refuses_composition_source_entries() -> None:
    """Caller-side sanity: entries destined for the runtime helper must
    carry ``source == 'runtime'``. A composition-source entry is a
    caller bug, not a schema error."""
    base = _declaration()
    composition_narrowing = BudgetNarrowing(
        function="edit",
        field_name="input_target",
        old=1000,
        new=800,
        source="composition",
    )
    with pytest.raises(ValueError, match="source must be 'runtime'"):
        apply_runtime_narrowing(base, [composition_narrowing])


# ---------------------------------------------------------------------------
# ``narrow`` combinator invariants
# ---------------------------------------------------------------------------


def test_narrow_refuses_narrowing_for_wrong_function() -> None:
    base = _declaration()
    other = BudgetNarrowing(
        function="research",
        field_name="input_target",
        old=1000,
        new=800,
        source="runtime",
    )
    with pytest.raises(ValueError, match="does not match declaration.function"):
        narrow(base, [other])


def test_narrow_refuses_narrowing_for_unknown_field() -> None:
    """The ``narrow`` combinator refuses a narrowing whose ``field_name``
    is not one of the nine narrowable fields on the declaration.

    Construct time does NOT refuse arbitrary field names on
    :class:`BudgetNarrowing` because the type would then need to embed
    the narrowable-field list, coupling the value type to the
    declaration surface. Instead, ``narrow`` is the belt-and-suspenders
    check: build a narrowing that construction accepts but names a
    field the declaration does not carry, then let ``narrow`` refuse."""
    base = _declaration()
    entry = BudgetNarrowing(
        function="edit",
        field_name="input_target",
        old=1000,
        new=800,
        source="runtime",
    )
    # Bypass frozen dataclass to simulate a stale caller / a bad
    # composition helper that emitted a narrowing for a field the
    # declaration does not carry.
    object.__setattr__(entry, "field_name", "unknown_field")
    with pytest.raises(ValueError, match="is not narrowable"):
        narrow(base, [entry])


def test_narrow_refuses_stale_old_value() -> None:
    base = _declaration()
    with pytest.raises(ValueError, match="disagrees with the current value"):
        narrow(
            base,
            [
                BudgetNarrowing(
                    function="edit",
                    field_name="input_target",
                    old=999,  # actual is 1000
                    new=800,
                    source="runtime",
                )
            ],
        )


def test_narrow_composition_of_narrowings_cannot_widen_versus_base() -> None:
    """Second Pass Q2 construct-time question: ``narrow(narrow(base,
    N1), N2)`` cannot produce a declaration wider than ``base`` for
    the fields both narrowings touch.

    N1 tightens input_target from 1000 to 800; N2 attempts to raise
    input_target back to 900. The intermediate has input_target=800,
    so N2's ``old`` must be 800 (not 900), and N2's ``new`` cannot
    exceed the intermediate's 800.
    """
    base = _declaration()
    step1 = narrow(
        base,
        [
            BudgetNarrowing(
                function="edit",
                field_name="input_target",
                old=1000,
                new=800,
                source="runtime",
            )
        ],
    )
    with pytest.raises(WideningRefusedError):
        BudgetNarrowing(
            function="edit",
            field_name="input_target",
            old=800,
            new=900,
            source="runtime",
        )
    # And even the plumbing refuses if a caller synthesises a bad
    # ``old`` to bypass construct-time.
    forged = BudgetNarrowing(
        function="edit",
        field_name="input_target",
        old=800,
        new=800,
        source="runtime",
    )
    object.__setattr__(forged, "new", 900)
    with pytest.raises(WideningRefusedError):
        narrow(step1, [forged])


def test_narrow_empty_list_returns_declaration_unchanged() -> None:
    base = _declaration()
    assert narrow(base, []) is base
