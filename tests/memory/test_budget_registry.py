"""Registry loader tests for src/ract/memory/budget_defaults.yaml.

Covers:

- The shipped defaults YAML loads to four function keys (intake,
  research, plan, edit).
- Each key produces a valid :class:`BudgetDeclaration`.
- Unknown function lookup raises :class:`UnknownFunctionError`.
- Missing / mistyped fields surface as :class:`BudgetSchemaError`
  naming the offender rather than silently defaulting.
- Unsupported schema version is refused.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from ract.memory.budget import BudgetDeclaration
from ract.memory.budget_registry import (
    DEFAULTS_PATH,
    BudgetSchemaError,
    UnknownFunctionError,
    _reset_for_tests,
    get,
    load_defaults,
)


_EXPECTED_FUNCTIONS: tuple[str, ...] = ("intake", "research", "plan", "edit")


@pytest.fixture(autouse=True)
def _isolate_registry_cache() -> object:
    """Reset the module-level cache before and after every test."""
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_shipped_defaults_yaml_lives_next_to_module() -> None:
    assert DEFAULTS_PATH.is_file()
    assert DEFAULTS_PATH.name == "budget_defaults.yaml"


def test_shipped_defaults_load_four_functions() -> None:
    defaults = load_defaults()
    assert set(defaults) == set(_EXPECTED_FUNCTIONS)
    for function in _EXPECTED_FUNCTIONS:
        decl = defaults[function]
        assert isinstance(decl, BudgetDeclaration)
        assert decl.function == function


def test_shipped_defaults_ordering_matches_spec() -> None:
    """§Function contracts orders the four by edit-width dominance:
    intake is smallest and edit is largest. Plan and research sit in
    the middle; plan carries more input_target than research (it must
    combine intake + research summaries), while research carries a
    larger output_target than plan (research produces bundle text
    where plan produces a step list). Both dominances are locked so a
    rebase does not silently reshuffle sizing."""
    defaults = load_defaults()
    assert defaults["intake"].input_target < defaults["research"].input_target
    assert defaults["intake"].input_target < defaults["plan"].input_target
    assert defaults["research"].input_target < defaults["edit"].input_target
    assert defaults["plan"].input_target < defaults["edit"].input_target
    # Research produces bundle text; plan produces a step list.
    assert defaults["research"].output_target > defaults["plan"].output_target


def test_shipped_defaults_pass_declaration_invariant() -> None:
    """Every shipped default satisfies the strict-inequality invariant
    ``hard_ceiling >= input_max + output_max + reasoning_headroom``.

    This regression test would catch a rebase that widens a field
    without also raising the ceiling."""
    defaults = load_defaults()
    for function, decl in defaults.items():
        required = decl.input_max + decl.output_max + decl.reasoning_headroom
        assert decl.hard_ceiling >= required, (
            f"function {function!r} declaration violates ceiling invariant: "
            f"{decl.hard_ceiling} < {required}"
        )


def test_get_reads_from_cache_after_first_call() -> None:
    first = get("intake")
    second = get("intake")
    assert first is second


def test_get_refuses_unknown_function() -> None:
    with pytest.raises(UnknownFunctionError, match="intak"):
        get("intak")


def test_load_defaults_refuses_missing_file(tmp_path: Path) -> None:
    with pytest.raises(BudgetSchemaError, match="not found"):
        load_defaults(tmp_path / "missing.yaml")


def test_load_defaults_refuses_non_mapping_top_level(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(BudgetSchemaError, match="top-level must be a mapping"):
        load_defaults(path)


def test_load_defaults_refuses_missing_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("functions: {}\n", encoding="utf-8")
    with pytest.raises(BudgetSchemaError, match="schema_version"):
        load_defaults(path)


def test_load_defaults_refuses_unsupported_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("schema_version: 999\nfunctions: {intake: {}}\n", encoding="utf-8")
    with pytest.raises(BudgetSchemaError, match="unsupported schema_version"):
        load_defaults(path)


def test_load_defaults_refuses_empty_functions(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("schema_version: 1\nfunctions: {}\n", encoding="utf-8")
    with pytest.raises(BudgetSchemaError, match="non-empty 'functions'"):
        load_defaults(path)


def test_load_defaults_refuses_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        dedent(
            """\
            schema_version: 1
            functions:
              intake:
                input: {min: 0, target: 100, max: 200}
                output: {min: 0, target: 100, max: 100}
                reasoning_headroom: 100
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(BudgetSchemaError, match="hard_ceiling"):
        load_defaults(path)


def test_load_defaults_refuses_unknown_field(tmp_path: Path) -> None:
    """Missing hard_ceiling caught above; here we test that an unknown
    top-level key (typo) is refused instead of silently ignored."""
    path = tmp_path / "bad.yaml"
    path.write_text(
        dedent(
            """\
            schema_version: 1
            functions:
              intake:
                input: {min: 0, target: 100, max: 200}
                output: {min: 0, target: 100, max: 100}
                reasoning_headroom: 100
                hard_ceiling: 500
                extra_field: 42
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(BudgetSchemaError, match="unknown field"):
        load_defaults(path)


def test_load_defaults_refuses_unknown_input_field(tmp_path: Path) -> None:
    """Second Pass Q3: a typo in input sub-block (``maxx`` for ``max``)
    surfaces as a named error, not a silent default."""
    path = tmp_path / "bad.yaml"
    path.write_text(
        dedent(
            """\
            schema_version: 1
            functions:
              intake:
                input: {min: 0, target: 100, maxx: 200}
                output: {min: 0, target: 100, max: 100}
                reasoning_headroom: 100
                hard_ceiling: 500
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(BudgetSchemaError, match="unknown input field"):
        load_defaults(path)


def test_load_defaults_refuses_non_int_value(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        dedent(
            """\
            schema_version: 1
            functions:
              intake:
                input: {min: 0, target: 100, max: "big"}
                output: {min: 0, target: 100, max: 100}
                reasoning_headroom: 100
                hard_ceiling: 500
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(BudgetSchemaError, match="expected int"):
        load_defaults(path)


def test_load_defaults_refuses_declaration_invariant_violation(
    tmp_path: Path,
) -> None:
    """A hand-written YAML that violates the ceiling invariant surfaces
    the underlying error wrapped in :class:`BudgetSchemaError`."""
    path = tmp_path / "bad.yaml"
    path.write_text(
        dedent(
            """\
            schema_version: 1
            functions:
              intake:
                input: {min: 0, target: 100, max: 200}
                output: {min: 0, target: 100, max: 100}
                reasoning_headroom: 100
                hard_ceiling: 100
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        BudgetSchemaError, match="invalid BudgetDeclaration for function 'intake'"
    ):
        load_defaults(path)
