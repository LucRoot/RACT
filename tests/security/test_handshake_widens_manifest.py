"""HandshakeRegistry widens the manifest for an approved action.

SUBSTRATE §4.3 + module_03 step 6. An approved handshake widens the
manifest within the ``yolo_widen`` bounds; an unapproved handshake
leaves the manifest unchanged.
"""

from __future__ import annotations

from pathlib import Path

from ract.handshake_registry import HandshakeRegistry
from ract.security.manifest import (
    CapabilityManifest,
    FilesystemPolicy,
    NetworkPolicy,
    YoloWiden,
)


def _make_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        run_id="widen-run",
        filesystem=FilesystemPolicy(write=("/workspace/*",)),
        network=NetworkPolicy(
            allow_hosts=("staging.example.com",), deny_default=True
        ),
        yolo_widen=YoloWiden(
            extra_write=("/tmp/build/*",),
            extra_hosts=("cdn.example.com",),
        ),
    )


def test_unapproved_handshake_does_not_widen(tmp_path: Path):
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "risky write", "operator approves")
    base = _make_manifest()
    widened = registry.widen_manifest_for(base, "m1")
    assert widened == base


def test_approved_handshake_widens_within_bounds(tmp_path: Path):
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "risky write", "operator approves")
    registry.update_status("m1", "approved")
    base = _make_manifest()
    widened = registry.widen_manifest_for(base, "m1")
    assert "/tmp/build/*" in widened.filesystem.write
    assert "cdn.example.com" in widened.network.allow_hosts
    # The base allowlist entries are preserved.
    assert "/workspace/*" in widened.filesystem.write
    assert "staging.example.com" in widened.network.allow_hosts


def test_widen_does_not_touch_tiers(tmp_path: Path):
    """An approved handshake cannot lift tier 3 (compile-time hard-off)."""
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "risky", "operator approves")
    registry.update_status("m1", "approved")
    base = _make_manifest()
    widened = registry.widen_manifest_for(base, "m1")
    assert widened.tiers.allow_tier_3 is False


# RACT 0.4.0
