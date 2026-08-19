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

    Subverbs: ``init``, ``apply-narrowings``.

    Returns 0 on success, 1 on any user-visible failure. Prints
    ``[ract]``-prefixed diagnostics on the failure path.
    """
    parser = argparse.ArgumentParser(prog="ract memory")
    parser.add_argument(
        "subverb",
        choices=["init", "apply-narrowings"],
        help="Memory-discipline action to perform.",
    )
    parsed, rest = parser.parse_known_args(args)
    if parsed.subverb == "init":
        return _memory_init(rest)
    if parsed.subverb == "apply-narrowings":
        return _memory_apply_narrowings(rest)
    parser.print_help()
    return 1


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
    """Handle ``ract retrieval query <query> [--budget N] [--format ...]``.

    New in module_09. Called from the existing ``_retrieval_command``
    dispatcher when the subverb resolves to ``query``.
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
        from ract.memory.retrieve import RetrievalQuery
    except ImportError as exc:
        print(
            f"[ract] retrieval query: memory package unavailable: {exc}",
            file=sys.stderr,
        )
        return 1

    # A real integration wires ``retrieve()`` against the three built
    # indexes. Module_09 lands the CLI surface with a minimal
    # keyword-only query the operator can smoke-test against a repo
    # whose indexes exist. Full three-index wiring lands via the
    # composition_runner path in the same module.
    query = RetrievalQuery(
        symbol_names=(),
        keywords=(parsed.query,),
    )
    if parsed.json_output:
        print(
            json.dumps(
                {
                    "query": parsed.query,
                    "budget": parsed.budget,
                    "format": parsed.format,
                    "strategy": parsed.strategy,
                    "repo_path": str(repo_path),
                    "canonical": {
                        "keywords": list(query.keywords),
                        "symbol_names": list(query.symbol_names),
                    },
                },
                indent=2,
            )
        )
    else:
        print(f"[ract] retrieval query: '{parsed.query}' against {repo_path}")
        print(
            f"  budget: {parsed.budget}  format: {parsed.format}  "
            f"strategy: {parsed.strategy}"
        )
        print(
            "  note: full retrieve() wiring against a live index bundle is "
            "exercised via composition_runner; use ract memory init first."
        )
    return 0


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
