"""Composition override + runtime narrowing over budget declarations.

Two entry points:

- :func:`apply_composition_override` — playbook YAML dict narrows the
  function default. Reads only known fields; a typo like ``input_maxx``
  raises :class:`~ract.memory.budget.WideningRefusedError` -adjacent
  :class:`CompositionSchemaError` rather than silently defaulting
  (Second Pass Q3).

- :func:`apply_runtime_narrowing` — self-adjustment layer (module_08)
  emits a list of :class:`BudgetNarrowing` records; this helper
  applies them against the current declaration. Lateral Chain branch B
  bounds runtime narrowings by a floor: a runtime narrowing that
  would push ``input_target`` below half its current value is refused
  (:class:`RuntimeNarrowingFloorError`).

Both helpers refuse widening; refusal raises
:class:`~ract.memory.budget.WideningRefusedError` at the narrowing
construct site.
"""

from __future__ import annotations

from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import (
    BudgetDeclaration,
    BudgetNarrowing,
    WideningRefusedError,
    narrow,
)


class CompositionSchemaError(RuntimeError):
    """Raised when the playbook override dict has a mistyped or unknown field."""


class RuntimeNarrowingFloorError(RuntimeError):
    """Raised when a runtime narrowing would push a field below its floor.

    Lateral Chain branch B: a runtime narrowing that reduces
    ``input_target`` below half of the current value is refused.
    Without the floor, a self-adjustment layer that trims by 10 percent
    every invocation collapses the budget to zero over enough runs.
    """


# Playbook overrides address the same nine narrowable fields, plus
# nested access to input/output sub-blocks for readability. Both
# ``input_max: N`` and ``input: {max: N}`` are accepted.
_FIELD_ALIASES: dict[str, str] = {
    "input_min": "input_min",
    "input_target": "input_target",
    "input_max": "input_max",
    "output_min": "output_min",
    "output_target": "output_target",
    "output_max": "output_max",
    "reasoning_headroom": "reasoning_headroom",
    "hard_ceiling": "hard_ceiling",
}

_SUB_BLOCK_FIELDS: dict[str, tuple[str, ...]] = {
    "input": ("min", "target", "max"),
    "output": ("min", "target", "max"),
}


def _flatten_override(override: dict[str, Any]) -> dict[str, int]:
    """Return a flat ``{field_name: new_value}`` map from a playbook override.

    Accepts either flat (``input_max: 3000``) or nested
    (``input: {max: 3000}``) shapes. An unknown key raises
    :class:`CompositionSchemaError` naming the offender.
    """
    flat: dict[str, int] = {}
    allowed_top = set(_FIELD_ALIASES) | set(_SUB_BLOCK_FIELDS)
    for key, value in override.items():
        if key not in allowed_top:
            raise CompositionSchemaError(
                f"unknown composition override field {key!r}; "
                f"allowed: {sorted(allowed_top)!r}"
            )
        if key in _SUB_BLOCK_FIELDS:
            if not isinstance(value, dict):
                raise CompositionSchemaError(
                    f"composition override {key!r} must be a mapping; "
                    f"got {type(value).__name__}"
                )
            allowed_sub = set(_SUB_BLOCK_FIELDS[key])
            for sub_key, sub_value in value.items():
                if sub_key not in allowed_sub:
                    raise CompositionSchemaError(
                        f"unknown composition override field {key}.{sub_key!r}; "
                        f"allowed: {sorted(allowed_sub)!r}"
                    )
                flat_key = f"{key}_{sub_key}"
                if flat_key in flat:
                    raise CompositionSchemaError(
                        f"composition override sets {flat_key!r} twice"
                    )
                flat[flat_key] = _require_int(sub_value, path=f"{key}.{sub_key}")
            continue
        if key in flat:
            raise CompositionSchemaError(f"composition override sets {key!r} twice")
        flat[key] = _require_int(value, path=key)
    return flat


def _require_int(value: Any, *, path: str) -> int:
    """Return ``value`` as an int, or raise :class:`CompositionSchemaError`."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise CompositionSchemaError(
            f"composition override {path} must be int; "
            f"got {type(value).__name__}: {value!r}"
        )
    return value


def apply_composition_override(
    base: BudgetDeclaration,
    playbook_override: dict[str, Any],
) -> BudgetDeclaration:
    """Return a new declaration with ``playbook_override`` narrowings applied.

    The override is a dict read from the playbook YAML for the current
    use case (module_07 lands the playbook loader). Every override
    field must narrow; a widening attempt raises
    :class:`~ract.memory.budget.WideningRefusedError`. An unknown key
    raises :class:`CompositionSchemaError` naming the offender so a
    typo (``input_maxx``) does not silently fall through with the
    default value.
    """
    if not isinstance(playbook_override, dict):
        raise CompositionSchemaError(
            f"playbook override must be a mapping; "
            f"got {type(playbook_override).__name__}"
        )
    flat = _flatten_override(playbook_override)
    if not flat:
        return base
    narrowings: list[BudgetNarrowing] = []
    for field_name, new_value in flat.items():
        old_value = getattr(base, field_name)
        if new_value > old_value:
            raise WideningRefusedError(
                field_name=field_name, old=old_value, new=new_value
            )
        narrowings.append(
            BudgetNarrowing(
                function=base.function,
                field_name=field_name,
                old=old_value,
                new=new_value,
                source="composition",
            )
        )
    return narrow(base, narrowings)


def apply_runtime_narrowing(
    base: BudgetDeclaration,
    narrowings: list[BudgetNarrowing],
) -> BudgetDeclaration:
    """Return a new declaration with ``narrowings`` applied at runtime.

    Every entry must have ``source == "runtime"``; a mismatched source
    is a caller bug. Lateral Chain branch B: a narrowing that would
    push ``input_target`` below half of ``base.input_target`` is
    refused with :class:`RuntimeNarrowingFloorError`. The floor is
    computed against ``base`` (not the running intermediate) so
    repeated narrowings cannot chain past the floor.
    """
    floor = base.input_target // 2
    for entry in narrowings:
        if entry.source != "runtime":
            raise ValueError(
                f"apply_runtime_narrowing: entry source must be 'runtime'; "
                f"got {entry.source!r}"
            )
        if entry.field_name == "input_target" and entry.new < floor:
            raise RuntimeNarrowingFloorError(
                f"runtime narrowing on input_target={entry.new} is below the "
                f"floor {floor} (half of base.input_target={base.input_target})"
            )
    return narrow(base, narrowings)


__all__ = [
    "CompositionSchemaError",
    "RuntimeNarrowingFloorError",
    "apply_composition_override",
    "apply_runtime_narrowing",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
