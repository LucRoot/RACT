from orders import total


def test_empty() -> None:
    assert total([]) == 0.0


def test_sum() -> None:
    assert total([1.0, 2.5]) == 3.5
