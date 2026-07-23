# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from ract.complexity_router import ComplexityRouter


def _make_router(health_fn=None):
    return ComplexityRouter(
        tiers={
            "local": {
                "endpoint": {
                    "name": "local",
                    "base_url": "http://127.0.0.1:8106",
                    "model": "qwen",
                },
                "cost": 1,
            },
            "low_cost_cloud": {
                "endpoint": {
                    "name": "cloud",
                    "base_url": "http://cloud.example.com",
                    "model": "cheap",
                },
                "cost": 5,
            },
            "high_cost_fallback": {
                "endpoint": {
                    "name": "frontier",
                    "base_url": "http://frontier.example.com",
                    "model": "big",
                },
                "cost": 50,
            },
        },
        health_check_fn=health_fn,
    )


def test_routes_trivial_task_to_local():
    router = _make_router()
    selection = router.select_endpoint("fix typo in README")
    assert selection.score.tier == "low"
    assert selection.endpoint_tier == "local"
    assert selection.endpoint_name == "local"
    assert selection.score.score < 0.25


def test_routes_frontier_task_to_fallback():
    router = _make_router()
    selection = router.select_endpoint(
        "Design a repo-wide architecture refactor for unknown frontier algorithms"
    )
    # Strong frontier signals reach the high tier and map to the high-cost fallback.
    assert selection.score.tier in ("high", "frontier")
    assert selection.endpoint_tier == "high_cost_fallback"
    assert selection.endpoint_name == "frontier"


def test_medium_task_routes_to_cloud():
    router = _make_router()
    selection = router.select_endpoint("Design a cross-module algorithm")
    assert selection.score.tier == "medium"
    assert selection.endpoint_tier == "low_cost_cloud"
    assert selection.endpoint_name == "cloud"


def test_falls_back_when_local_unhealthy():
    def health(endpoint):
        return endpoint.get("name") != "local"

    router = _make_router(health_fn=health)
    selection = router.select_endpoint("fix typo")
    assert selection.score.tier == "low"
    assert selection.endpoint_tier == "low_cost_cloud"
    assert selection.endpoint_name == "cloud"


def test_falls_back_multiple_tiers():
    def health(endpoint):
        return endpoint.get("name") == "frontier"

    router = _make_router(health_fn=health)
    selection = router.select_endpoint("small export")
    assert selection.score.tier == "low"
    assert selection.endpoint_tier == "high_cost_fallback"
    assert selection.endpoint_name == "frontier"


def test_no_healthy_endpoint_raises():
    router = _make_router(health_fn=lambda _ep: False)
    with pytest.raises(RuntimeError, match="no healthy endpoint"):
        router.select_endpoint("anything")


def test_no_tiers_raises():
    router = ComplexityRouter()
    with pytest.raises(ValueError, match="no tiers configured"):
        router.select_endpoint("anything")


def test_from_config():
    router = ComplexityRouter.from_config(
        {
            "tiers": {
                "local": {"endpoint": {"name": "local"}},
            },
            "thresholds": {"low": 0.3, "medium": 0.6, "high": 0.9},
        }
    )
    assert router.thresholds["low"] == 0.3
    selection = router.select_endpoint("trivial task")
    assert selection.endpoint_name == "local"


def test_from_config_bad_tiers():
    with pytest.raises(ValueError, match="tiers must be a dict"):
        ComplexityRouter.from_config({"tiers": ["a"]})


def test_from_config_bad_thresholds():
    with pytest.raises(ValueError, match="thresholds must be a dict"):
        ComplexityRouter.from_config(
            {"tiers": {"local": {"endpoint": {}}}, "thresholds": "bad"}
        )


def test_override_health_check_fn():
    router = _make_router(health_fn=lambda _ep: True)
    selection = router.select_endpoint(
        "anything", health_check_fn=lambda ep: ep.get("name") == "cloud"
    )
    assert selection.endpoint_name == "cloud"


def test_unknown_tier_defaults_to_low_order():
    router = _make_router()
    # Force an impossible tier name through a patched _tier_for_score
    router._tier_for_score = lambda _score: "unknown"  # type: ignore[method-assign]
    selection = router.select_endpoint("anything")
    assert selection.endpoint_name == "local"
