"""v0.5.2 hardening module_06 -- SP amendments (Ox Alpha).

Ox Alpha SP DEFECTS folded:

- Q1 (HANDSHAKE version-triple mismatch): fixed in HANDSHAKE
  doc; not exercised by tests.
- Q2 (--notes-file placeholder; origin assumption): fixed in
  HANDSHAKE doc; not exercised by tests.
- Q3 (five vs six hardening modules + missing new-hash literal):
  fixed in HANDSHAKE + CHANGELOG; not exercised by tests.
- Q5 (IndexConsistencyReport shape):
  (a) checks_skipped field added to the frozen dataclass.
  (b) max_inconsistencies<1 refused at both API and CLI
      boundaries.
  (c) sweep-infrastructure failures now surface as new
      ``check_error`` kind (not the misnamed ``orphan_edge``).
- Q8 (provenance_cli handles RootknotUnknownSidecarFormat with
  a sharp diagnostic).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.memory.symbol_index import SymbolIndex, SymbolRow
from ract.memory.verify_consistency import (
    IndexConsistencyReport,
    IndexInconsistency,
    verify_indexes,
)


def _sym(**kw) -> SymbolRow:
    defaults = dict(
        id=None,
        name="",
        kind="function",
        file_path="",
        start_line=None,
        end_line=None,
        signature="",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash=None,
        token_count=None,
        updated_at=None,
    )
    defaults.update(kw)
    return SymbolRow(**defaults)


# ---------------------------------------------------------------------------
# Q5a: checks_skipped field
# ---------------------------------------------------------------------------


class TestChecksSkippedField:
    def test_report_has_checks_skipped_field(self) -> None:
        r = IndexConsistencyReport.consistent(symbols_checked=5)
        assert hasattr(r, "checks_skipped")
        assert r.checks_skipped == ()

    def test_disk_check_disabled_recorded(self, tmp_path: Path) -> None:
        with SymbolIndex() as sym:
            r = verify_indexes(
                symbol_index=sym, check_files_on_disk=False
            )
            assert "disk-existence" in r.checks_skipped

    def test_graph_missing_recorded(self) -> None:
        with SymbolIndex() as sym:
            r = verify_indexes(
                symbol_index=sym,
                graph_index=None,
                check_files_on_disk=False,
            )
            assert "graph_index_not_attached" in r.checks_skipped

    def test_semantic_missing_recorded(self) -> None:
        with SymbolIndex() as sym:
            r = verify_indexes(
                symbol_index=sym,
                semantic_index=None,
                check_files_on_disk=False,
            )
            assert "semantic_index_not_attached" in r.checks_skipped

    def test_partial_sweep_consistent_reason_names_skipped(
        self,
    ) -> None:
        with SymbolIndex() as sym:
            r = verify_indexes(
                symbol_index=sym, check_files_on_disk=False
            )
            assert r.status == "CONSISTENT"
            # Reason must acknowledge the partial sweep.
            assert "checks skipped" in r.reason
            assert "disk-existence" in r.reason


# ---------------------------------------------------------------------------
# Q5b: max_inconsistencies < 1 refused
# ---------------------------------------------------------------------------


class TestMaxInconsistenciesRefused:
    def test_zero_refused(self) -> None:
        with SymbolIndex() as sym, pytest.raises(
            ValueError, match=r"max_inconsistencies must be >= 1"
        ):
            verify_indexes(
                symbol_index=sym,
                check_files_on_disk=False,
                max_inconsistencies=0,
            )

    def test_negative_refused(self) -> None:
        with SymbolIndex() as sym, pytest.raises(
            ValueError, match=r"max_inconsistencies must be >= 1"
        ):
            verify_indexes(
                symbol_index=sym,
                check_files_on_disk=False,
                max_inconsistencies=-5,
            )

    def test_cli_negative_refused(
        self, tmp_path: Path, capsys
    ) -> None:
        from ract.memory.cli_memory import memory_command

        # argparse-driven refusal.
        with pytest.raises(SystemExit):
            memory_command(
                [
                    "verify-consistency",
                    str(tmp_path),
                    "--max-inconsistencies",
                    "0",
                ]
            )


# ---------------------------------------------------------------------------
# Q5c: check_error kind
# ---------------------------------------------------------------------------


class TestCheckErrorKind:
    def test_check_error_kind_legal(self) -> None:
        # Constructing an inconsistency with kind=check_error must
        # not raise.
        i = IndexInconsistency(
            kind="check_error",
            file=None,
            symbol_id=None,
            edge_id=None,
            detail="graph sweep raised: RuntimeError('synthetic')",
        )
        assert i.kind == "check_error"


# ---------------------------------------------------------------------------
# Q8: provenance_cli handles unknown sidecar format
# ---------------------------------------------------------------------------


class TestProvenanceCliUnknownSidecar:
    def test_unknown_sidecar_yields_sharp_diagnostic(
        self, tmp_path: Path
    ) -> None:
        """Write an artifact + sidecar with an unknown schema
        literal; verify_artifact must surface a sharp
        unknown-schema diagnostic rather than the generic
        'sidecar unparseable'.
        """
        import json

        from ract.provenance_cli import verify_artifact

        artifact = tmp_path / "artifact.txt"
        artifact.write_text("dummy content\n", encoding="utf-8")
        sidecar = tmp_path / ".artifact.txt.rootknot.json"
        sidecar.write_text(
            json.dumps(
                {
                    "schema": "sidecar/v9",
                    "plan_id": "00" * 32,
                    "step_id": "00" * 32,
                    "assumption_digest": "00" * 32,
                    "generator": {
                        "model_name": "m",
                        "model_version": "v",
                        "session_id": "00" * 32,
                        "public_key_id": "00" * 32,
                    },
                    "parent_digests": [],
                    "workspace_path": "/tmp/x",
                    "artifact_digest": "00" * 32,
                    "created_at_ns": 1,
                    "signature": "00" * 32,
                }
            ),
            encoding="utf-8",
        )
        ok, msg = verify_artifact(artifact)
        assert ok is False
        assert "unknown sidecar schema" in msg
        assert "sidecar/v9" in msg
