"""B-082: a shipped handshake with the same id cannot stall or stand in for the real one.

A cloned repository can ship `.ract/handshakes.json` with an item whose id
RACT will use later. Before, `update_status` changed the first item with
the id, so a shipped item ahead of the real pending one took the approval
and the real one stayed pending, blocking its step. Every decision now
reads the item this machine created (it carries a request mark in the user
state directory); a shipped copy is ignored for it.
"""

from __future__ import annotations

import json
from pathlib import Path

from ract.core.compile import IntentCompiler
from ract.handshake_registry import HandshakeRegistry
from ract.security.manifest import (
    CapabilityManifest,
    FilesystemPolicy,
    NetworkPolicy,
    YoloWiden,
)


def _manifest() -> CapabilityManifest:
    return CapabilityManifest(
        run_id="b082",
        filesystem=FilesystemPolicy(write=("/workspace/*",)),
        network=NetworkPolicy(allow_hosts=("staging.example.com",), deny_default=True),
        yolo_widen=YoloWiden(extra_write=("/tmp/build/*",)),
    )


def _ship(project: Path, status: str, item_id: str = "m1") -> None:
    (project / ".ract").mkdir(parents=True, exist_ok=True)
    (project / ".ract" / "handshakes.json").write_text(
        json.dumps(
            [
                {
                    "id": item_id,
                    "description": "shipped",
                    "acceptance": "shipped",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "status": status,
                }
            ]
        ),
        encoding="utf-8",
    )


def test_the_approval_reaches_the_item_this_machine_created(tmp_path: Path) -> None:
    _ship(tmp_path, "pending")
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "risky write", "operator approves")

    registry.update_status("m1", "approved")

    assert registry.blocks_commit(["m1"]) == []
    widened = registry.widen_manifest_for(_manifest(), "m1")
    assert "/tmp/build/*" in widened.filesystem.write


def test_a_shipped_approved_copy_does_not_unblock_the_real_pending_item(
    tmp_path: Path,
) -> None:
    _ship(tmp_path, "approved")
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "risky write", "operator approves")

    assert registry.blocks_commit(["m1"]) == ["m1"]
    assert registry.widen_manifest_for(_manifest(), "m1") == _manifest()


def test_a_shipped_pending_copy_does_not_keep_an_approved_step_blocked(
    tmp_path: Path,
) -> None:
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "risky write", "operator approves")
    registry.update_status("m1", "approved")
    # A later checkout puts a shipped pending copy ahead of it.
    path = tmp_path / ".ract" / "handshakes.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    shipped = {
        "id": "m1",
        "description": "shipped",
        "acceptance": "shipped",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "status": "pending",
    }
    path.write_text(json.dumps([shipped, *items]), encoding="utf-8")

    assert registry.blocks_commit(["m1"]) == []


def test_a_shipped_approved_group_does_not_approve_compiled_predicates(
    tmp_path: Path,
) -> None:
    group = IntentCompiler._group_id("invariant")
    _ship(tmp_path, "approved", item_id=group)

    assert not IntentCompiler._group_is_approved(
        HandshakeRegistry(tmp_path), "invariant"
    )


def test_a_group_the_operator_approved_here_is_approved(tmp_path: Path) -> None:
    group = IntentCompiler._group_id("invariant")
    registry = HandshakeRegistry(tmp_path)
    registry.add(group, "new invariants", "operator approves")
    registry.update_status(group, "approved")

    assert IntentCompiler._group_is_approved(registry, "invariant")
