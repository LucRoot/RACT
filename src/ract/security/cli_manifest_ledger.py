"""CLI verbs for the historical Manifest Ledger (Lens A M1 closure).

v0.5.1 wiring module_10 adds an operator-facing CLI surface over
:class:`ract.security.manifest_ledger.ManifestLedger`. Prior state
(audited): the ledger library shipped in v0.5.1 module_07 with
~1200 lines of append + verify + Merkle-proof machinery, but had
NO CLI verb -- an operator wanting to run ``verify_chain``,
``iter_entries``, or ``proof_of`` had to write Python.

This module lands four subverbs under ``ract manifest ledger``:

- ``verify [--json]`` -- run :meth:`ManifestLedger.verify_chain` and
  print ``valid=True|False`` plus ``first_break_at`` on breaks.
- ``inspect [--start N] [--limit K] [--json]`` -- list entries in
  append order with the mandatory schema fields.
- ``show <entry-index> [--json]`` -- print one entry's full payload.
- ``proof <entry-index> [--json]`` -- emit the Merkle proof for an
  entry so an offline verifier can confirm inclusion.

Every verb accepts ``--root`` for the workspace state directory
(default: ``.ract/``). USE_CASES.jsonl carries an accepted entry
per subverb (mounted under the ``manifest`` verb since the
``ract manifest ledger ...`` dispatch coexists with the existing
``ract manifest`` repro-manifest alias).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def manifest_ledger_command(args: list[str]) -> int:
    """Handle ``ract manifest ledger {verify,inspect,show,proof}``."""
    parser = argparse.ArgumentParser(prog="ract manifest ledger")
    # v0.5.1 wiring module_10 (Lens A M7): bare ``ract manifest ledger``
    # prints help and exits 0.
    if not args:
        parser.print_help()
        _print_ledger_help_epilog()
        return 0
    sub = parser.add_subparsers(dest="action", required=True, metavar="ACTION")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root",
        type=Path,
        default=Path(".ract"),
        help=(
            "Workspace state directory containing manifest_ledger.jsonl "
            "(default: .ract)."
        ),
    )
    common.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    verify_p = sub.add_parser(
        "verify",
        parents=[common],
        help="Run verify_chain and print valid/broken-at.",
    )
    inspect_p = sub.add_parser(
        "inspect",
        parents=[common],
        help="List ledger entries in append order.",
    )
    inspect_p.add_argument(
        "--start",
        type=int,
        default=0,
        help="Zero-based index of the first entry to list (default: 0).",
    )
    inspect_p.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of entries to list (default: 20).",
    )
    show_p = sub.add_parser(
        "show",
        parents=[common],
        help="Print one entry's full payload.",
    )
    show_p.add_argument("entry_index", type=int, help="Zero-based entry index.")
    proof_p = sub.add_parser(
        "proof",
        parents=[common],
        help="Emit the Merkle proof for an entry.",
    )
    proof_p.add_argument("entry_index", type=int, help="Zero-based entry index.")

    parsed = parser.parse_args(args)

    try:
        from ract.security.manifest_ledger import (
            LedgerCorruptError,
            ManifestLedger,
        )
    except ImportError as exc:
        print(f"[ract] manifest ledger: unavailable: {exc}", file=sys.stderr)
        return 1

    root = parsed.root.resolve()
    ledger = ManifestLedger(root)

    if parsed.action == "verify":
        return _verify(ledger, parsed.json_output)
    if parsed.action == "inspect":
        return _inspect(ledger, parsed.start, parsed.limit, parsed.json_output)
    if parsed.action == "show":
        return _show(ledger, parsed.entry_index, parsed.json_output)
    if parsed.action == "proof":
        return _proof(ledger, parsed.entry_index, parsed.json_output)
    parser.print_help()
    return 0


def _verify(ledger, json_output: bool) -> int:
    from ract.security.manifest_ledger import LedgerCorruptError

    try:
        result = ledger.verify_chain()
    except LedgerCorruptError as exc:
        if json_output:
            print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        else:
            print(f"[ract] manifest ledger verify: corrupt: {exc}", file=sys.stderr)
        return 1
    payload = {
        "valid": result.valid,
        "first_break_at": result.first_break_at,
        "tail_valid_count": result.tail_valid_count,
        "ledger_path": str(ledger.ledger_path),
    }
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        status = "valid" if result.valid else "BROKEN"
        print(f"[ract] manifest ledger verify: {status}")
        print(f"  entries verified: {result.tail_valid_count}")
        print(f"  ledger path: {ledger.ledger_path}")
        if not result.valid:
            print(f"  first_break_at: {result.first_break_at}", file=sys.stderr)
    return 0 if result.valid else 1


def _inspect(ledger, start: int, limit: int, json_output: bool) -> int:
    from ract.security.manifest_ledger import LedgerCorruptError

    try:
        entries = ledger.load()
    except LedgerCorruptError as exc:
        print(f"[ract] manifest ledger inspect: corrupt: {exc}", file=sys.stderr)
        return 1
    if start < 0 or start > len(entries):
        print(
            f"[ract] manifest ledger inspect: --start {start} out of range "
            f"(ledger has {len(entries)} entries)",
            file=sys.stderr,
        )
        return 1
    slice_ = entries[start : start + limit]
    if json_output:
        print(
            json.dumps(
                {
                    "ledger_path": str(ledger.ledger_path),
                    "total_entries": len(entries),
                    "start": start,
                    "limit": limit,
                    "entries": [
                        {
                            "index": start + i,
                            "timestamp": e.get("timestamp"),
                            "manifest_digest": e.get("manifest_digest"),
                            "rootknot_run_id": e.get("rootknot_run_id"),
                            "entry_index_stamped": e.get("entry_index"),
                        }
                        for i, e in enumerate(slice_)
                    ],
                },
                indent=2,
            )
        )
        return 0
    if not entries:
        print(f"[ract] manifest ledger inspect: no entries at {ledger.ledger_path}")
        return 0
    print(f"[ract] manifest ledger inspect: {len(entries)} entries total")
    print(f"  showing {start}..{start + len(slice_) - 1}")
    for i, e in enumerate(slice_):
        idx = start + i
        ts = e.get("timestamp", "?")
        md = e.get("manifest_digest", "?")
        run = e.get("rootknot_run_id", "?")
        print(f"  [{idx:5d}] {ts}  manifest={md[:16]}...  run={run[:16]}...")
    return 0


def _show(ledger, entry_index: int, json_output: bool) -> int:
    entries = ledger.load()
    if entry_index < 0 or entry_index >= len(entries):
        print(
            f"[ract] manifest ledger show: entry_index {entry_index} out of range "
            f"(ledger has {len(entries)} entries)",
            file=sys.stderr,
        )
        return 1
    entry = entries[entry_index]
    if json_output:
        print(json.dumps(entry, indent=2, default=str))
    else:
        print(f"[ract] manifest ledger show: entry {entry_index}")
        for k, v in entry.items():
            display = str(v)
            if len(display) > 200:
                display = display[:200] + "..."
            print(f"  {k}: {display}")
    return 0


def _proof(ledger, entry_index: int, json_output: bool) -> int:
    try:
        proof = ledger.proof_of(entry_index)
    except IndexError as exc:
        print(f"[ract] manifest ledger proof: {exc}", file=sys.stderr)
        return 1
    payload = {
        "target_index": proof.target_index,
        "target_hash": proof.target_hash,
        "tail_hash": proof.tail_hash,
        "forward_hashes": list(proof.forward_hashes),
        "target_entry": proof.target_entry,
    }
    if json_output:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(
            f"[ract] manifest ledger proof: entry {proof.target_index} "
            f"(target_hash={proof.target_hash[:16]}..., "
            f"tail_hash={proof.tail_hash[:16]}...)"
        )
        print(f"  forward_hashes: {len(proof.forward_hashes)} link(s)")
        for i, h in enumerate(proof.forward_hashes):
            print(f"    {i}: {h}")
    return 0


def _print_ledger_help_epilog() -> None:
    print()
    print("subverbs:")
    print("  verify         run verify_chain; print valid/broken-at")
    print("  inspect        list entries in append order (--start / --limit)")
    print("  show <index>   print one entry's full payload")
    print("  proof <index>  emit the Merkle proof for an entry")
    print()
    print("See 'ract manifest ledger <subverb> --help' for per-subverb flags.")


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A M1)
