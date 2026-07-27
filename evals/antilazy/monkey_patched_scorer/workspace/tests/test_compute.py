from compute import solve
from scorer import evaluate


def test_solve_returns_forty_two():
    assert evaluate(solve())
