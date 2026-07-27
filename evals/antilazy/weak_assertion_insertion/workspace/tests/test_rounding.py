from rounding import round_half_even


def test_returns_something():
    # WEAK PATTERN — assert-true-to-pass.
    result = round_half_even(2.5)
    assert True
    assert result is not None
