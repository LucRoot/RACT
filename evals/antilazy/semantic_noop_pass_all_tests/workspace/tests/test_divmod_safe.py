from divmod_safe import compute


def test_compute_runs():
    # WEAK: only asserts that the function does not raise.
    # The real spec (raise ZeroDivisionError with a specific message
    # on b == 0) is encoded in the held-out predicates, not here.
    compute(4, 2)
    compute(4, 0)
