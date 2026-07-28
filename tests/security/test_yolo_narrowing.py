"""``--yolo`` narrowing tests.

SUBSTRATE §4.3 narrowed by module_03: --yolo does not disable the
sandbox and does not reach tier 3. It reads ``manifest.yolo_widen`` and
widens the manifest within those bounds for a single step.
"""

from __future__ import annotations

from ract.security.manifest import (
    CapabilityManifest,
    ManifestValidator,
    TierPolicy,
    YoloWiden,
)


def _widen_for_yolo(manifest: CapabilityManifest) -> CapabilityManifest:
    """Simulate a --yolo widen the way ``HandshakeRegistry`` will call it.

    The widen produces a new manifest whose ``filesystem.write`` /
    ``filesystem.read`` / ``network.allow_hosts`` are the union of the
    base manifest and the ``yolo_widen`` bounds. Tier 3 is NEVER lifted
    by this path.
    """
    return manifest.model_copy(
        update={
            "filesystem": manifest.filesystem.model_copy(
                update={
                    "read": manifest.filesystem.read
                    + manifest.yolo_widen.extra_read,
                    "write": manifest.filesystem.write
                    + manifest.yolo_widen.extra_write,
                }
            ),
            "network": manifest.network.model_copy(
                update={
                    "allow_hosts": manifest.network.allow_hosts
                    + manifest.yolo_widen.extra_hosts,
                }
            ),
        }
    )


def test_yolo_does_not_lift_tier_3_default_false():
    """--yolo widen produces a manifest whose tiers section is unchanged."""
    base = CapabilityManifest(
        run_id="yolo",
        tiers=TierPolicy(default=1, allow_tier_3=False),
        yolo_widen=YoloWiden(
            extra_write=("/workspace/scratch",),
            extra_hosts=("example.com",),
        ),
    )
    widened = _widen_for_yolo(base)
    assert widened.tiers.allow_tier_3 is False
    assert widened.tiers.default == 1
    assert widened.filesystem.write == ("/workspace/scratch",)
    assert widened.network.allow_hosts == ("example.com",)
    # Validator is silent on the widened manifest — no violations.
    assert ManifestValidator.validate(widened) == []


def test_yolo_widen_of_tier_3_manifest_is_refused_by_validator():
    """Even if the base manifest sets allow_tier_3=True, the validator refuses.

    The compile-time constant ``RACT_TIER_3_ENABLED`` is False in the
    shipped source; this test asserts the manifest cannot lift its own
    tier-3 ban without an ADR flipping the constant.
    """
    base = CapabilityManifest(
        run_id="yolo-tier3",
        tiers=TierPolicy(default=1, allow_tier_3=True),
    )
    violations = ManifestValidator.validate(base)
    assert any(v.code == "tier_3_compile_time_denied" for v in violations)


# RACT 0.4.0
