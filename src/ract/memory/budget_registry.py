"""Per-function budget registry — reads budget_defaults.yaml.

Loads a mapping of function name to :class:`~ract.memory.budget.
BudgetDeclaration` from ``src/ract/memory/budget_defaults.yaml``. A
module-level cache stabilises the mapping across the process; the
``_reset_for_tests`` helper allows the test suite to reload the
registry from disk when a fixture rewrites the YAML.

Refuses on:

- unknown YAML schema version (mirrors ADR-0008 for ``ract.yaml``).
- missing / mistyped top-level ``functions`` mapping.
- missing per-function field (validation loop names every expected
  field so a typo like ``input_maxx`` surfaces as a specific error
  rather than silently defaulting).
- unknown function name at :func:`get` time.

Reference: ADR-0008 (`ract.yaml` versioning) and
``docs/ADRs/ADR-0031-budget-accountant-hard-ceiling.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import BudgetDeclaration


DEFAULTS_PATH: Path = Path(__file__).resolve().parent / "budget_defaults.yaml"
"""Location of the shipped defaults YAML."""

SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})
"""Schema versions the reader accepts. Bumped when the payload shape changes."""


class UnknownFunctionError(KeyError):
    """Raised when :func:`get` is asked for a function name not in the registry."""


class BudgetSchemaError(RuntimeError):
    """Raised when the YAML payload is malformed.

    Carries the failing field path and the observed value so a
    misspelled field (``input_maxx`` for ``input.max``) shows up as
    a named error rather than a silent default (Second Pass Q3).
    """


_CACHE: dict[str, BudgetDeclaration] | None = None
_CACHE_PATH: Path | None = None


def _reset_for_tests() -> None:
    """Clear the process-local cache so the next :func:`get` reloads.

    Used by the test suite to reload the registry after rewriting the
    YAML in a temporary fixture.
    """
    global _CACHE, _CACHE_PATH
    _CACHE = None
    _CACHE_PATH = None


_REQUIRED_INPUT_FIELDS: tuple[str, ...] = ("min", "target", "max")
_REQUIRED_OUTPUT_FIELDS: tuple[str, ...] = ("min", "target", "max")


def _require_int(value: Any, *, path: str) -> int:
    """Return ``value`` as an int, or raise :class:`BudgetSchemaError`."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise BudgetSchemaError(
            f"expected int at {path}; got {type(value).__name__}: {value!r}"
        )
    return value


def _require_mapping(value: Any, *, path: str) -> dict[str, Any]:
    """Return ``value`` as a dict, or raise :class:`BudgetSchemaError`."""
    if not isinstance(value, dict):
        raise BudgetSchemaError(
            f"expected mapping at {path}; got {type(value).__name__}"
        )
    return value


def _parse_declaration(function: str, payload: dict[str, Any]) -> BudgetDeclaration:
    """Build a :class:`BudgetDeclaration` from one function's YAML payload.

    Every expected field is named; an unexpected extra field raises so
    a typo cannot silently fall through with a default value.
    """
    allowed_top = {"input", "output", "reasoning_headroom", "hard_ceiling"}
    extra = set(payload) - allowed_top
    if extra:
        raise BudgetSchemaError(
            f"unknown field(s) at functions.{function}: {sorted(extra)!r} "
            f"(allowed: {sorted(allowed_top)!r})"
        )
    input_map = _require_mapping(
        payload.get("input"), path=f"functions.{function}.input"
    )
    output_map = _require_mapping(
        payload.get("output"), path=f"functions.{function}.output"
    )
    extra_input = set(input_map) - set(_REQUIRED_INPUT_FIELDS)
    if extra_input:
        raise BudgetSchemaError(
            f"unknown input field(s) at functions.{function}.input: "
            f"{sorted(extra_input)!r} (allowed: {list(_REQUIRED_INPUT_FIELDS)!r})"
        )
    extra_output = set(output_map) - set(_REQUIRED_OUTPUT_FIELDS)
    if extra_output:
        raise BudgetSchemaError(
            f"unknown output field(s) at functions.{function}.output: "
            f"{sorted(extra_output)!r} (allowed: {list(_REQUIRED_OUTPUT_FIELDS)!r})"
        )
    for name in _REQUIRED_INPUT_FIELDS:
        if name not in input_map:
            raise BudgetSchemaError(
                f"missing required field functions.{function}.input.{name}"
            )
    for name in _REQUIRED_OUTPUT_FIELDS:
        if name not in output_map:
            raise BudgetSchemaError(
                f"missing required field functions.{function}.output.{name}"
            )
    for name in ("reasoning_headroom", "hard_ceiling"):
        if name not in payload:
            raise BudgetSchemaError(
                f"missing required field functions.{function}.{name}"
            )
    try:
        return BudgetDeclaration(
            function=function,
            input_min=_require_int(
                input_map["min"], path=f"functions.{function}.input.min"
            ),
            input_target=_require_int(
                input_map["target"], path=f"functions.{function}.input.target"
            ),
            input_max=_require_int(
                input_map["max"], path=f"functions.{function}.input.max"
            ),
            output_min=_require_int(
                output_map["min"], path=f"functions.{function}.output.min"
            ),
            output_target=_require_int(
                output_map["target"], path=f"functions.{function}.output.target"
            ),
            output_max=_require_int(
                output_map["max"], path=f"functions.{function}.output.max"
            ),
            reasoning_headroom=_require_int(
                payload["reasoning_headroom"],
                path=f"functions.{function}.reasoning_headroom",
            ),
            hard_ceiling=_require_int(
                payload["hard_ceiling"], path=f"functions.{function}.hard_ceiling"
            ),
        )
    except (TypeError, ValueError) as exc:
        raise BudgetSchemaError(
            f"invalid BudgetDeclaration for function {function!r}: {exc}"
        ) from exc


def load_defaults(path: Path | None = None) -> dict[str, BudgetDeclaration]:
    """Read ``path`` (default :data:`DEFAULTS_PATH`) and return the mapping.

    Returns a fresh dict on every call; the module-level cache used by
    :func:`get` is separate. Malformed YAML raises
    :class:`BudgetSchemaError` naming the failing field.
    """
    read_from = path if path is not None else DEFAULTS_PATH
    if not read_from.is_file():
        raise BudgetSchemaError(f"budget defaults file not found: {read_from}")
    try:
        raw = yaml.safe_load(read_from.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BudgetSchemaError(f"budget defaults YAML parse error: {exc}") from exc
    if not isinstance(raw, dict):
        raise BudgetSchemaError(
            f"budget defaults top-level must be a mapping; got {type(raw).__name__}"
        )
    schema_version = raw.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise BudgetSchemaError("budget defaults missing integer schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise BudgetSchemaError(
            f"unsupported schema_version {schema_version!r}; "
            f"reader supports {sorted(SUPPORTED_SCHEMA_VERSIONS)!r}"
        )
    functions = raw.get("functions")
    if not isinstance(functions, dict) or not functions:
        raise BudgetSchemaError(
            "budget defaults must have a non-empty 'functions' mapping"
        )
    parsed: dict[str, BudgetDeclaration] = {}
    for function, payload in functions.items():
        if not isinstance(function, str) or not function:
            raise BudgetSchemaError(
                f"function key must be a non-empty string; got {function!r}"
            )
        parsed[function] = _parse_declaration(
            function, _require_mapping(payload, path=f"functions.{function}")
        )
    return parsed


def _ensure_cache(path: Path | None = None) -> dict[str, BudgetDeclaration]:
    """Populate the module-level cache if empty; return the cached mapping."""
    global _CACHE, _CACHE_PATH
    if _CACHE is None or (path is not None and _CACHE_PATH != path):
        _CACHE = load_defaults(path)
        _CACHE_PATH = path if path is not None else DEFAULTS_PATH
    return _CACHE


def get(function: str, *, path: Path | None = None) -> BudgetDeclaration:
    """Return the :class:`BudgetDeclaration` for ``function``.

    Reads from the module-level cache (populated on first call).
    Raises :class:`UnknownFunctionError` when ``function`` is not in
    the registry — the caller MUST NOT fall back to a default. A
    typo like ``intak`` should fail loudly, not silently synthesize
    an intake budget.
    """
    cache = _ensure_cache(path)
    if function not in cache:
        raise UnknownFunctionError(
            f"unknown function {function!r}; registry has {sorted(cache)!r}"
        )
    return cast(BudgetDeclaration, cache[function])


__all__ = [
    "BudgetSchemaError",
    "DEFAULTS_PATH",
    "SUPPORTED_SCHEMA_VERSIONS",
    "UnknownFunctionError",
    "get",
    "load_defaults",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
