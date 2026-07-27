def round_half_even(x: float) -> int:
    """Banker's rounding — round half to even."""
    lower = int(x // 1)
    frac = x - lower
    if frac < 0.5:
        return lower
    if frac > 0.5:
        return lower + 1
    return lower if lower % 2 == 0 else lower + 1
