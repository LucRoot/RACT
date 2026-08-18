"""LSP-driven edge population for the module_03 graph index.

Walks every symbol in the module_02
:class:`~ract.memory.symbol_index.SymbolIndex`, opens one
:class:`~ract.memory.lsp.LspClient` per language, runs
``references_of`` per symbol, and inserts the resulting edges
into the :class:`~ract.memory.graph_index.GraphIndex`.

Batches LSP calls by file (Lateral Chain branch B) — one LSP
open-file per source file rather than per symbol. Per-language
clients are kept alive for the whole build (Lateral Chain
branch C) so ``rust-analyzer`` and ``gopls`` pay their multi-
second start-up cost once.

Fallback: when :func:`~ract.memory.lsp.probe_lsp` reports a
language as unavailable, the populator invokes
:func:`~ract.memory.lsp_fallback.populate_symbol_only` for every
symbol in that language and continues; the build does not fail.

Import-alias resolver (module_02 POST-E constraint): callers
identified by the LSP are looked up in the module_02 symbol store
by (file, line) rather than by name-string, so an aliased import
``from foo import Bar as _b`` resolves the edge source correctly
via the caller's own symbol id.

Consistency (Second Pass Q1): every per-file update runs under a
single :class:`GraphIndex.insert_edges` batch inside a
BEGIN/COMMIT transaction. A mid-batch LSP crash rolls back so
partial edges never land.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.graph_index import EdgeRow, GraphIndex
from ract.memory.lsp import (
    LSP_ADAPTERS,
    LspClient,
    LspProbeResult,
    LspUnavailableError,
    available_languages,
)
from ract.memory.lsp_fallback import populate_symbol_only
from ract.memory.symbol_index import SymbolIndex, SymbolRow


_LOGGER = logging.getLogger(__name__)


@dataclass
class BuildReport:
    """Result of :meth:`GraphPopulator.initial_build`.

    - ``edges_indexed`` — count of edges the populator inserted
      (LSP + fallback both counted).
    - ``lsp_calls`` — count of ``references_of`` calls issued;
      one per LSP-eligible symbol.
    - ``lsp_errors`` — count of failed ``references_of`` calls
      (the client logged a warning and returned an empty list).
    - ``fallback_languages`` — sorted tuple of languages the
      populator downgraded to symbol-only mode.
    - ``elapsed_ms`` — wall-clock time in whole milliseconds.
    """

    edges_indexed: int = 0
    lsp_calls: int = 0
    lsp_errors: int = 0
    fallback_languages: list[str] = field(default_factory=list)
    elapsed_ms: int = 0


@dataclass
class UpdateReport:
    """Result of :meth:`GraphPopulator.update_file`.

    - ``deleted`` — count of pre-existing edges the update
      removed.
    - ``inserted`` — count of fresh edges inserted.
    - ``elapsed_ms`` — wall-clock time in whole milliseconds.
    - ``used_fallback`` — True iff the update ran through
      :func:`populate_symbol_only`.
    """

    deleted: int = 0
    inserted: int = 0
    elapsed_ms: int = 0
    used_fallback: bool = False


class GraphPopulator:
    """LSP-driven populator for :class:`GraphIndex`.

    Owns one :class:`LspClient` per language for its lifetime.
    Constructed with the module_02 symbol index and the module_03
    graph index; the caller invokes :meth:`initial_build` once at
    startup and :meth:`update_file` per file save (module_09 wires
    the latter onto the module_02 watcher).

    Use as a context manager to guarantee LSP subprocesses shut
    down on exit.
    """

    def __init__(
        self,
        repo_root: Path | str,
        graph: GraphIndex,
        symbols: SymbolIndex,
        client_factory: Callable[[Path, str], LspClient] | None = None,
    ) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._graph = graph
        self._symbols = symbols
        self._clients: dict[str, LspClient] = {}
        self._fallback_languages: set[str] = set()
        # Factory is a hook for tests to swap in a stub client. When the
        # caller supplies one, initial_build skips the multilspy probe
        # entirely and treats every language as available; a factory
        # that raises still triggers per-language fallback.
        self._client_factory: Callable[[Path, str], LspClient]
        if client_factory is None:
            self._client_factory = lambda root, lang: LspClient(root, lang)
            self._skip_probe: bool = False
        else:
            self._client_factory = client_factory
            self._skip_probe = True

    def __enter__(self) -> "GraphPopulator":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def close(self) -> None:
        """Shut every LSP subprocess this populator started."""
        for client in list(self._clients.values()):
            try:
                client.close()
            except Exception:
                _LOGGER.debug(
                    "GraphPopulator.close: subprocess shutdown raised",
                    exc_info=True,
                )
        self._clients.clear()

    @property
    def fallback_languages(self) -> tuple[str, ...]:
        return tuple(sorted(self._fallback_languages))

    def _ensure_client(self, language: str) -> LspClient | None:
        """Return the cached client for ``language`` or start a fresh one.

        Returns ``None`` if the language is already marked for
        fallback (either the initial probe rejected it or a prior
        client-start attempt failed).
        """
        if language in self._fallback_languages:
            return None
        if language in self._clients:
            return self._clients[language]
        try:
            client = self._client_factory(self._repo_root, language)
        except (LspUnavailableError, ModuleNotFoundError, Exception) as exc:
            _LOGGER.warning(
                "GraphPopulator: LSP unavailable for %s (%s); fallback engaged",
                language,
                exc,
            )
            self._fallback_languages.add(language)
            return None
        self._clients[language] = client
        return client

    def _global_resolver(self) -> Callable[[str, int], int | None]:
        """Return a (path, line) -> symbol_id lookup across every file.

        LSP references frequently cross files (a caller in
        ``b.py`` referring to a callee defined in ``a.py``), so
        the resolver must lookup by the LSP's REPORTED path, not
        the symbol's original file. A per-file cache prevents
        re-fetching the same file's rows for every symbol.
        """
        cache: dict[str, list[SymbolRow]] = {}

        def _rows_for(path_str: str) -> list[SymbolRow]:
            if path_str not in cache:
                cache[path_str] = sorted(
                    (
                        r
                        for r in self._symbols.find_in_file(path_str)
                        if r.start_line is not None
                    ),
                    key=lambda r: r.start_line or 0,
                )
            return cache[path_str]

        def resolver(path: str, line: int) -> int | None:
            # Line is LSP-native (0-indexed); symbol_index is
            # 1-indexed. Normalise before comparing.
            normalised = line + 1
            candidates = _rows_for(self._resolve_path(path))
            best_id: int | None = None
            for row in candidates:
                start = row.start_line or 0
                end = row.end_line or start
                if start <= normalised <= end:
                    best_id = row.id
            return best_id

        return resolver

    def _resolve_path(self, ref_path: str) -> str:
        """Resolve an LSP reference path against the symbol index.

        LSP paths are usually relative to the repo root. The
        module_02 symbol index stores absolute paths, so this
        helper joins the LSP path with the repo root and returns
        the resolved absolute path as a string.
        """
        candidate = Path(ref_path)
        if not candidate.is_absolute():
            candidate = self._repo_root / candidate
        try:
            return str(candidate.resolve())
        except OSError:
            return str(candidate)

    def initial_build(self) -> BuildReport:
        """Walk every symbol in the store and populate edges.

        Returns a :class:`BuildReport` with per-language fallback
        + LSP call counts. Fails soft on individual LSP errors
        (warning logged, symbol skipped) so a single broken
        reference does not stop the build (Lateral Chain
        branch C).
        """
        started = time.perf_counter()
        report = BuildReport()
        # Probe every language once up front so a per-file loop
        # does not repeatedly retry a missing LSP. Skipped when a
        # client_factory hook is injected (tests supply their own
        # stub; a raising factory still triggers per-language
        # fallback via _ensure_client).
        probes: dict[str, LspProbeResult] = {}
        if not self._skip_probe:
            probes = available_languages(LSP_ADAPTERS.keys(), self._repo_root)
            for lang, probe in probes.items():
                if not probe.available:
                    self._fallback_languages.add(lang)
                    _LOGGER.info(
                        "GraphPopulator: probe for %s failed (%s); fallback engaged",
                        lang,
                        probe.error_message,
                    )
        # Bucket symbols by language.
        by_language: dict[str, list[SymbolRow]] = {}
        # Fetch symbols via a cursor to avoid materialising 100k rows.
        cur = self._symbols.connection.execute(
            "SELECT * FROM symbols ORDER BY file_path, start_line"
        )
        from ract.memory.symbol_index import _row_from_sqlite as sym_row

        for sql_row in cur.fetchall():
            row = sym_row(sql_row)
            if row.language is None or row.language not in LSP_ADAPTERS:
                continue
            by_language.setdefault(row.language, []).append(row)
        # LSP path per language.
        for language, symbols in by_language.items():
            client = self._ensure_client(language)
            if client is None:
                probe_result = probes.get(language)
                reason = "no probe result"
                if probe_result is not None and probe_result.error_message:
                    reason = probe_result.error_message
                inserted = populate_symbol_only(
                    self._graph, symbols, language, reason=reason
                )
                report.edges_indexed += inserted
                continue
            # Group symbols by file so we open each file once.
            by_file: dict[str, list[SymbolRow]] = {}
            for symbol in symbols:
                by_file.setdefault(symbol.file_path, []).append(symbol)
            resolver = self._global_resolver()
            for file_path, file_symbols in by_file.items():
                edges_for_file: list[EdgeRow] = []
                for symbol in file_symbols:
                    report.lsp_calls += 1
                    try:
                        edges = client.as_edges(symbol, resolver)
                    except Exception as exc:
                        report.lsp_errors += 1
                        _LOGGER.warning(
                            "GraphPopulator.initial_build: LSP error for %s:%s "
                            "(%s); skipping",
                            symbol.file_path,
                            symbol.name,
                            exc,
                        )
                        continue
                    edges_for_file.extend(edges)
                if edges_for_file:
                    inserted_ids = self._graph.insert_edges(edges_for_file)
                    report.edges_indexed += len(inserted_ids)
        report.fallback_languages = sorted(self._fallback_languages)
        report.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return report

    def update_file(self, path: Path | str) -> UpdateReport:
        """Re-populate edges for one source file.

        Deletes stale edges by source file and re-runs the LSP for
        each symbol in the file. Called from the module_02
        watcher on save (module_09 wires the callback).
        """
        started = time.perf_counter()
        report = UpdateReport()
        path_str = str(Path(path).resolve())
        # Detect language from the file's symbols; if the file has
        # no symbols in the index yet, we skip (the watcher will
        # re-invoke once parse-and-diff catches up).
        file_symbols = self._symbols.find_in_file(path_str)
        if not file_symbols:
            report.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return report
        languages = {row.language for row in file_symbols if row.language}
        # Delete stale edges anchored at this file.
        report.deleted = self._graph.delete_by_source_file(path_str)
        for language in languages:
            if language not in LSP_ADAPTERS:
                continue
            client = self._ensure_client(language)
            if client is None:
                inserted = populate_symbol_only(
                    self._graph,
                    [r for r in file_symbols if r.language == language],
                    language,
                    reason="update_file fallback",
                )
                report.inserted += inserted
                report.used_fallback = True
                continue
            resolver = self._global_resolver()
            edges: list[EdgeRow] = []
            for symbol in (r for r in file_symbols if r.language == language):
                try:
                    edges.extend(client.as_edges(symbol, resolver))
                except Exception as exc:
                    _LOGGER.warning(
                        "GraphPopulator.update_file: LSP error for %s:%s (%s)",
                        path_str,
                        symbol.name,
                        exc,
                    )
                    continue
            if edges:
                inserted_ids = self._graph.insert_edges(edges)
                report.inserted += len(inserted_ids)
        report.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return report


__all__ = [
    "BuildReport",
    "GraphPopulator",
    "UpdateReport",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
