"""CLI verbs for the v0.5.0 memory-discipline surface.

Module_09 lands three verbs under ``ract memory``:

- ``ract memory init <path>`` — first-run builds of the three
  indexes (symbol, graph, semantic) plus the probe scheduler first
  invocation against the repo at ``<path>``.
- ``ract memory apply-narrowings [--dry-run]`` — invokes the
  failure-record aggregator (module_08) and applies proposed
  budget narrowings from recent :class:`FailureRecord` values.
- ``ract retrieval query <query> [--budget N] [--format
  full|body|sig|summary] [--strategy relevance|complete|core]`` —
  invokes the retrieve primitive (module_05) against the three
  indexes and prints the resulting bundle. Extends the existing
  ``ract retrieval`` verb with a new ``query`` subverb.

The verbs are thin CLI shims over :mod:`ract.memory` primitives.
Each shim degrades gracefully when an optional dependency is
missing (e.g. LanceDB for the semantic index): the command prints
a diagnostic and exits 1 rather than crashing with a traceback.

Reference: RACT v0.5.0 MEMORY DISCIPLINE SPEC §Integration surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ract.core.module_identity import _module_knot, register_module_knot


def memory_command(args: list[str]) -> int:
    """Handle ``ract memory <subverb>``.

    Subverbs: ``init``, ``apply-narrowings``,
    ``verify-consistency`` (v0.5.2 module_06 DA-B F-5.1 companion).

    Returns 0 on success, 1 on any user-visible failure. Prints
    ``[ract]``-prefixed diagnostics on the failure path.
    """
    parser = argparse.ArgumentParser(prog="ract memory")
    # v0.5.1 wiring module_10 (Lens A M7): a bare ``ract memory``
    # prints help and exits 0 -- CI-friendly capability probe.
    if not args:
        parser.print_help()
        return 0
    parser.add_argument(
        "subverb",
        choices=["init", "apply-narrowings", "verify-consistency"],
        help="Memory-discipline action to perform.",
    )
    parsed, rest = parser.parse_known_args(args)
    if parsed.subverb == "init":
        return _memory_init(rest)
    if parsed.subverb == "apply-narrowings":
        return _memory_apply_narrowings(rest)
    if parsed.subverb == "verify-consistency":
        return _memory_verify_consistency(rest)
    parser.print_help()
    return 0


def _memory_verify_consistency(args: list[str]) -> int:
    """v0.5.2 module_06: cross-index consistency verifier CLI.

    Opens the three-index store under ``<repo>/.ract/memory/``
    (symbol + graph; semantic is optional and best-effort) and
    prints a report. Exit codes:

    - 0 -- CONSISTENT
    - 1 -- INCONSISTENT (at least one flagged discrepancy)
    - 2 -- UNAVAILABLE (backing store missing / unreadable)
    """
    import json

    parser = argparse.ArgumentParser(
        prog="ract memory verify-consistency",
        description=(
            "Cross-check symbol / graph / semantic indexes for "
            "orphan edges, missing files, and stale semantic "
            "slices."
        ),
    )
    parser.add_argument(
        "repo_path",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Repository whose .ract/memory store to verify.",
    )
    parser.add_argument(
        "--no-disk-check",
        dest="check_files_on_disk",
        action="store_false",
        default=True,
        help=(
            "Skip the missing-symbol-file check (only useful in "
            "CI where paths are synthetic)."
        ),
    )
    def _positive_int(raw: str) -> int:
        # v0.5.2 module_06 SP Q5 fold: refuse a vacuous cap of
        # 0 or negative. Verify_indexes also refuses at the API
        # boundary; the CLI validation gives a friendlier
        # argparse-formatted error message.
        try:
            v = int(raw)
        except ValueError as exc:  # pragma: no cover - argparse re-wraps
            raise argparse.ArgumentTypeError(str(exc)) from exc
        if v < 1:
            raise argparse.ArgumentTypeError(
                f"must be >= 1; got {v}"
            )
        return v

    parser.add_argument(
        "--max-inconsistencies",
        type=_positive_int,
        default=500,
        help="Cap on returned detail entries (default 500; must be >= 1).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit a JSON report instead of human-readable text.",
    )
    parsed = parser.parse_args(args)
    repo_path: Path = parsed.repo_path.resolve()

    from ract.memory.symbol_index import SymbolIndex
    from ract.memory.graph_index import GraphIndex
    from ract.memory.verify_consistency import (
        IndexConsistencyReport,
        verify_indexes,
    )

    sym_db = repo_path / ".ract" / "memory" / "symbols.db"
    graph_db = repo_path / ".ract" / "memory" / "graph.db"
    if not sym_db.is_file():
        report = IndexConsistencyReport.unavailable(
            reason=(
                f"symbol_index DB not found at {sym_db} "
                "(run `ract memory init` first)"
            ),
        )
    else:
        try:
            with SymbolIndex(db_path=str(sym_db)) as sym_idx:
                gi = None
                if graph_db.is_file():
                    try:
                        gi = GraphIndex(
                            db_path=str(graph_db),
                            symbol_index=sym_idx,
                        )
                    except Exception as exc:
                        gi = None
                        print(
                            f"[ract memory verify-consistency] "
                            f"graph_index open failed ({exc}); "
                            "graph check skipped",
                            file=sys.stderr,
                        )
                try:
                    report = verify_indexes(
                        symbol_index=sym_idx,
                        graph_index=gi,
                        semantic_index=None,
                        check_files_on_disk=parsed.check_files_on_disk,
                        max_inconsistencies=parsed.max_inconsistencies,
                    )
                finally:
                    if gi is not None:
                        try:
                            gi.close()
                        except Exception:
                            pass
        except Exception as exc:
            report = IndexConsistencyReport.unavailable(
                reason=f"symbol_index open failed: {exc}",
            )

    if parsed.json_output:
        from ract.canonical import dumps_jcs
        payload = {
            "repo_path": str(repo_path),
            "status": report.status,
            "symbols_checked": report.symbols_checked,
            "edges_checked": report.edges_checked,
            "semantic_slices_checked": report.semantic_slices_checked,
            # v0.5.2 module_06 SP Q5 fold: expose checks_skipped
            # so JSON consumers see the honest partial-sweep
            # signal.
            "checks_skipped": list(report.checks_skipped),
            "reason": report.reason,
            "inconsistencies": [
                {
                    "kind": i.kind,
                    "file": i.file,
                    "symbol_id": i.symbol_id,
                    "edge_id": i.edge_id,
                    "detail": i.detail,
                }
                for i in report.inconsistencies
            ],
        }
        # dumps_jcs returns bytes; decode for print.
        print(dumps_jcs(payload).decode("utf-8"))
    else:
        print(f"[ract memory verify-consistency] {repo_path}")
        print(f"  status: {report.status}")
        print(f"  symbols_checked: {report.symbols_checked}")
        print(f"  edges_checked: {report.edges_checked}")
        print(
            "  semantic_slices_checked: "
            f"{report.semantic_slices_checked}"
        )
        if report.checks_skipped:
            print(
                "  checks_skipped: "
                f"{', '.join(report.checks_skipped)}"
            )
        print(f"  reason: {report.reason}")
        if report.inconsistencies:
            # Cap human-readable print at 20; JSON has all.
            for i in report.inconsistencies[:20]:
                print(f"  - [{i.kind}] {i.detail}")
            if len(report.inconsistencies) > 20:
                print(
                    "  ... "
                    f"{len(report.inconsistencies) - 20} more "
                    "(pass --json for the full list)"
                )

    if report.status == "CONSISTENT":
        return 0
    if report.status == "INCONSISTENT":
        return 1
    return 2


def _memory_init(args: list[str]) -> int:
    """First-run builds of the three indexes against a repo."""
    parser = argparse.ArgumentParser(prog="ract memory init")
    parser.add_argument(
        "repo_path",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to the repository whose indexes are built.",
    )
    parser.add_argument(
        "--skip-semantic",
        dest="skip_semantic",
        action="store_true",
        help=(
            "Skip the semantic-index build. Useful when LanceDB or the "
            "embedding model is unavailable (offline / CI). The symbol "
            "and graph indexes still build."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit a JSON summary instead of human-readable text.",
    )
    parsed = parser.parse_args(args)

    repo_path: Path = parsed.repo_path.resolve()
    if not repo_path.is_dir():
        print(f"[ract] memory init: repo path not found: {repo_path}", file=sys.stderr)
        return 1

    warnings: list[str] = []
    summary: dict[str, object] = {
        "repo_path": str(repo_path),
        "symbol_index": None,
        "graph_index": None,
        "semantic_index": None,
        "warnings": warnings,
    }

    symbol_idx = None
    graph_idx = None
    try:
        # --- symbol index -------------------------------------------------
        from ract.memory import walker
        from ract.memory.symbol_index import SymbolIndex

        db_path = repo_path / ".ract" / "memory" / "symbols.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        symbol_idx = SymbolIndex(db_path=str(db_path))
        sym_report = walker.initial_build(repo_path, symbol_idx)
        summary["symbol_index"] = {
            "db_path": str(db_path),
            "files_parsed": sym_report.files_parsed,
            "symbols_indexed": sym_report.symbols_indexed,
        }
    except Exception as exc:  # noqa: BLE001
        msg = f"symbol index build failed: {exc}"
        warnings.append(msg)
        if not parsed.json_output:
            print(f"[ract] memory init: {msg}", file=sys.stderr)
        return 1

    # --- graph index ------------------------------------------------------
    try:
        from ract.memory.graph_index import GraphIndex
        from ract.memory.graph_populator import GraphPopulator

        graph_db_path = repo_path / ".ract" / "memory" / "graph.db"
        graph_db_path.parent.mkdir(parents=True, exist_ok=True)
        graph_idx = GraphIndex(db_path=str(graph_db_path), symbol_index=symbol_idx)
        with GraphPopulator(repo_path, graph_idx, symbol_idx) as populator:
            populator.initial_build()
        summary["graph_index"] = {"db_path": str(graph_db_path)}
    except Exception as exc:  # noqa: BLE001
        # Non-fatal: LSP unavailable / language server bootstrap failure
        # leaves the symbol index intact. Log the warning and continue.
        msg = f"graph index build failed (non-fatal): {exc}"
        warnings.append(msg)
        if not parsed.json_output:
            print(f"[ract] memory init: {msg}", file=sys.stderr)

    # --- semantic index (optional) ----------------------------------------
    if not parsed.skip_semantic:
        try:
            from ract.memory import semantic_builder
            from ract.memory.semantic_index import SemanticIndex

            semantic_dir = repo_path / ".ract" / "memory" / "semantic"
            semantic_dir.mkdir(parents=True, exist_ok=True)
            semantic_idx = SemanticIndex(
                store_path=semantic_dir, symbol_index=symbol_idx
            )
            semantic_builder.initial_build(repo_path, semantic_idx, symbol_idx)
            summary["semantic_index"] = {"store_dir": str(semantic_dir)}
        except Exception as exc:  # noqa: BLE001
            # Non-fatal: LanceDB or embedding model unavailable. Log and
            # continue — the symbol + graph indexes still deliver value.
            msg = f"semantic index build skipped: {exc}"
            warnings.append(msg)
            if not parsed.json_output:
                print(f"[ract] memory init: {msg}", file=sys.stderr)

    if parsed.json_output:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"[ract] memory init: symbol index built at {repo_path}")
        if summary["graph_index"]:
            print(f"[ract] memory init: graph index built at {repo_path}")
        if summary["semantic_index"]:
            print(f"[ract] memory init: semantic index built at {repo_path}")
    return 0


def _memory_apply_narrowings(args: list[str]) -> int:
    """Invoke the failure aggregator and apply proposed narrowings."""
    parser = argparse.ArgumentParser(prog="ract memory apply-narrowings")
    parser.add_argument(
        "--repo-path",
        type=Path,
        default=Path("."),
        help="Path to the repository whose narrowings are inspected.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print proposed narrowings without applying them.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit a JSON summary instead of human-readable text.",
    )
    parsed = parser.parse_args(args)

    repo_path: Path = parsed.repo_path.resolve()
    try:
        from ract.memory.failure_records import aggregate
    except ImportError as exc:
        print(
            f"[ract] memory apply-narrowings: failure-records module unavailable: {exc}",
            file=sys.stderr,
        )
        return 1

    store_root = repo_path / ".ract" / "memory"
    if not store_root.is_dir():
        if parsed.json_output:
            print(json.dumps({"applied": 0, "proposals": [], "note": "no records"}))
        else:
            print(
                "[ract] memory apply-narrowings: no memory store found at "
                f"{store_root} (run 'ract memory init' first)"
            )
        return 0

    report = aggregate(store_root)
    proposals = list(report.proposals)

    if parsed.json_output:
        print(
            json.dumps(
                {
                    "applied": 0 if parsed.dry_run else len(proposals),
                    "dry_run": parsed.dry_run,
                    "proposals": [
                        {
                            "function": p.function,
                            "field_name": p.field_name,
                            "new_value": p.new_value,
                            "reference_current_value": p.reference_current_value,
                            "reason": p.reason,
                        }
                        for p in proposals
                    ],
                    "window_start": report.window_start,
                    "window_end": report.window_end,
                    "total_records_considered": report.total_records_considered,
                },
                indent=2,
                default=str,
            )
        )
    else:
        if not proposals:
            print("[ract] memory apply-narrowings: no proposals from failure records.")
            return 0
        print(
            f"[ract] memory apply-narrowings: {len(proposals)} "
            f"proposal(s){' (dry-run)' if parsed.dry_run else ''}:"
        )
        for p in proposals:
            print(
                f"  - {p.function}.{p.field_name} -> {p.new_value}"
                f" (from {p.reference_current_value}, reason: {p.reason})"
            )

    if parsed.dry_run:
        return 0

    # Non-dry-run: write applied narrowings back to the budget-registry
    # override file so subsequent runs pick them up.
    try:
        override_path = repo_path / ".ract" / "memory" / "budget_overrides.yaml"
        override_path.parent.mkdir(parents=True, exist_ok=True)
        _write_narrowing_overrides(override_path, proposals)
    except OSError as exc:
        print(
            f"[ract] memory apply-narrowings: could not write overrides: {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


def _write_narrowing_overrides(path: Path, proposals: list) -> None:
    """Persist proposed narrowings as a YAML overrides file.

    Kept small — writes a plain map keyed on function/field so a human
    can inspect and edit the file. A future :class:`BudgetRegistry`
    revision may read this file directly.
    """
    import yaml

    payload: dict[str, dict[str, object]] = {}
    for p in proposals:
        payload.setdefault(p.function, {})[p.field_name] = p.new_value
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


def retrieval_query_command(args: list[str]) -> int:
    """Handle ``ract retrieval query <text> [--k N] [--index KIND] [--json]``.

    v0.5.1 wiring module_10 (Lens A C3 closure): the prior stub
    printed a params-echo diagnostic; the wire now opens the three
    workspace indexes (symbol, graph, semantic -- whichever exist
    under ``.ract/memory/``), runs the retrieve primitive from
    :mod:`ract.memory.retrieve` against them, and prints the
    matching chunks. Missing indexes are tolerated (that branch of
    the cascade no-ops); an unpopulated workspace produces an
    ``"index_not_populated"`` error surface with a clear
    ``ract memory init`` next-step instruction.
    """
    parser = argparse.ArgumentParser(prog="ract retrieval query")
    parser.add_argument("query", help="Retrieval query text (keyword / symbol name).")
    parser.add_argument(
        "--repo-path",
        type=Path,
        default=Path("."),
        help="Path to the repository whose indexes to query.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=None,
        help="Max chunks to surface (default: unbounded; use --budget to cap tokens).",
    )
    parser.add_argument(
        "--index",
        choices=["symbol", "graph", "semantic", "lexical", "all"],
        default="all",
        help="Restrict retrieval to a single index kind (default: all).",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=4000,
        help="Retrieve-local sub-budget in tokens (default: 4000).",
    )
    parser.add_argument(
        "--format",
        choices=["full", "body", "sig", "summary"],
        default="body",
        help="Chunk format the bundle renders (default: body).",
    )
    parser.add_argument(
        "--strategy",
        choices=["relevance", "complete", "core"],
        default="relevance",
        help="Packing strategy for the bundle (default: relevance).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit the bundle as JSON instead of human-readable text.",
    )
    parsed = parser.parse_args(args)

    repo_path: Path = parsed.repo_path.resolve()
    try:
        from ract.memory.chunk import ChunkFormat
        from ract.memory.retrieve import (
            BoundedContextError,
            IndexKind,
            IndexRef,
            RetrievalQuery,
            RetrievalStrategy,
            retrieve,
        )
    except ImportError as exc:
        print(
            f"[ract] retrieval query: memory package unavailable: {exc}",
            file=sys.stderr,
        )
        return 1

    # Build indexes list from what exists on disk. The retrieve
    # primitive tolerates missing kinds; each missing branch no-ops.
    indexes: list = []
    symbol_idx = None
    _load_warnings: list[str] = []
    memory_root = repo_path / ".ract" / "memory"
    want_symbol = parsed.index in {"symbol", "lexical", "all"}
    want_graph = parsed.index in {"graph", "all"}
    want_semantic = parsed.index in {"semantic", "all"}

    if want_symbol:
        try:
            from ract.memory.symbol_index import SymbolIndex

            symbol_db = memory_root / "symbols.db"
            if symbol_db.exists():
                symbol_idx = SymbolIndex(db_path=str(symbol_db))
                indexes.append(IndexRef(kind=IndexKind.SYMBOL, index=symbol_idx))
        except Exception as exc:  # noqa: BLE001
            _load_warnings.append(f"symbol index load failed: {exc}")

    if want_graph:
        try:
            from ract.memory.graph_index import GraphIndex

            graph_db = memory_root / "graph.db"
            if graph_db.exists():
                graph_idx = GraphIndex(db_path=str(graph_db), symbol_index=symbol_idx)
                indexes.append(IndexRef(kind=IndexKind.GRAPH, index=graph_idx))
        except Exception as exc:  # noqa: BLE001
            _load_warnings.append(f"graph index load failed: {exc}")

    if want_semantic:
        try:
            from ract.memory.semantic_index import SemanticIndex

            semantic_dir = memory_root / "semantic"
            if semantic_dir.is_dir():
                semantic_idx = SemanticIndex(
                    store_path=semantic_dir, symbol_index=symbol_idx
                )
                indexes.append(IndexRef(kind=IndexKind.SEMANTIC, index=semantic_idx))
        except Exception as exc:  # noqa: BLE001
            _load_warnings.append(f"semantic index load failed: {exc}")

    fmt_map = {
        "full": ChunkFormat.FULL,
        "body": ChunkFormat.BODY_ONLY,
        "sig": ChunkFormat.SIGNATURE,
        "summary": ChunkFormat.SUMMARY,
    }
    strat_map = {
        "relevance": RetrievalStrategy.RELEVANCE,
        "complete": RetrievalStrategy.COMPREHENSIVE,
        "core": RetrievalStrategy.CORE_FIRST,
    }

    # v0.5.1 module_10: send both a symbol-name seed AND a keyword seed
    # so exact-name matches surface even when the caller typed a
    # bare identifier. The primitive dedups downstream so this cannot
    # double-count.
    query = RetrievalQuery(
        symbol_names=(parsed.query,),
        keywords=(parsed.query,),
    )

    try:
        bundle = retrieve(
            query=query,
            indexes=indexes,
            budget=parsed.budget,
            format=fmt_map[parsed.format],
            strategy=strat_map[parsed.strategy],
        )
    except BoundedContextError as exc:
        print(
            f"[ract] retrieval query: refused (budget {parsed.budget} exhausted "
            f"at cascade level {exc.deepest_level}). Narrow the query or "
            "raise --budget.",
            file=sys.stderr,
        )
        return 1

    chunks = list(bundle.chunks)
    if parsed.k is not None:
        chunks = chunks[: parsed.k]

    if parsed.json_output:
        payload = {
            "query": parsed.query,
            "repo_path": str(repo_path),
            "budget": parsed.budget,
            "format": parsed.format,
            "strategy": parsed.strategy,
            "index_filter": parsed.index,
            "indexes_loaded": [ref.kind.value for ref in indexes],
            "total_tokens": bundle.total_tokens,
            "budget_used_pct": bundle.budget_used_pct,
            "dropped_count": bundle.dropped_count,
            "dropped_symbols": list(bundle.dropped_symbols),
            "final_level": bundle.query_trace.final_level,
            "error": bundle.query_trace.error,
            "chunks": [
                {
                    "symbol_name": c.symbol_name,
                    "file_path": c.file_path,
                    "language": c.language,
                    "token_count": c.token_count,
                    "signature": c.signature,
                    "body": c.body,
                }
                for c in chunks
            ],
            "warnings": _load_warnings,
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0

    # Human-readable output.
    print(f"[ract] retrieval query: '{parsed.query}' against {repo_path}")
    if _load_warnings:
        for w in _load_warnings:
            print(f"  warn: {w}", file=sys.stderr)
    if not indexes:
        print(
            "[ract] retrieval query: no indexes found under .ract/memory/. "
            "Run 'ract memory init' first.",
            file=sys.stderr,
        )
        return 0
    if bundle.query_trace.error == "index_not_populated":
        print(
            "[ract] retrieval query: indexes exist but contain no rows matching "
            f"'{parsed.query}'. Run 'ract memory init' to (re)build.",
            file=sys.stderr,
        )
        return 0
    if not chunks:
        print(f"[ract] retrieval query: no chunks matched '{parsed.query}'.")
        return 0
    print(
        f"  {len(chunks)} chunk(s); {bundle.total_tokens} tokens "
        f"({bundle.budget_used_pct:.1f}% of {parsed.budget}) at "
        f"cascade level {bundle.query_trace.final_level}"
    )
    for i, chunk in enumerate(chunks, start=1):
        loc = f"{chunk.file_path}"
        if chunk.symbol_name:
            loc += f" :: {chunk.symbol_name}"
        print(f"--- {i}. {loc} ({chunk.language}, {chunk.token_count}t)")
        # Truncate long chunk bodies for terminal readability; JSON
        # output above carries the full body.
        preview = chunk.body or chunk.signature
        if len(preview) > 800:
            preview = preview[:800] + "\n[... truncated; use --json for full body]"
        print(preview)
    if bundle.dropped_symbols:
        print(
            f"  dropped ({bundle.dropped_count}): "
            + ", ".join(bundle.dropped_symbols[:10])
            + ("..." if len(bundle.dropped_symbols) > 10 else "")
        )
    return 0


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
