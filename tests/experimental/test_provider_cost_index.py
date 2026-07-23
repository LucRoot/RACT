from __future__ import annotations


from ract.experimental.provider_cost_index import (
    COST_INDEX,
    get_cost_index,
    estimate_cost,
)


def test_local_provider_is_free():
    index = get_cost_index("local")
    assert index["input_per_1k"] == 0.0
    assert index["output_per_1k"] == 0.0
    assert estimate_cost("local", tokens=10000) == 0.0


def test_openai_estimate_with_total_tokens():
    # gpt-4o-mini: input 0.15, output 0.60 -> blended 0.375 per 1k
    cost = estimate_cost("openai", tokens=1000)
    assert cost == 0.375


def test_anthropic_estimate_with_input_output_split():
    # Claude 3.5 Sonnet: input 3.0, output 15.0 per 1k
    cost = estimate_cost("anthropic", input_tokens=1000, output_tokens=500)
    assert cost == 3.0 + 7.5


def test_case_insensitive_lookup():
    assert (
        get_cost_index("OPENAI")["input_per_1k"] == COST_INDEX["openai"]["input_per_1k"]
    )


def test_unknown_provider_returns_zero_estimate():
    index = get_cost_index("some-unknown-cloud")
    assert index["input_per_1k"] == 0.0
    assert estimate_cost("some-unknown-cloud", tokens=1000) == 0.0


def test_alias_resolution():
    assert (
        get_cost_index("claude")["input_per_1k"]
        == COST_INDEX["anthropic"]["input_per_1k"]
    )
    assert get_cost_index("gpt")["input_per_1k"] == COST_INDEX["openai"]["input_per_1k"]


def test_qwen_local_alias_is_free():
    assert estimate_cost("qwen", tokens=50000) == 0.0


def test_cost_index_has_currency():
    for entry in COST_INDEX.values():
        assert entry["currency"] == "USD"
        assert "input_per_1k" in entry
        assert "output_per_1k" in entry
