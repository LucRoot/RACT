"""Tests for task-aware temperature routing."""

from __future__ import annotations


from ract.temperature_router import TemperatureRouter


def test_code_action_uses_low_temperature():
    router = TemperatureRouter()
    assert router.for_action("Write the implementation for the parser") == 0.15


def test_plan_action_uses_moderate_temperature():
    router = TemperatureRouter()
    assert router.for_action("Design the milestone backlog") == 0.4


def test_brainstorm_action_uses_high_temperature():
    router = TemperatureRouter()
    assert router.for_action("Brainstorm alternative UI flows") == 0.55


def test_default_action_uses_default_temperature():
    router = TemperatureRouter()
    assert router.for_action("Verify the configuration") == 0.25


def test_plan_intent_uses_plan_temperature():
    router = TemperatureRouter()
    assert router.for_plan("Refactor the loop controller") == 0.4


def test_plan_intent_brainstorm_uses_high_temperature():
    router = TemperatureRouter()
    assert router.for_plan("Brainstorm new use cases") == 0.55


def test_custom_temperatures_respected():
    router = TemperatureRouter(
        code_temp=0.05, plan_temp=0.35, default_temp=0.2, brainstorm_temp=0.7
    )
    assert router.for_action("generate code") == 0.05
    assert router.for_action("outline architecture") == 0.35
    assert router.for_action("explore ideas") == 0.7
    assert router.for_action("check status") == 0.2


# RACT 0.1.1 - Trust and tooling
