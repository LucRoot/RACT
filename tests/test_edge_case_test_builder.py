from __future__ import annotations

_ROOT_KNOT = object()

from pathlib import Path

from rootact.edge_case_test_builder import build_edge_cases


def test_build_edge_cases_returns_exactly_five_dicts():
    user_story = "The payment gateway fails when the network is unreachable and the currency code is invalid."
    result = build_edge_cases(user_story)
    assert isinstance(result, list)
    assert len(result) == 5
    for item in result:
        assert isinstance(item, dict)


def test_each_dict_contains_required_keys():
    user_story = (
        "Payment processing fails when the exchange rate calculation divides by zero."
    )
    cases = build_edge_cases(user_story)
    required = {"scenario", "pytest_fixture", "assertion"}
    for case in cases:
        assert required.issubset(case.keys())


def test_pytest_fixture_are_valid_identifiers_and_deterministic():
    user_story = "The system exceeds the daily transaction limit during peak hours."
    cases1 = build_edge_cases(user_story, seed=42)
    cases2 = build_edge_cases(user_story, seed=42)
    for c1, c2 in zip(cases1, cases2):
        assert c1["pytest_fixture"] == c2["pytest_fixture"]
        assert c1["pytest_fixture"].isidentifier()


def test_assertion_starts_with_assert_and_interpolates_user_story():
    user_story = "Invalid currency code causes a gateway timeout."
    cases = build_edge_cases(user_story)
    for case in cases:
        assert case["assertion"].startswith("assert ")
        # Verify that at least one dynamic element from the story appears
        assert any(
            dynamic in case["assertion"]
            for dynamic in ["invalid currency code", "gateway timeout"]
        )


def test_root_author_marker_present_in_source():
    source_path = Path("src/rootact/edge_case_test_builder.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content


# RACT 0.1.0 - Initial Public Release
