"""``ract manifest ledger {verify,inspect,show,proof}`` (Lens A M1 closure).

v0.5.1 wiring module_10 adds a CLI surface over :class:`ManifestLedger`.
Prior state: the library shipped in v0.5.1 module_07 with no operator-
facing verb.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest


def _run(argv: list[str]) -> tuple[int, str, str]:
    from ract.security.cli_manifest_ledger import manifest_ledger_command

    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = manifest_ledger_command(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def _seeded_ledger(tmp_path: Path, n: int = 3) -> Path:
    """Return a workspace-state root with ``n`` legitimate ledger entries."""
    from ract.security.manifest_ledger import ManifestLedger

    root = tmp_path / ".ract"
    root.mkdir()
    ledger = ManifestLedger(root)
    for i in range(n):
        payload = b'{"schema":"manifest/v1","seq":' + str(i).encode() + b"}"
        digest_hex = ledger.store_snapshot(payload)
        ledger.append(
            manifest_digest=digest_hex,
            rootknot_signature=b"\x00" * 64,
            rootknot_run_id="run-" + f"{i:028d}",
            tool_trace_summary={
                "tool_ids_invoked": [],
                "invocation_count": i,
                "first_ns": 0,
                "last_ns": 0,
            },
            first_wal_seq=0,
            last_wal_seq=0,
        )
    return root


def test_verify_reports_valid_on_untouched_ledger(tmp_path: Path) -> None:
    root = _seeded_ledger(tmp_path, n=3)
    code, out, err = _run(["verify", "--root", str(root)])
    assert code == 0, err
    assert "valid" in out.lower()


def test_verify_json_shape(tmp_path: Path) -> None:
    root = _seeded_ledger(tmp_path, n=2)
    code, out, err = _run(["verify", "--root", str(root), "--json"])
    assert code == 0, err
    payload = json.loads(out)
    assert payload["valid"] is True
    assert payload["tail_valid_count"] == 2
    assert payload["first_break_at"] is None


def test_inspect_lists_entries(tmp_path: Path) -> None:
    root = _seeded_ledger(tmp_path, n=3)
    code, out, err = _run(["inspect", "--root", str(root)])
    assert code == 0, err
    assert "3 entries" in out


def test_inspect_json_shape(tmp_path: Path) -> None:
    root = _seeded_ledger(tmp_path, n=3)
    code, out, err = _run(["inspect", "--root", str(root), "--json", "--limit", "2"])
    assert code == 0, err
    payload = json.loads(out)
    assert payload["total_entries"] == 3
    assert len(payload["entries"]) == 2


def test_show_prints_one_entry_payload(tmp_path: Path) -> None:
    root = _seeded_ledger(tmp_path, n=2)
    code, out, err = _run(["show", "0", "--root", str(root), "--json"])
    assert code == 0, err
    entry = json.loads(out)
    assert entry["rootknot_run_id"] == "run-" + f"{0:028d}"
    assert "manifest_digest" in entry


def test_show_out_of_range_returns_exit_1(tmp_path: Path) -> None:
    root = _seeded_ledger(tmp_path, n=2)
    code, out, err = _run(["show", "99", "--root", str(root)])
    assert code == 1
    assert "out of range" in err


def test_proof_emits_valid_shape(tmp_path: Path) -> None:
    root = _seeded_ledger(tmp_path, n=4)
    code, out, err = _run(["proof", "1", "--root", str(root), "--json"])
    assert code == 0, err
    proof = json.loads(out)
    assert proof["target_index"] == 1
    assert isinstance(proof["forward_hashes"], list)
    # Proof for entry 1 of a 4-entry ledger has 2 forward hashes.
    assert len(proof["forward_hashes"]) == 2


def test_bare_manifest_ledger_prints_help_exit_zero(tmp_path: Path) -> None:
    """Empty argv triggers help + exit 0 (Lens A M7)."""
    code, out, err = _run([])
    assert code == 0
    assert "subverbs" in out or "usage" in out.lower()


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A M1 regression)
