"""Filesystem walker + initial-build entry point for the symbol index.

- :func:`walk` yields every file under a root that matches the
  supplied extension set. Respects ``.gitignore`` and ``.ractignore``
  via ``pathspec`` (Lateral Chain branch C: binary files or
  generated code should not swamp the index).
- :func:`initial_build` full-walks the root, parses every file,
  writes into the :class:`SymbolIndex`, and returns a
  :class:`BuildReport` naming files parsed, symbols indexed, elapsed
  wall time, and any per-file parse errors.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import pathspec

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.parser import (
    SUPPORTED_EXTENSIONS,
    UnsupportedLanguageError,
    parse_file,
)
from ract.memory.symbol_index import SymbolIndex


DEFAULT_EXTENSIONS: tuple[str, ...] = SUPPORTED_EXTENSIONS
"""Default extension set the walker filters on."""


@dataclass(frozen=True)
class ParseError:
    """One parse failure recorded during an initial build."""

    file_path: str
    error_type: str
    message: str


@dataclass
class BuildReport:
    """Result of :func:`initial_build`.

    - ``files_parsed`` — number of files the walker handed to the parser
      (whether or not the parse succeeded).
    - ``symbols_indexed`` — number of :class:`SymbolRow` values inserted.
    - ``elapsed_ms`` — wall-clock time in whole milliseconds.
    - ``parse_errors`` — one :class:`ParseError` per per-file failure;
      empty list means every parse succeeded.
    """

    files_parsed: int = 0
    symbols_indexed: int = 0
    elapsed_ms: int = 0
    parse_errors: list[ParseError] = field(default_factory=list)


def _load_ignore_spec(root: Path) -> pathspec.PathSpec:
    """Compose a PathSpec from ``.gitignore`` + ``.ractignore`` at ``root``.

    Missing files are treated as empty. ``.ractignore`` extends
    ``.gitignore`` (both are additive; a pattern in either excludes).
    """
    lines: list[str] = []
    for name in (".gitignore", ".ractignore"):
        candidate = root / name
        if candidate.is_file():
            lines.extend(
                line
                for line in candidate.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
    # Always exclude .git, __pycache__, node_modules on top of the
    # user-declared patterns; these carry no source-symbol value and
    # slow the walk substantially.
    lines.extend([".git/", "__pycache__/", "node_modules/", ".venv/", "target/"])
    # ``gitignore`` supersedes the ``gitwildmatch`` factory in pathspec
    # 1.x (which emits a DeprecationWarning on use).
    return pathspec.PathSpec.from_lines("gitignore", lines)


def walk(
    root: Path,
    extensions: Sequence[str] = DEFAULT_EXTENSIONS,
) -> Iterator[Path]:
    """Yield every file under ``root`` whose suffix is in ``extensions``.

    ``.gitignore`` + ``.ractignore`` at ``root`` filter the walk.
    Files are yielded in a deterministic (sorted) order so a
    downstream :func:`initial_build` produces a stable ``id`` sequence
    across runs.
    """
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"walk: root is not a directory: {root!r}")
    ext_set = frozenset(extensions)
    spec = _load_ignore_spec(root)
    collected: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in ext_set:
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if spec.match_file(rel):
            continue
        collected.append(path)
    collected.sort()
    for path in collected:
        yield path


def initial_build(
    root: Path,
    index: SymbolIndex,
    extensions: Sequence[str] = DEFAULT_EXTENSIONS,
) -> BuildReport:
    """Full walk + parse + insert over ``root`` into ``index``.

    Parse errors are collected into the returned :class:`BuildReport`;
    they do NOT halt the build. The walker still yields every file so
    the caller can decide (per language module maturity) which errors
    are load-bearing.
    """
    started = time.perf_counter()
    report = BuildReport()
    for path in walk(root, extensions):
        report.files_parsed += 1
        try:
            rows = parse_file(path)
        except UnsupportedLanguageError:
            # A .py file whose extension was filtered in by the caller
            # should never trip this — but if it does, treat as parse
            # error and continue.
            report.parse_errors.append(
                ParseError(
                    file_path=str(path),
                    error_type="UnsupportedLanguageError",
                    message=f"extension {path.suffix!r} unsupported",
                )
            )
            continue
        except Exception as exc:  # pragma: no cover - defensive
            report.parse_errors.append(
                ParseError(
                    file_path=str(path),
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            )
            continue
        index.replace_file(str(path), rows)
        report.symbols_indexed += len(rows)
    report.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return report


def resolve_paths(paths: Iterable[Path]) -> list[Path]:
    """Return the deduplicated list of resolved absolute paths."""
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        rp = path.resolve()
        key = str(rp)
        if key in seen:
            continue
        seen.add(key)
        out.append(rp)
    return out


__all__ = [
    "BuildReport",
    "DEFAULT_EXTENSIONS",
    "ParseError",
    "initial_build",
    "resolve_paths",
    "walk",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
