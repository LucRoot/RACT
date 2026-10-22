"""S-028b: every other reader of a file a repository can ship stays inside
the workspace.

Found while reviewing the readers of `.ract/` after S-028: session
rollback snapshots, consolidation handshakes and backups, and imported
session exports each turned a value from a workspace file into a path
with no containment. All four were in v0.5.2.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.consolidate import ConsolidationApplier, MergeProposal
from ract.session_rollback import SessionRollback
from ract.session_store import SessionStore
from tests.test_headless import _ract


def _outside_untouched(tmp_path: Path, before: set[str]) -> None:
    assert {p.name for p in tmp_path.iterdir()} == before


def test_a_shipped_rollback_snapshot_cannot_write_outside(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    before = {p.name for p in tmp_path.iterdir()}
    snapshots = ws / ".ract" / "snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "demo.json").write_text(
        json.dumps(
            {
                "created_at": "x",
                "files": {"../payload.txt": "attacker\n", "ok.txt": "restored\n"},
            }
        ),
        encoding="utf-8",
    )

    restored, missing = SessionRollback(ws).restore("demo")

    _outside_untouched(tmp_path, before)
    assert restored == ["ok.txt"] and "../payload.txt" in missing


def test_a_shipped_handshake_cannot_make_consolidate_write_outside(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "a.py").write_text("x = 1\n", encoding="utf-8")
    victim = tmp_path / "victim.py"
    victim.write_text("keep = True\n", encoding="utf-8")
    proposal = MergeProposal(
        target="a.py", sources=("../victim.py",), diff="", reason="r", safe=True
    )

    result = ConsolidationApplier(ws).apply(proposal, "p1")

    assert victim.read_text(encoding="utf-8") == "keep = True\n"
    assert result.error and "outside the workspace" in result.error


def test_a_shipped_consolidation_backup_cannot_restore_outside(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    backups = ws / ".ract" / "consolidate_backups" / "p1"
    backups.mkdir(parents=True)
    (backups / "..__payload.txt").write_text("attacker\n", encoding="utf-8")
    (backups / "ok.py").write_text("restored\n", encoding="utf-8")
    before = {p.name for p in tmp_path.iterdir()}

    result = ConsolidationApplier(ws).rollback("p1")

    _outside_untouched(tmp_path, before)
    assert (ws / "ok.py").read_text(encoding="utf-8") == "restored\n"
    assert result.error and "../payload.txt" in result.error


@pytest.mark.parametrize(
    "bad", ["../escape", "a/b", "..", ".hidden", "", "C:x", "a\\b"]
)
def test_session_and_proposal_ids_are_names_not_paths(tmp_path: Path, bad: str) -> None:
    store = SessionStore(tmp_path / "sessions")
    with pytest.raises(ValueError):
        store.save(bad, {"intent": "x"})
    with pytest.raises(ValueError):
        SessionRollback(tmp_path).restore(bad)
    with pytest.raises(ValueError):
        ConsolidationApplier(tmp_path).rollback(bad)


def test_importing_a_hostile_session_export_writes_nothing_outside(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "ract.yaml").write_text("providers: {}\n", encoding="utf-8")
    export = tmp_path / "export.json"
    export.write_text(
        # The store is <ws>/.ract_sessions, so this lands in tmp_path.
        json.dumps({"session_id": "../../escaped", "state": {"intent": "x"}}),
        encoding="utf-8",
    )
    before = {p.name for p in tmp_path.iterdir()}

    result = _ract(ws, "session", "import", "--input", str(export))

    assert result.returncode != 0
    _outside_untouched(tmp_path, before)
    assert "not a valid session id" in result.stderr
