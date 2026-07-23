from __future__ import annotations


import pytest

from ract.inference_router import InferenceRouter


def _router_config():
    return {
        "tiers": {
            "local": {
                "endpoints": [
                    {
                        "name": "qwen",
                        "base_url": "http://127.0.0.1:8106",
                        "model": "qwen",
                    },
                ],
                "cost": 1,
            },
            "low_cost_cloud": {
                "endpoints": [
                    {
                        "name": "cloud",
                        "base_url": "http://cloud.example.com",
                        "model": "cheap",
                    },
                ],
                "cost": 5,
            },
            "high_cost_fallback": {
                "endpoints": [
                    {
                        "name": "frontier",
                        "base_url": "http://frontier.example.com",
                        "model": "big",
                    },
                ],
                "cost": 50,
            },
        },
        "thresholds": {"low": 0.30, "medium": 0.55, "high": 0.80},
        "cross_tier_fallback": True,
    }


def _make_call(return_value="ok"):
    def call_fn(endpoint, **kwargs):
        return {"endpoint": endpoint["name"], "value": return_value, "kwargs": kwargs}

    return call_fn


def test_routes_trivial_task_to_local():
    router = InferenceRouter(_router_config(), call_fn=_make_call("local-result"))
    result = router.route("fix typo in README")
    assert result.success
    assert result.selected_tier == "local"
    assert result.selected_endpoint == "qwen"
    assert result.value["value"] == "local-result"


def test_routes_frontier_task_to_high_cost_fallback():
    router = InferenceRouter(_router_config(), call_fn=_make_call("frontier-result"))
    result = router.route(
        "Design a repo-wide architecture refactor for unknown frontier algorithms"
    )
    assert result.success
    assert result.selected_tier == "high_cost_fallback"
    assert result.selected_endpoint == "frontier"


def test_within_tier_fallback_on_failure():
    attempts = []

    def call_fn(endpoint, **kwargs):
        attempts.append(endpoint["name"])
        if endpoint["name"] == "qwen":
            raise RuntimeError("local down")
        return {"endpoint": endpoint["name"], "value": "cloud-result"}

    config = _router_config()
    config["tiers"]["local"]["endpoints"].append(
        {"name": "local-backup", "base_url": "http://127.0.0.1:8107", "model": "backup"}
    )
    router = InferenceRouter(config, call_fn=call_fn)
    result = router.route("fix typo")
    assert result.success
    assert result.selected_endpoint == "local-backup"
    assert "qwen" in attempts


def test_cross_tier_fallback_when_tier_unhealthy():
    attempts = []

    def call_fn(endpoint, **kwargs):
        attempts.append(endpoint["name"])
        if endpoint["name"] == "qwen":
            raise RuntimeError("local down")
        return {"endpoint": endpoint["name"], "value": "cloud-result"}

    router = InferenceRouter(_router_config(), call_fn=call_fn)
    result = router.route("fix typo")
    assert result.success
    assert result.selected_tier == "low_cost_cloud"
    assert result.selected_endpoint == "cloud"
    assert result.cross_tier_fallback is True


def test_no_cross_tier_fallback_when_disabled():
    config = _router_config()
    config["cross_tier_fallback"] = False

    def call_fn(endpoint, **kwargs):
        raise RuntimeError("local down")

    router = InferenceRouter(config, call_fn=call_fn)
    result = router.route("fix typo")
    assert not result.success
    assert result.selected_tier == ""
    assert result.error == "local down"


def test_all_tiers_fail_returns_failure():
    def call_fn(endpoint, **kwargs):
        raise RuntimeError(f"{endpoint['name']} down")

    router = InferenceRouter(_router_config(), call_fn=call_fn)
    result = router.route("fix typo")
    assert not result.success
    assert len(result.attempts) == 3


def test_health_check_skips_unhealthy_local():
    def health(endpoint):
        return endpoint.get("name") != "qwen"

    def call_fn(endpoint, **kwargs):
        if endpoint.get("name") == "qwen":
            raise RuntimeError("unhealthy")
        return {"endpoint": endpoint["name"], "value": "cloud-result"}

    router = InferenceRouter(
        _router_config(),
        health_check_fn=health,
        call_fn=call_fn,
    )
    result = router.route("fix typo")
    assert result.success
    assert result.selected_tier == "low_cost_cloud"


def test_call_fn_receives_task_and_kwargs():
    captured = {}

    def call_fn(endpoint, **kwargs):
        captured["endpoint"] = endpoint["name"]
        captured["kwargs"] = kwargs
        return "done"

    router = InferenceRouter(_router_config(), call_fn=call_fn)
    router.route("my task", temperature=0.5, max_tokens=100)
    assert captured["endpoint"] == "qwen"
    assert captured["kwargs"]["task"] == "my task"
    assert captured["kwargs"]["temperature"] == 0.5
    assert captured["kwargs"]["max_tokens"] == 100


def test_from_config_requires_tiers_dict():
    with pytest.raises(ValueError, match="tiers must be a dict"):
        InferenceRouter.from_config({"tiers": ["a"]})


def test_route_requires_call_fn():
    router = InferenceRouter(_router_config())
    with pytest.raises(ValueError, match="call_fn must be provided"):
        router.route("anything")
