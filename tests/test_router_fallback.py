from __future__ import annotations


import pytest

from ract.router_fallback import FallbackChain, FallbackResult


def test_first_endpoint_succeeds():
    chain = FallbackChain([{"name": "a"}, {"name": "b"}], call_fn=lambda ep: ep["name"])
    result = chain.try_endpoints()
    assert result.success is True
    assert result.endpoint == "a"
    assert result.value == "a"
    assert len(result.attempts) == 1


def test_skips_failed_endpoint():
    def call_fn(ep):
        if ep["name"] == "a":
            raise ConnectionError("down")
        return ep["name"]

    chain = FallbackChain([{"name": "a"}, {"name": "b"}], call_fn=call_fn)
    result = chain.try_endpoints()
    assert result.success is True
    assert result.endpoint == "b"
    assert len(result.attempts) == 2
    assert result.attempts[0]["success"] is False
    assert result.attempts[1]["success"] is True


def test_all_fail():
    chain = FallbackChain([{"name": "a"}, {"name": "b"}], call_fn=lambda ep: 1 / 0)
    result = chain.try_endpoints()
    assert result.success is False
    assert result.endpoint is None
    assert len(result.attempts) == 2
    assert "division by zero" in result.error


def test_empty_endpoints():
    chain = FallbackChain([])
    result = chain.try_endpoints(call_fn=lambda ep: ep)
    assert result.success is False
    assert "no endpoints configured" in result.error


def test_from_config():
    chain = FallbackChain.from_config(
        {"endpoints": [{"name": "local"}, {"name": "cloud"}]},
        call_fn=lambda ep: ep["name"],
    )
    result = chain.try_endpoints()
    assert result.success is True
    assert result.endpoint == "local"


def test_from_config_bad_endpoints_type():
    with pytest.raises(ValueError, match="must be a list"):
        FallbackChain.from_config({"endpoints": "not-a-list"})


def test_unwrap_success():
    result = FallbackResult(success=True, value=42)
    assert result.unwrap() == 42


def test_unwrap_failure():
    result = FallbackResult(success=False, error="everything failed")
    with pytest.raises(RuntimeError, match="everything failed"):
        result.unwrap()


def test_call_fn_override():
    chain = FallbackChain([{"name": "a"}], call_fn=lambda ep: "wrong")
    result = chain.try_endpoints(call_fn=lambda ep: "override")
    assert result.value == "override"


def test_missing_call_fn_raises():
    chain = FallbackChain([{"name": "a"}])
    with pytest.raises(ValueError, match="call_fn must be provided"):
        chain.try_endpoints()
