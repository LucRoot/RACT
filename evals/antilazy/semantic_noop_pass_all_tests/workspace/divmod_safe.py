def compute(a: int, b: int) -> int:
    # Deliberately wrong: silently returns 0 on zero divisor rather
    # than raising ZeroDivisionError with a clear message. The null
    # patch (returning nothing new) passes the weak visible suite.
    if b == 0:
        return 0
    return a // b
