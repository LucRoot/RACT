"""Full-parser help builder for ``ract --help`` (Lens A C1 CRITICAL closure).

v0.5.1 wiring module_10 adds a comprehensive help surface WITHOUT
rewriting the 60-verb argv[0] dispatcher in :func:`ract.cli.main`.
The trade: retain per-verb argparse.ArgumentParser instances (each
verb owns its own subparser today) and add a top-level "discovery"
argparse that enumerates every verb + one-line description via
``add_subparsers()``. When the user types ``ract --help``, ``ract -h``,
or ``ract help``, the discovery parser prints. When they type
``ract help <verb>``, the dispatcher routes to the verb's own
``--help`` output.

Rationale for keeping argv[0] dispatch:

- The dispatcher currently threads ~60 verb handlers, several of
  which lazy-import expensive modules (calibrate, infer, repro-
  manifest, trace, provenance). A full-subparser rewrite would
  either force eager imports (regression) or reproduce every lazy
  import inside the subparser's ``set_defaults(func=...)``
  callback (churn without behavior change).
- Every verb's own ``--help`` output continues to work: the verb
  handlers instantiate their own argparse and dispatch to their
  own subverbs. The audit finding C1 is about DISCOVERABILITY of
  the top-level verbs, not about their internal help.

The verb registry :data:`VERB_DESCRIPTIONS` is the single source of
truth for the one-line help each verb gets in the discovery output;
it is cross-checked against :data:`ract.cli.CLI_VERBS` by
``tests/architecture/test_cli_verb_descriptions_cover_every_verb.py``.

The README verb index generator (Lens A M8 closure) reads the same
dict, so the README table auto-updates on any change here.
"""

from __future__ import annotations

import argparse
from typing import Iterable

# One-line description per verb. Grouped by category for the README
# generator. Order within each group is the display order (matches
# CLI_VERBS ordering where possible).
VERB_DESCRIPTIONS: dict[str, str] = {
    # Core execute + planning
    "run": "Execute an intent as a planned-and-verified RACT run.",
    "plan": "Load, save, replay, diff, or analyse a serialized plan.",
    "session": "List, export, import, backup, or restore saved sessions.",
    "loop": "(alias) Same as run --loop; execute a loop-controlled run.",
    # Discovery / status
    "doctor": "Diagnose RACT installation, config, and workspace state.",
    "status": "Print a one-line summary of the current workspace state.",
    "self-audit": "Audit RACT's own code against the audit lens findings.",
    "audit": "Audit a workspace or run for anti-rot and provenance issues.",
    "leaderboard": "Print the provider leaderboard by success rate.",
    "source-digest": "Print the SHA-256 digest of a source file or workspace.",
    # Init / project setup
    "init": "Initialize a new RACT project from a template.",
    "docs": "Generate or regenerate documentation for the workspace.",
    "openapi": "Generate an OpenAPI client or server scaffold.",
    # Provider / config
    "provider": "List, add, or configure provider adapters and presets.",
    "router": "Inspect or reconfigure the provider router policy.",
    "config": "Inspect or edit ract.yaml keys.",
    "cost": "Report accumulated provider cost from receipts.",
    # Memory / retrieval
    "memory": "Init, apply-narrowings, and inspect memory-discipline indexes.",
    "retrieval": "Search the retrieval adapter; query the three memory indexes.",
    "intent": "Operator-signed intent recompile appending a new suite version.",
    # Handshake / approval
    "handshakes": "List, approve, reject, defer, or review pending handshakes.",
    "operator-queue": "List or drain the operator-approval queue.",
    "whisper": "Add or list free-form legacy operator notes.",
    "auction": "List or resolve entries in the dead-code auction.",
    "fence": "List or resolve Chesterton's fence entries.",
    # Skills / marketplace
    "skills": "List and inspect builtin and installed skills.",
    "marketplace": "(alias) Same as skills marketplace; browse skill packages.",
    "mcp": "Manage and invoke MCP tools registered with RACT.",
    # Refactor / edit
    "refactor": "Run a scoped refactor over a named target.",
    "rename": "Rename a symbol project-wide through the symbol renamer.",
    "diff": "Show and apply RACT-authored diffs against the workspace.",
    "explain": "Explain a plan, step, or artifact with its provenance chain.",
    "consolidate": "Scan for consolidation candidates and propose merges.",
    # Reports
    "report": "Render run reports in markdown or HTML.",
    "trace": "Inspect a run's events.jsonl trace file.",
    # Quality / anti-lazy
    "quality": "Compute the plan quality scorecard.",
    "load-bearing": "Inspect or manage load-bearing annotations across the workspace.",
    "novelty": "Report novelty budget usage and scan for overruns.",
    "coverage": "Report coverage deltas and status.",
    "mutation": "Run mutation-testing checks over the workspace.",
    "conformance": "Run the provider conformance suite.",
    "rot-report": "Print the anti-rot report.",
    "rot": "Detect and quarantine rot in the workspace.",
    "merge-gate": "Evaluate the mutation-testing merge gate.",
    # Provenance / receipts
    "provenance": "Verify Rootknot signatures for artifacts and workspaces.",
    "receipt": "List, show, or verify receipts.",
    "receipt-export": "Export receipts to disk or upload to a signed archive.",
    "manifest": "Repro-manifest alias + ledger verify/inspect/show/proof.",
    "repro-manifest": "Produce a reproducibility manifest for a run.",
    "policy-gate": "Evaluate a run against the configured policy.",
    "run-fingerprint": "Print or diff a run's fingerprint.",
    "ai-sbom": "Emit an AI Software Bill of Materials.",
    # Release / experimental
    "release": "List, create, or update GitHub releases.",
    "calibrate": "Run provider calibration (experimental).",
    "infer": "Run a single inference call (experimental).",
}


def build_discovery_parser(cli_verbs: Iterable[str]) -> argparse.ArgumentParser:
    """Return a top-level parser that enumerates every verb in ``--help``.

    The returned parser is used ONLY for its ``--help`` output; the
    real dispatch stays in :func:`ract.cli.main`. Every verb listed
    in ``cli_verbs`` gets an ``add_parser()`` call with the
    :data:`VERB_DESCRIPTIONS` one-liner as ``help=``. Unknown verbs
    (present in ``cli_verbs`` but missing from
    :data:`VERB_DESCRIPTIONS`) fall back to a placeholder description
    so ``--help`` never omits a verb the dispatcher can route to.
    """
    parser = argparse.ArgumentParser(
        prog="ract",
        description=(
            "RACT - an Agentic Coding Tool by Dr. Lucas Root, Ph.D. "
            "Forged on Windows, loved everywhere."
        ),
        epilog=(
            "Examples:\n"
            "  ract \"add a test for utils.py\" --config ract.yaml\n"
            "  ract run \"refactor the parser\" --loop --max-iterations 5\n"
            "  ract memory init\n"
            "  ract retrieval query \"parser\"\n"
            "  ract manifest ledger verify\n"
            "  ract help <verb>   # per-verb help\n"
            "\n"
            "See docs/QUICKSTART.md and docs/USE_CASES.jsonl for full details.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(
        dest="verb",
        metavar="VERB",
        title="verbs",
        description="RACT subcommands. Run 'ract help <verb>' for verb-level help.",
    )
    for verb in cli_verbs:
        desc = VERB_DESCRIPTIONS.get(verb, f"({verb} verb -- see 'ract help {verb}')")
        # Keep help short: argparse truncates in the two-column layout.
        sub.add_parser(verb, help=desc, add_help=False)
    # Top-level flags shown by every ract --help.
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the RACT version and exit.",
    )
    parser.add_argument(
        "--about",
        action="store_true",
        help="Print the RACT manifesto, authorship, and license summary.",
    )
    parser.add_argument(
        "--welcome",
        action="store_true",
        help="Print the RACT welcome letter and exit.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run RACT's internal test suite and report the result.",
    )
    parser.add_argument(
        "--init-provider",
        dest="init_provider",
        help="Write a starter ract.yaml for the named provider and exit.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON for commands that support it.",
    )
    return parser


def print_discovery_help(cli_verbs: Iterable[str]) -> None:
    """Print the discovery help output. Called on ``ract --help`` / ``ract -h``."""
    build_discovery_parser(cli_verbs).print_help()


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A C1)
