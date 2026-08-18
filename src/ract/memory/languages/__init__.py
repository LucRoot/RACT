"""Per-language parser modules for the symbol index.

Each language module (``python``, ``typescript``, ``rust``, ``go``)
exports a ``parse(source: bytes, path: Path) -> list[SymbolRow]``
function and a ``SUPPORTED_GRAMMAR_VERSION`` constant (the pinned
``tree_sitter_<lang>`` package version — Lateral Chain branch A).

The grammar version pin closes the silent-parse-failure worry: a
mismatched grammar (e.g. TypeScript 0.20 vs 0.21 renamed node kinds)
raises :class:`GrammarVersionMismatchError` at parser construction
rather than producing an empty symbol list.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` section
"Chunk discipline / AST chunking rules".
"""

from __future__ import annotations

from ract.core.module_identity import _module_knot, register_module_knot


class GrammarVersionMismatchError(RuntimeError):
    """Raised when a language module detects a mismatched grammar version.

    Carries ``language`` (label), ``expected`` (the pinned version
    the language module was written against), and ``observed`` (the
    version the installed ``tree_sitter_<lang>`` package reports).
    """

    def __init__(self, *, language: str, expected: str, observed: str) -> None:
        self.language = language
        self.expected = expected
        self.observed = observed
        super().__init__(
            f"grammar version mismatch for {language}: "
            f"expected {expected!r}, observed {observed!r}. Reinstall "
            f"tree-sitter-{language} at the expected version or update "
            f"the pinned version constant in the language module."
        )


def _installed_version(package_name: str) -> str:
    """Return the installed version string for ``package_name``.

    Uses :func:`importlib.metadata.version` so the answer is the
    distribution version PyPI shipped, not the tree-sitter grammar
    ABI (which is unreliable across grammar packages — see
    ``tree_sitter.Language.semantic_version`` returning ``None`` for
    the TypeScript grammar).
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(package_name)
    except PackageNotFoundError:
        return "not-installed"


__all__ = [
    "GrammarVersionMismatchError",
    "_installed_version",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
