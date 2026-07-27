from billing import calculate_total


def test_calculate_total():
    items = [{"price": 2.0, "qty": 3}, {"price": 1.5, "qty": 2}]
    assert calculate_total(items) == 9.0
