"""B-027: every tier-3 capability has a red-team module, and run_command has one too."""

from __future__ import annotations

from pathlib import Path

from ract.core.threat_model import CapabilityTier
from ract.tools import REGISTRY

HERE = Path(__file__).parent


def test_every_tier3_tool_has_a_red_team_module() -> None:
    tier3 = sorted(
        name
        for name, spec in REGISTRY.items()
        if spec.tier is CapabilityTier.TIER_3_EXTERNAL
    )
    assert tier3, "no tier-3 tool is registered"
    missing = [name for name in tier3 if not (HERE / f"test_{name}.py").is_file()]
    assert not missing, f"tier-3 tools without a red-team module: {missing}"


def test_the_command_core_has_its_own_module() -> None:
    assert (HERE / "test_run_command.py").is_file()
