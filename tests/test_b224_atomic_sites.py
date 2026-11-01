"""B-224: no writer of the workspace or of RACT's state uses a fixed
temporary name (the B-212 class). Each site below writes through
``write_atomic`` (a fresh ``mkstemp`` name and one rename), so a link
planted at the target's name or at the old predictable temporary name is
replaced, never written through.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import pytest


def _plant(target: Path, outside: Path) -> None:
    """A link at *target* pointing at *outside* (symlink, hard-link fallback)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(outside)
    except OSError:
        os.link(outside, target)


def _check(target: Path, outside: Path, sentinel: str, read: Callable[[Path], Any], expected: Any) -> None:
    assert outside.read_text(encoding="utf-8") == sentinel
    assert read(target) == expected
    assert not target.is_symlink()


def test_review_hunks_write_replaces_a_planted_link(tmp_path: Path) -> None:
    from ract import review_hunks

    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel" + chr(10), encoding="utf-8")
    target = root / "a.txt"
    # The old predictable temporary name a planted link could wait on.
    planted = root / "a.txt.ract-review"
    try:
        planted.symlink_to(outside)
    except OSError:
        import os

        os.link(outside, planted)

    review_hunks._write(root, "a.txt", b"changed" + bytes([10]))
    assert outside.read_text(encoding="utf-8") == "sentinel" + chr(10)
    assert target.read_text(encoding="utf-8") == "changed" + chr(10)


def test_the_trust_store_replaces_a_planted_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract import trust

    state = tmp_path / "state"
    monkeypatch.setattr("ract.core.keys._default_state_dir", lambda: state)
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel\n", encoding="utf-8")
    target = trust.store_path()
    _plant(target, outside)

    trust._write_store({"deadbeef": "trusted"})
    import json

    _check(
        target,
        outside,
        "sentinel" + chr(10),
        lambda p: json.loads(p.read_text(encoding="utf-8")),
        {"deadbeef": "trusted"},
    )


def test_the_plan_approval_store_replaces_a_planted_link(tmp_path: Path) -> None:
    from ract import plan_approval_store

    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel\n", encoding="utf-8")
    target = plan_approval_store.approvals_path(root, "sess1")
    _plant(target, outside)

    plan_approval_store.remember(root, "sess1", "digest1", [2])
    _check(target, outside, "sentinel\n", lambda p: plan_approval_store.load(root, "sess1"), {"digest1": [2]})


def test_a_sidecar_write_replaces_a_planted_link(tmp_path: Path) -> None:
    import json

    from ract import sidecar_header

    target = tmp_path / "src" / ".calc.py.rootknot.json"
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel\n", encoding="utf-8")
    _plant(target, outside)

    sidecar_header.register_sidecar_type("test/v1", frozenset({1}))
    sidecar_header.write_json_sidecar_with_header(
        target,
        {"artifact_digest": "ab"},
        sidecar_type="test/v1",
        schema_version=1,
        run_id="run1",
    )
    _check(
        target,
        outside,
        "sentinel\n",
        lambda p: json.loads(p.read_text(encoding="utf-8"))["artifact_digest"],
        "ab",
    )


def test_the_guided_policy_write_replaces_a_planted_link(tmp_path: Path) -> None:
    from ract.policy import guided

    target = tmp_path / "policy" / "policy.yaml"
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel\n", encoding="utf-8")
    _plant(target, outside)

    guided._write_whole(target, "grants: []\n")
    _check(
        target,
        outside,
        "sentinel\n",
        lambda p: p.read_text(encoding="utf-8"),
        "grants: []\n",
    )


def test_the_wizard_config_write_replaces_a_planted_link(tmp_path: Path) -> None:
    from ract.setup import wizard

    target = tmp_path / "ract.yaml"
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel\n", encoding="utf-8")
    _plant(target, outside)

    wizard._atomic_write(target, "project:\n  name: demo\n")
    _check(
        target,
        outside,
        "sentinel\n",
        lambda p: p.read_text(encoding="utf-8"),
        "project:\n  name: demo\n",
    )


def test_the_revoked_list_write_replaces_a_planted_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract.policy import grant

    project = tmp_path / "proj"
    policy_dir = project / ".ract"
    policy_dir.mkdir(parents=True)
    (policy_dir / "policy.yaml").write_text("grants: []" + chr(10), encoding="utf-8")
    config_dir = tmp_path / "config"
    monkeypatch.setattr("ract.policy.grant.config_dir", lambda: config_dir)
    outside = tmp_path / "outside.txt"
    # The attacker's revoked list is valid JSON; the write must not
    # follow the planted link and change it.
    outside.write_text('["aaaa"]' + chr(10), encoding="utf-8")
    target = grant._revoked_file(None)
    _plant(target, outside)

    grant.revoke(project)
    assert outside.read_text(encoding="utf-8") == '["aaaa"]' + chr(10)
    assert target.is_file()
    assert not target.is_symlink()
    assert len(grant.revoked(None)) == 2


def test_the_assumptions_snapshot_replaces_a_planted_link(tmp_path: Path) -> None:
    from ract.core.assumptions_wal import AssumptionWal

    wal_dir = tmp_path / "wal"
    wal = AssumptionWal(wal_dir)
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel" + chr(10), encoding="utf-8")
    _plant(wal_dir / "assumptions.json", outside)

    wal.rotate_snapshot(
        [{"id": "a1", "kind": "proposed", "text": "assume x", "confidence": 0.9}]
    )
    assert outside.read_text(encoding="utf-8") == "sentinel" + chr(10)
    target = wal_dir / "assumptions.json"
    assert target.is_file()
    assert not target.is_symlink()
