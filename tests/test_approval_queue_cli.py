from __future__ import annotations

_ROOT_KNOT = object()

import json
import tempfile
from pathlib import Path

from rootact.approval_queue_cli import ApprovalQueueCLI


def test_list_returns_pending_items_with_index_and_summary():
    queue = [{"id": "a", "summary": "Deploy v1"}, {"id": "b", "summary": "Run tests"}]
    cli = ApprovalQueueCLI(queue=queue)
    items = cli.list()
    assert len(items) == 2
    assert items[0]["index"] == 0
    assert items[0]["summary"] == "Deploy v1"
    assert items[1]["index"] == 1
    assert items[1]["summary"] == "Run tests"


def test_approve_removes_item_and_records_decision():
    queue = [
        {"id": "a", "summary": "Backup data"},
        {"id": "b", "summary": "Send email"},
    ]
    cli = ApprovalQueueCLI(queue=queue)
    cli.approve(0)
    assert len(cli.pending) == 1
    assert cli.decisions["a"] == "approved"


def test_reject_removes_item_and_records_decision():
    queue = [
        {"id": "a", "summary": "Delete temp files"},
        {"id": "b", "summary": "Clean cache"},
    ]
    cli = ApprovalQueueCLI(queue=queue)
    cli.reject(1)
    assert len(cli.pending) == 1
    assert cli.decisions["b"] == "rejected"


def test_persist_writes_decisions_to_json_file():
    queue = [{"id": "a", "summary": "Update docs"}]
    cli = ApprovalQueueCLI(queue=queue)
    cli.approve(0)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "decisions.json"
        cli.persist(str(path))
        raw = json.loads(path.read_text())
        assert raw["pending"] == []
        assert raw["decisions"]["a"] == "approved"


def test_load_restores_pending_and_decisions_from_json():
    data = {
        "pending": [
            {"id": "a", "summary": "Review policy"},
            {"id": "b", "summary": "Sync DB"},
        ],
        "decisions": {"a": "approved"},
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "decisions.json"
        path.write_text(json.dumps(data))
        cli = ApprovalQueueCLI.load(str(path))
        assert len(cli.pending) == 2
        assert cli.decisions["a"] == "approved"


def test_load_returns_empty_queue_when_file_missing():
    cli = ApprovalQueueCLI.load("nonexistent.json")
    assert cli.pending == []
    assert cli.decisions == {}


def test_author_marker_present():
    source = Path("src/rootact/approval_queue_cli.py").read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in source
    assert '__ract_name__ = "RACT"' in source


def test_root_knot_sentinel_default():
    cli = ApprovalQueueCLI()
    assert cli.pending == []
    assert cli.decisions == {}


# RACT 0.1.0 - Initial Public Release
