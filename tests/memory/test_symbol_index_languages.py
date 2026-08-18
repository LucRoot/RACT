"""Per-language parse tests against the tiny_repo fixture.

Each test loads one fixture file, calls the language module's
``parse`` function, and asserts the emitted symbol set matches the
spec's AST chunking rules for that language.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.memory.languages import GrammarVersionMismatchError
from ract.memory.parser import parse_file


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "tiny_repo"


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def test_python_class_method_and_function() -> None:
    path = FIXTURE_ROOT / "py_pkg" / "greeter.py"
    rows = parse_file(path)
    kinds = [(r.kind, r.name) for r in rows]
    assert ("type", "Name") in kinds
    assert ("class", "Greeter") in kinds
    assert ("method", "greet") in kinds
    assert ("function", "make_greeter") in kinds


def test_python_module_level_constant_and_type_alias() -> None:
    path = FIXTURE_ROOT / "py_pkg" / "math_utils.py"
    rows = parse_file(path)
    named = {(r.kind, r.name) for r in rows}
    # ALL_CAPS module-level assignment ships as ``constant`` (not type).
    assert ("constant", "MAX_VALUE") in named
    assert ("function", "add") in named
    assert ("function", "multiply") in named


def test_python_class_hierarchy() -> None:
    path = FIXTURE_ROOT / "py_pkg" / "errors.py"
    rows = parse_file(path)
    assert [r.name for r in rows] == ["TinyError", "TinyValueError"]
    assert all(r.kind == "class" for r in rows)


def test_python_visibility_uses_leading_underscore() -> None:
    from ract.memory.languages.python import parse

    src = b"def public_fn():\n    pass\n\ndef _private_fn():\n    pass\n"
    rows = parse(src, Path("mod.py"))
    kinds = {r.name: r.visibility for r in rows}
    assert kinds == {"public_fn": "public", "_private_fn": "private"}


def test_python_nested_function_does_not_surface() -> None:
    from ract.memory.languages.python import parse

    src = b"def outer():\n    def inner():\n        pass\n    return inner\n"
    rows = parse(src, Path("mod.py"))
    assert [r.name for r in rows] == ["outer"]


def test_python_decorated_class_emits_class_kind() -> None:
    from ract.memory.languages.python import parse

    src = b"import dataclasses\n\n@dataclasses.dataclass\nclass Point:\n    x: int\n    y: int\n\n    def norm(self) -> int:\n        return self.x + self.y\n"
    rows = parse(src, Path("mod.py"))
    kinds = [(r.kind, r.name) for r in rows]
    assert ("class", "Point") in kinds
    assert ("method", "norm") in kinds


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------


def test_typescript_class_and_arrow_function() -> None:
    path = FIXTURE_ROOT / "ts_pkg" / "greeter.ts"
    rows = parse_file(path)
    kinds = [(r.kind, r.name) for r in rows]
    assert ("class", "Greeter") in kinds
    assert ("method", "greet") in kinds
    assert ("function", "makeGreeter") in kinds
    # Arrow function assigned to a const at module scope surfaces.
    assert ("function", "shout") in kinds


def test_typescript_interface_and_type_alias() -> None:
    path = FIXTURE_ROOT / "ts_pkg" / "shapes.ts"
    rows = parse_file(path)
    kinds = {(r.kind, r.name) for r in rows}
    assert ("interface", "Named") in kinds
    assert ("type", "Id") in kinds
    assert ("class", "Point") in kinds
    # Constructor + method both surface as ``method``.
    assert ("method", "distance") in kinds


def test_typescript_nested_arrow_does_not_surface() -> None:
    # Second Pass Q2: an arrow function INSIDE a class method must NOT
    # surface as a top-level symbol.
    from ract.memory.languages.typescript import parse

    src = b"export class Widget {\n  render(): void {\n    const inner = () => 1;\n    return inner();\n  }\n}\n"
    rows = parse(src, Path("widget.ts"))
    assert [(r.kind, r.name) for r in rows] == [
        ("class", "Widget"),
        ("method", "render"),
    ]


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------


def test_rust_struct_impl_and_methods() -> None:
    path = FIXTURE_ROOT / "rs_pkg" / "lib.rs"
    rows = parse_file(path)
    kinds = [(r.kind, r.name) for r in rows]
    assert ("struct", "Greeter") in kinds
    # impl block ships as its own row.
    assert any(k == "impl" for k, _ in kinds)
    assert ("method", "new") in kinds
    assert ("method", "greet") in kinds


def test_rust_enum_and_trait() -> None:
    path = FIXTURE_ROOT / "rs_pkg" / "shapes.rs"
    rows = parse_file(path)
    kinds = {(r.kind, r.name) for r in rows}
    assert ("struct", "Point") in kinds
    assert ("enum", "Direction") in kinds
    assert ("trait", "Greet") in kinds


def test_rust_doc_comments_attach() -> None:
    path = FIXTURE_ROOT / "rs_pkg" / "lib.rs"
    rows = parse_file(path)
    greeter = next(r for r in rows if r.name == "Greeter" and r.kind == "struct")
    assert greeter.docstring is not None
    assert "polite greeter" in greeter.docstring


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------


def test_go_struct_and_method() -> None:
    path = FIXTURE_ROOT / "go_pkg" / "greeter.go"
    rows = parse_file(path)
    kinds = [(r.kind, r.name) for r in rows]
    assert ("struct", "Greeter") in kinds
    assert ("method", "Greet") in kinds


def test_go_interface_and_struct() -> None:
    path = FIXTURE_ROOT / "go_pkg" / "shapes.go"
    rows = parse_file(path)
    kinds = {(r.kind, r.name) for r in rows}
    assert ("struct", "Point") in kinds
    assert ("interface", "Shape") in kinds


def test_go_functions() -> None:
    path = FIXTURE_ROOT / "go_pkg" / "math.go"
    rows = parse_file(path)
    assert [(r.kind, r.name) for r in rows] == [
        ("function", "Add"),
        ("function", "Multiply"),
    ]


def test_go_visibility_from_leading_case() -> None:
    from ract.memory.languages.go import parse

    src = b"package p\n\nfunc Public() {}\n\nfunc private() {}\n"
    rows = parse(src, Path("m.go"))
    kinds = {r.name: r.visibility for r in rows}
    assert kinds == {"Public": "public", "private": "private"}


# ---------------------------------------------------------------------------
# Cross-language sanity
# ---------------------------------------------------------------------------


def test_grammar_version_mismatch_error_is_runtime() -> None:
    # Instantiate the error type directly to prove the API.
    err = GrammarVersionMismatchError(
        language="python", expected="0.25.0", observed="0.20.0"
    )
    assert isinstance(err, RuntimeError)
    assert "python" in str(err)


def test_parser_dispatcher_refuses_unknown_extension(tmp_path: Path) -> None:
    from ract.memory.parser import UnsupportedLanguageError

    weird = tmp_path / "code.xyz"
    weird.write_text("stuff", encoding="utf-8")
    with pytest.raises(UnsupportedLanguageError):
        parse_file(weird)


def test_content_hash_and_token_count_populated_on_every_row() -> None:
    for suffix in (".py", ".ts", ".rs", ".go"):
        candidates = list(FIXTURE_ROOT.rglob(f"*{suffix}"))
        assert candidates, f"tiny_repo has no {suffix} fixtures"
        for path in candidates:
            for row in parse_file(path):
                assert row.content_hash is not None
                assert row.token_count is not None
                assert row.token_count >= 0
                assert row.language is not None
