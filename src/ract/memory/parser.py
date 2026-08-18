"""Extension-based dispatch to the per-language parsers.

- ``.py`` -> :mod:`ract.memory.languages.python`
- ``.ts`` / ``.tsx`` -> :mod:`ract.memory.languages.typescript`
- ``.rs`` -> :mod:`ract.memory.languages.rust`
- ``.go`` -> :mod:`ract.memory.languages.go`

Also ships two utilities the language parsers already use internally
but which callers outside the parser want direct access to:
:func:`compute_content_hash` (SHA-256 of the source bytes, hex) and
:func:`estimate_tokens` (whitespace-split proxy — same shape as the
v0.1 ``token_budget.py`` heuristic).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.symbol_index import SymbolRow


class UnsupportedLanguageError(RuntimeError):
    """Raised when :func:`parse_file` is asked about an unsupported extension."""


ParseFn = Callable[[bytes, Path], list[SymbolRow]]


def _load_language(module_name: str) -> ParseFn:
    """Import the language module lazily and return its ``parse`` callable.

    Lazy import means a caller that only touches Python files does
    not pay the grammar-version-mismatch cost for TypeScript / Rust /
    Go until the first cross-language file lands.
    """
    import importlib

    module: Any = importlib.import_module(module_name)
    return module.parse  # type: ignore[no-any-return]


EXTENSION_TO_MODULE: dict[str, str] = {
    ".py": "ract.memory.languages.python",
    ".ts": "ract.memory.languages.typescript",
    ".tsx": "ract.memory.languages.typescript",
    ".rs": "ract.memory.languages.rust",
    ".go": "ract.memory.languages.go",
}
"""File-extension to language module lookup."""


SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(sorted(EXTENSION_TO_MODULE))


def parse_file(path: Path) -> list[SymbolRow]:
    """Parse ``path`` and return the flat list of :class:`SymbolRow`.

    Raises :class:`UnsupportedLanguageError` for extensions not in
    :data:`EXTENSION_TO_MODULE`. Reads the file as bytes and delegates
    to the language module keyed by the extension.
    """
    suffix = path.suffix
    if suffix not in EXTENSION_TO_MODULE:
        raise UnsupportedLanguageError(
            f"parse_file: {suffix!r} not in supported extensions "
            f"{SUPPORTED_EXTENSIONS!r}"
        )
    parser = _load_language(EXTENSION_TO_MODULE[suffix])
    source = path.read_bytes()
    return parser(source, path)


def compute_content_hash(source: str | bytes) -> str:
    """Return the SHA-256 hex digest of ``source``."""
    if isinstance(source, str):
        source = source.encode("utf-8")
    return hashlib.sha256(source).hexdigest()


def estimate_tokens(source: str | bytes) -> int:
    """Return a whitespace-split token estimate for ``source``.

    Same shape as the v0.1 ``token_budget.py`` heuristic. Note the
    v0.5.0 ADR-0031 known-bias caveat: this under-counts BPE tokens
    by 20-40 percent on typical code; per-provider tokenizers land in
    module_09.
    """
    if isinstance(source, bytes):
        source = source.decode("utf-8", errors="replace")
    return len(source.split())


__all__ = [
    "EXTENSION_TO_MODULE",
    "SUPPORTED_EXTENSIONS",
    "UnsupportedLanguageError",
    "compute_content_hash",
    "estimate_tokens",
    "parse_file",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
