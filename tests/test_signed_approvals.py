"""B-111 (ADR-0048 R2): an approval written outside a live session needs the operator's signature.

Unsigned approvals are recorded and shown and never unlock anything. The
signature covers the handshake id, the approved digest and an expiry. Every
key here is a throwaway.
"""

from __future__ import annotations

import json
from pathlib import Path

from ract.handshake_registry import HandshakeRegistry, _approval_digest, sign_approval
from ract.policy.operator_key import generate, unlock


def _registry(tmp_path: Path) -> HandshakeRegistry:
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "deploy", "ok")
    return registry


def test_an_unsigned_approval_unlocks_nothing(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.update_status("m1", "approved")
    item = registry.current("m1")
    assert item.status == "approved"  # recorded and shown
    assert registry.approval_state(item) == "unsigned"
    assert not registry.is_approved("m1")
    assert registry.blocks_commit(["m1"]) == ["m1"]


def test_a_signed_approval_unlocks(tmp_path: Path, operator_signer) -> None:
    registry = _registry(tmp_path)
    registry.update_status("m1", "approved", signer=operator_signer)
    assert registry.approval_state(registry.current("m1")) == "signed"
    assert registry.is_approved("m1")
    assert registry.blocks_commit(["m1"]) == []


def test_a_signature_by_another_key_does_not_hold(
    tmp_path: Path, operator_signer
) -> None:
    other_cfg = tmp_path / "other"
    other = generate("another throwaway passphrase", config=other_cfg)
    other_signer = (
        other.key_id,
        unlock("another throwaway passphrase", config=other_cfg),
    )
    registry = _registry(tmp_path / "p")
    registry.update_status("m1", "approved", signer=other_signer)
    assert not registry.is_approved("m1")


def test_an_expired_signature_does_not_hold(
    tmp_path: Path, operator_signer, monkeypatch
) -> None:
    import ract.handshake_registry as hr

    monkeypatch.setattr(hr, "APPROVAL_DAYS", -1)
    registry = _registry(tmp_path)
    registry.update_status("m1", "approved", signer=operator_signer)
    assert not registry.is_approved("m1")


def test_a_signed_record_for_another_item_does_not_hold(
    tmp_path: Path, operator_signer
) -> None:
    registry = _registry(tmp_path)
    registry.update_status("m1", "approved", signer=operator_signer)
    # The item's text changes after the approval (a shipped edit): the digest
    # no longer matches what was signed.
    data = json.loads(registry.registry_path.read_text(encoding="utf-8"))
    data[0]["description"] = "deploy everything"
    registry.registry_path.write_text(json.dumps(data), encoding="utf-8")
    assert not registry.is_approved("m1")


def test_the_record_holds_id_digest_and_expiry(operator_signer) -> None:
    record = sign_approval("m1", "d" * 64, operator_signer)
    assert set(record) == {"format", "id", "digest", "expires", "key_id", "signature"}
    assert record["key_id"] == operator_signer[0]


def test_rejecting_removes_the_signature(tmp_path: Path, operator_signer) -> None:
    registry = _registry(tmp_path)
    registry.update_status("m1", "approved", signer=operator_signer)
    registry.update_status("m1", "rejected")
    assert not registry.is_approved("m1")
    assert registry.approval_state(registry.current("m1")) == "none"
    assert _approval_digest(registry.current("m1"))
