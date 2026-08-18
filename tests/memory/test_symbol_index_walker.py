"""Walker + initial_build tests against the tiny_repo fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.memory.symbol_index import SymbolIndex
from ract.memory.walker import (
    DEFAULT_EXTENSIONS,
    initial_build,
    walk,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "tiny_repo"


# The tiny_repo fixture has a fixed count for module_02; a change to
# the fixture bumps this expectation on purpose so accidental fixture
# drift becomes a red test.
EXPECTED_FILE_COUNT = 13  # 4 py (incl __init__.py) + 3 ts + 3 rs + 3 go
EXPECTED_MIN_SYMBOLS = 30


def test_walk_yields_only_supported_extensions() -> None:
    paths = list(walk(FIXTURE_ROOT))
    for path in paths:
        assert path.suffix in DEFAULT_EXTENSIONS
    # Deterministic sorted order.
    assert paths == sorted(paths)


def test_walk_finds_every_fixture_file() -> None:
    paths = list(walk(FIXTURE_ROOT))
    assert len(paths) == EXPECTED_FILE_COUNT


def test_walk_refuses_missing_root(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        list(walk(tmp_path / "does_not_exist"))


def test_walk_respects_gitignore(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("def x(): pass\n", encoding="utf-8")
    (tmp_path / "drop.py").write_text("def y(): pass\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("drop.py\n", encoding="utf-8")
    paths = list(walk(tmp_path))
    names = [p.name for p in paths]
    assert "keep.py" in names
    assert "drop.py" not in names


def test_walk_respects_ractignore(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("def x(): pass\n", encoding="utf-8")
    (tmp_path / "generated.py").write_text("def y(): pass\n", encoding="utf-8")
    (tmp_path / ".ractignore").write_text("generated.py\n", encoding="utf-8")
    paths = [p.name for p in walk(tmp_path)]
    assert "keep.py" in paths
    assert "generated.py" not in paths


def test_walk_skips_pycache_and_venv(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("def x(): pass\n", encoding="utf-8")
    cached = tmp_path / "__pycache__"
    cached.mkdir()
    (cached / "hidden.py").write_text("def z(): pass\n", encoding="utf-8")
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "vendored.py").write_text("def q(): pass\n", encoding="utf-8")
    names = {p.name for p in walk(tmp_path)}
    assert names == {"keep.py"}


# ---------------------------------------------------------------------------
# initial_build
# ---------------------------------------------------------------------------


def test_initial_build_under_time_budget() -> None:
    with SymbolIndex() as idx:
        report = initial_build(FIXTURE_ROOT, idx)
        assert report.files_parsed == EXPECTED_FILE_COUNT
        assert report.symbols_indexed >= EXPECTED_MIN_SYMBOLS
        assert report.parse_errors == []
        assert report.elapsed_ms < 5000
        assert idx.count() == report.symbols_indexed


def test_initial_build_is_idempotent() -> None:
    with SymbolIndex() as idx:
        first = initial_build(FIXTURE_ROOT, idx)
        second = initial_build(FIXTURE_ROOT, idx)
        assert first.symbols_indexed == second.symbols_indexed
        assert idx.count() == first.symbols_indexed


def test_initial_build_records_parse_errors_and_continues(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text("def x(): pass\n", encoding="utf-8")
    # A .py file with invalid UTF-8 is still fine (parser reads bytes)
    # so instead force a parse error by injecting a bad extension in
    # extensions but no matching language module — the dispatcher raises
    # UnsupportedLanguageError which the walker catches into
    # parse_errors.
    (tmp_path / "config.xyz").write_text("x = 1\n", encoding="utf-8")
    with SymbolIndex() as idx:
        report = initial_build(tmp_path, idx, extensions=(".py", ".xyz"))
        assert report.files_parsed == 2
        # One parse error for .xyz; one good insertion for .py.
        assert len(report.parse_errors) == 1
        assert report.parse_errors[0].error_type == "UnsupportedLanguageError"
        assert idx.count() == 1  # only the .py symbol landed


def test_initial_build_populates_query_paths() -> None:
    with SymbolIndex() as idx:
        initial_build(FIXTURE_ROOT, idx)
        # find_by_name spans languages: Greeter appears in Python +
        # TypeScript + Rust + Go (as class or struct).
        greeters = idx.find_by_name("Greeter")
        languages = {r.language for r in greeters}
        assert {"python", "typescript", "rust", "go"}.issubset(languages)
