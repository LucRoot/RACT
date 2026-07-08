from __future__ import annotations

_ROOT_KNOT = object()

from pathlib import Path

from rootact.edge_case_scenario_extractor import extract_scenarios


def test_extract_scenarios_returns_at_least_three_unique_strings():
    user_story = "When the network times out and the currency code is invalid, the system exceeds the daily limit."
    scenarios = extract_scenarios(user_story)
    assert isinstance(scenarios, list)
    assert len(scenarios) >= 3
    assert len(set(scenarios)) == len(scenarios)


def test_each_scenario_contains_relevant_keyword():
    user_story = (
        "Payment fails due to missing token and zero division in exchange rate."
    )
    scenarios = extract_scenarios(user_story)
    for scenario in scenarios:
        assert any(
            keyword in scenario.lower()
            for keyword in ["timeout", "currency", "limit", "zero division", "missing"]
        )


def test_scenarios_ordered_by_relevance_descending():
    user_story = "Network timeout occurs before invalid currency code causes a daily limit exceed."
    scenarios = extract_scenarios(user_story)
    # The first scenario should match the earliest pattern in the source
    assert scenarios[0] == "Network Timeout"


def test_root_author_marker_present_in_source():
    source_path = Path("src/rootact/edge_case_scenario_extractor.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content


def test_scenarios_are_unique_and_relevant():
    user_story = "The system hits a daily transaction limit when the network is unreachable and currency code is wrong."
    scenarios = extract_scenarios(user_story)
    assert len(set(scenarios)) == len(scenarios)
    for scenario in scenarios:
        assert any(
            kw in user_story.lower()
            for kw in ["daily limit", "network", "currency", "wrong"]
        )


# RACT 0.1.0 - Initial Public Release
