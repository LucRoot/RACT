"""Manifest schema, validator, and digest tests.

Pure Pydantic + hashlib; runs on every platform.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ract.security.manifest import (
    CapabilityManifest,
    FilesystemPolicy,
    ManifestDigest,
    ManifestValidator,
    NetworkPolicy,
    SyscallPolicy,
    TierPolicy,
    YoloWiden,
    load_manifest_from_yaml,
)


def _minimal_manifest(**overrides) -> CapabilityManifest:
    """Build a valid manifest, allowing per-test overrides of any field."""
    data = dict(run_id="run-1", **overrides)
    return CapabilityManifest(**data)


def test_manifest_defaults_are_deny_default_network():
    m = _minimal_manifest()
    assert m.network.deny_default is True
    assert m.network.allow_hosts == ()


def test_manifest_refuses_deny_default_false():
    with pytest.raises(ValidationError):
        NetworkPolicy(deny_default=False)


def test_manifest_refuses_extra_fields():
    with pytest.raises(ValidationError):
        CapabilityManifest(run_id="r", unknown_field=42)


def test_manifest_refuses_unknown_version():
    with pytest.raises(ValidationError):
        CapabilityManifest(run_id="r", version=99)


def test_validator_flags_tier_3_compile_time_denied():
    m = _minimal_manifest(tiers=TierPolicy(default=1, allow_tier_3=True))
    violations = ManifestValidator.validate(m)
    codes = {v.code for v in violations}
    assert "tier_3_compile_time_denied" in codes


def test_yolo_does_not_lift_tier_3():
    """--yolo widens filesystem/network only; tier 3 remains denied.

    The manifest's yolo_widen carries extra_read / extra_write / extra_hosts —
    it has no field that could re-enable tier 3. Even a manifest that sets
    allow_tier_3=True is refused by the validator because the compile-time
    constant is False.
    """
    m = _minimal_manifest(
        tiers=TierPolicy(default=1, allow_tier_3=True),
        yolo_widen=YoloWiden(
            extra_write=("/workspace/scratch",),
            extra_hosts=("example.com",),
        ),
    )
    violations = ManifestValidator.validate(m)
    assert any(v.code == "tier_3_compile_time_denied" for v in violations)


def test_validator_flags_write_denied_overlap():
    m = _minimal_manifest(
        filesystem=FilesystemPolicy(
            write=("/workspace/foo",),
            denied=("/workspace/foo",),
        ),
    )
    violations = ManifestValidator.validate(m)
    assert any(v.code == "filesystem_write_denied_overlap" for v in violations)


def test_validator_flags_yolo_widen_conflicts_with_denied():
    m = _minimal_manifest(
        filesystem=FilesystemPolicy(denied=("/etc/passwd",)),
        yolo_widen=YoloWiden(extra_write=("/etc/passwd",)),
    )
    violations = ManifestValidator.validate(m)
    assert any(v.code == "yolo_widen_conflicts_with_denied" for v in violations)


def test_validator_passes_on_minimal_manifest():
    m = _minimal_manifest()
    assert ManifestValidator.validate(m) == []


def test_digest_is_stable_across_field_order():
    """Canonical JSON serialization means field order does not change the digest."""
    a = CapabilityManifest(
        run_id="r",
        filesystem=FilesystemPolicy(read=("/a", "/b")),
        syscalls=SyscallPolicy(seccomp_profile="strict"),
    )
    b = CapabilityManifest(
        syscalls=SyscallPolicy(seccomp_profile="strict"),
        filesystem=FilesystemPolicy(read=("/a", "/b")),
        run_id="r",
    )
    assert ManifestDigest.of(a) == ManifestDigest.of(b)


def test_digest_changes_on_content_change():
    a = _minimal_manifest(filesystem=FilesystemPolicy(read=("/a",)))
    b = _minimal_manifest(filesystem=FilesystemPolicy(read=("/b",)))
    assert ManifestDigest.of(a) != ManifestDigest.of(b)


def test_digest_canonical_form_is_sorted_json():
    m = _minimal_manifest()
    payload = ManifestDigest.canonical_bytes(m)
    parsed = json.loads(payload)
    # sort_keys=True in the digest means re-serializing sorted matches byte-for-byte.
    assert (
        json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        == payload
    )


def test_load_manifest_from_yaml():
    text = """
    version: 1
    run_id: yaml-run
    filesystem:
      read:
        - /workspace
      write:
        - /workspace/out
    network:
      allow_hosts:
        - example.com
      deny_default: true
    syscalls:
      seccomp_profile: strict
    """
    m = load_manifest_from_yaml(text)
    assert m.run_id == "yaml-run"
    assert m.filesystem.write == ("/workspace/out",)
    assert m.network.allow_hosts == ("example.com",)


# RACT 0.4.0
