"""multilspy LSP wrapper for the module_03 graph populator.

Wraps :class:`multilspy.SyncLanguageServer` so the graph populator
can request references without carrying the multilspy config
plumbing at every call site. Adapters map RACT's language labels
(the strings the module_02 parsers emit into
:class:`~ract.memory.symbol_index.SymbolRow.language`) to
multilspy's :class:`~multilspy.multilspy_config.Language` enum.

Every language server is a heavyweight subprocess (Lateral Chain
branch C). The :class:`LspClient` keeps one server alive for its
lifetime and shuts it down on :meth:`close`; per-query start-up
cost is paid once, not per call.

The multilspy dependency is import-guarded so a caller that only
wants the fallback path (module_03 fallback branch, symbol-only
mode) does not have to install multilspy at all. A missing
multilspy install surfaces through :func:`probe_lsp` as
``available=False`` with a specific ``error_message`` naming the
install command.

Referenced from graph_populator via the two entry points on
:class:`LspClient`:

- :meth:`LspClient.references_of` — returns an :class:`EdgeRow`
  per LSP reference for one source symbol.
- :meth:`LspClient.probe` — synthetic ``references`` query that
  verifies the server not only initialises but also implements
  the ``textDocument/references`` capability (Second Pass Q3).

The multilspy API stabilised to ``SyncLanguageServer.create`` /
``request_references`` in 0.0.15 (2026-06); an ADR pin in
``pyproject.toml`` reflects that (Lateral Chain branch A).
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Iterable

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.graph_index import EdgeRow
from ract.memory.symbol_index import SymbolRow


_LOGGER = logging.getLogger(__name__)


LSP_ADAPTERS: dict[str, str] = {
    "python": "python",
    "typescript": "typescript",
    "rust": "rust",
    "go": "go",
}
"""RACT language label -> multilspy language name.

Constrained to the four languages module_02 parses (chunker-
parity constraint from module_02 POST-A): opening an LSP for a
language module_02 does not chunk would populate the graph with
edges pointing at symbol ids that do not exist.
"""


LSP_BINARY_HINTS: dict[str, tuple[str, ...]] = {
    "python": ("jedi-language-server", "pylsp", "pyright-langserver"),
    "typescript": ("typescript-language-server",),
    "rust": ("rust-analyzer",),
    "go": ("gopls",),
}
"""PATH-lookup hints for the probe. First hit wins.

multilspy bundles its own downloads for some servers; the hints
here inform the ``error_message`` on
:func:`probe_lsp` failure so the caller sees which binary is
missing rather than an opaque multilspy stack trace.
"""


@dataclass
class LspProbeResult:
    """Result of :func:`probe_lsp` for one language.

    - ``language`` — the RACT language label probed.
    - ``available`` — True iff the LSP started and answered a
      synthetic ``request_references`` call.
    - ``version`` — best-effort binary version string;
      ``None`` if not obtainable.
    - ``latency_ms`` — wall-clock time to start, query, and stop
      the server.
    - ``error_message`` — populated when ``available`` is False;
      names the failing step (binary missing, initialise refused,
      references unsupported).
    """

    language: str
    available: bool
    version: str | None = None
    latency_ms: int = 0
    error_message: str | None = None


@dataclass
class LspReference:
    """One LSP reference hit, before conversion to :class:`EdgeRow`.

    Keeps the LSP-native fields (``relative_path``, ``line``,
    ``column``, ``end_line``, ``end_column``) around so the
    populator can resolve the target symbol id from the module_02
    symbol store rather than trusting the LSP's textual match.
    """

    relative_path: str
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class LspUnavailableError(RuntimeError):
    """Raised when a caller opens :class:`LspClient` for an unsupported language."""


def _load_multilspy() -> tuple[Any, Any, Any, Any]:
    """Import multilspy lazily and return the shipped symbols.

    Returns ``(SyncLanguageServer, MultilspyConfig, Language,
    MultilspyLogger)``. Raises :class:`ModuleNotFoundError` with a
    specific install hint if multilspy is missing.
    """
    try:
        from multilspy import SyncLanguageServer  # type: ignore[import-untyped]
        from multilspy.multilspy_config import (  # type: ignore[import-untyped]
            Language,
            MultilspyConfig,
        )
        from multilspy.multilspy_logger import (  # type: ignore[import-untyped]
            MultilspyLogger,
        )
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "multilspy is not installed. Install it with "
            "``pip install multilspy>=0.0.15,<0.1``. "
            "The graph populator falls back to symbol-only mode when "
            "multilspy is unavailable (see "
            "``ract.memory.lsp_fallback.populate_symbol_only``)."
        ) from exc
    return SyncLanguageServer, MultilspyConfig, Language, MultilspyLogger


class LspClient:
    """multilspy wrapper for one language + one repository root.

    Each instance owns one language-server subprocess for the
    lifetime of the object. Callers construct one client per
    language they need to query and re-use it across every source
    file for that language; the graph populator does exactly this
    (:meth:`~ract.memory.graph_populator.GraphPopulator.initial_build`).

    Use as a context manager to guarantee subprocess cleanup:

    .. code-block:: python

        with LspClient(repo_root, "python") as client:
            for ref in client.references_of(symbol):
                ...
    """

    def __init__(
        self,
        repo_root: Path | str,
        language: str,
        timeout_seconds: int = 30,
    ) -> None:
        if language not in LSP_ADAPTERS:
            raise LspUnavailableError(
                f"LspClient: language {language!r} not in {sorted(LSP_ADAPTERS)!r}. "
                f"The graph populator only supports languages the module_02 "
                f"symbol index parses."
            )
        self._repo_root = Path(repo_root).resolve()
        self._language = language
        self._timeout = timeout_seconds
        (
            self._SyncLanguageServer,
            self._MultilspyConfig,
            self._Language,
            self._MultilspyLogger,
        ) = _load_multilspy()
        config = self._MultilspyConfig(
            code_language=self._Language(LSP_ADAPTERS[language]),
            trace_lsp_communication=False,
        )
        logger = self._MultilspyLogger()
        self._server = self._SyncLanguageServer.create(
            config, logger, str(self._repo_root), timeout=timeout_seconds
        )
        self._context: Any | None = None
        self._server.start_server()
        # ``start_server`` on SyncLanguageServer returns an iterator
        # context; entering it makes the JSON-RPC channel live.
        self._context = self._server.start_server().__enter__()

    def __enter__(self) -> "LspClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Shut the underlying LSP subprocess down."""
        try:
            if self._context is not None:
                self._context.__exit__(None, None, None)
        except Exception:
            _LOGGER.debug("LspClient.close: subprocess shutdown raised", exc_info=True)
        finally:
            self._context = None

    @property
    def language(self) -> str:
        return self._language

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    def references_of(self, symbol: SymbolRow) -> list[LspReference]:
        """Return the LSP references for ``symbol`` inside the repo.

        The symbol's ``file_path`` is resolved relative to the
        repo root; the LSP is queried at the symbol's
        ``start_line`` and column 0 (approximate; module_02
        parsers do not currently emit ``start_col``, so column 0
        is the pragmatic choice — the LSP resolves the reference
        by symbol identity regardless).
        """
        if symbol.start_line is None:
            return []
        try:
            rel = str(Path(symbol.file_path).resolve().relative_to(self._repo_root))
        except ValueError:
            # Symbol lives outside the LSP's repo root; skip.
            return []
        rel_posix = rel.replace("\\", "/")
        try:
            with self._server.open_file(rel_posix):
                locations = self._server.request_references(
                    rel_posix, symbol.start_line, 0
                )
        except Exception as exc:
            _LOGGER.warning(
                "LspClient.references_of: LSP call failed for %s (%s): %s",
                symbol.name,
                symbol.file_path,
                exc,
            )
            return []
        results: list[LspReference] = []
        for loc in locations or []:
            rel_path = loc.get("relativePath") or loc.get("uri", "")
            range_ = loc.get("range", {})
            start = range_.get("start", {})
            end = range_.get("end", {})
            results.append(
                LspReference(
                    relative_path=str(rel_path).replace("file://", ""),
                    line=int(start.get("line", 0)),
                    column=int(start.get("character", 0)),
                    end_line=int(end.get("line", 0)) if end else None,
                    end_column=int(end.get("character", 0)) if end else None,
                    extras=dict(loc),
                )
            )
        return results

    def as_edges(
        self,
        symbol: SymbolRow,
        symbol_resolver: Callable[[str, int], int | None],
    ) -> list[EdgeRow]:
        """Return :class:`EdgeRow` values for every reference to ``symbol``.

        ``symbol_resolver(path, line)`` maps an LSP reference site
        back to the caller symbol's ``symbols.id`` in module_02's
        store. The populator supplies this lookup by pre-loading
        the symbol id-by-line map per file.
        """
        if symbol.id is None:
            return []
        edges: list[EdgeRow] = []
        for ref in self.references_of(symbol):
            source_id = symbol_resolver(ref.relative_path, ref.line)
            if source_id is None or source_id == symbol.id:
                # Skip self-references (the reference at the symbol's
                # own definition line).
                continue
            edges.append(
                EdgeRow(
                    id=None,
                    source_symbol_id=source_id,
                    target_symbol_id=symbol.id,
                    edge_type="references",
                    location_file=ref.relative_path,
                    location_line=ref.line + 1,  # LSP is 0-indexed
                    strength=1,
                    neighborhood_source="lsp",
                )
            )
        return edges


def probe_lsp(language: str, repo_root: Path | str | None = None) -> LspProbeResult:
    """Run a synthetic probe of the LSP for ``language``.

    Starts the LSP, opens a throwaway source file inside
    ``repo_root`` (or a temp dir), issues a
    ``textDocument/references`` request, and returns
    :class:`LspProbeResult`. On any failure returns
    ``available=False`` with the failure named in
    ``error_message``.

    Second Pass Q3: this probe MUST exercise the
    ``references`` capability, not just ``initialize``, so a
    server that answers initialise but not references is reported
    as unavailable.
    """
    if language not in LSP_ADAPTERS:
        return LspProbeResult(
            language=language,
            available=False,
            error_message=(
                f"probe_lsp: language {language!r} not in {sorted(LSP_ADAPTERS)!r}"
            ),
        )
    root = Path(repo_root).resolve() if repo_root is not None else Path.cwd()
    started = time.perf_counter()
    # Cheap short-circuit: if none of the known binaries are on PATH
    # AND multilspy did not bundle a downloader for the language, we
    # can save the multilspy start-up cost and report unavailable.
    hints = LSP_BINARY_HINTS.get(language, ())
    binary_on_path = any(shutil.which(name) is not None for name in hints)
    version: str | None = None
    try:
        client = LspClient(root, language, timeout_seconds=15)
    except ModuleNotFoundError as exc:
        return LspProbeResult(
            language=language,
            available=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_message=str(exc),
        )
    except Exception as exc:
        return LspProbeResult(
            language=language,
            available=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_message=(
                f"probe_lsp: LspClient construction failed for {language}: "
                f"{type(exc).__name__}: {exc}"
                + ("" if binary_on_path else " (no binary hint found on PATH)")
            ),
        )
    try:
        # Exercise the references capability, not just initialize.
        probe_symbol = SymbolRow(
            id=0,
            name="__probe__",
            kind="function",
            file_path=str(root),
            start_line=0,
            end_line=0,
            signature=None,
            docstring=None,
            visibility=None,
            parent_symbol_id=None,
            language=language,
            content_hash=None,
            token_count=None,
            updated_at=None,
        )
        # We do not care about the count; an empty list is a valid
        # "capability supported, no matches" answer.
        _ = client.references_of(probe_symbol)
        elapsed = int((time.perf_counter() - started) * 1000)
        return LspProbeResult(
            language=language,
            available=True,
            version=version,
            latency_ms=elapsed,
        )
    except Exception as exc:
        return LspProbeResult(
            language=language,
            available=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_message=(
                f"probe_lsp: references capability failed for {language}: "
                f"{type(exc).__name__}: {exc}"
            ),
        )
    finally:
        try:
            client.close()
        except Exception:
            _LOGGER.debug("probe_lsp: close raised", exc_info=True)


def available_languages(
    languages: Iterable[str] | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, LspProbeResult]:
    """Probe every language in ``languages`` (defaults to :data:`LSP_ADAPTERS`).

    Returns a dict keyed by RACT language label -> probe result.
    The populator uses this to build the per-language client map,
    marking unsupported languages for fallback in one pass.
    """
    langs = tuple(languages) if languages is not None else tuple(LSP_ADAPTERS)
    return {lang: probe_lsp(lang, repo_root) for lang in langs}


__all__ = [
    "LSP_ADAPTERS",
    "LSP_BINARY_HINTS",
    "LspClient",
    "LspProbeResult",
    "LspReference",
    "LspUnavailableError",
    "available_languages",
    "probe_lsp",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
