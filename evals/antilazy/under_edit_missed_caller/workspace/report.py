from billing import calc_total  # STALE — G6 must flag


def render(items):
    return f"Total: {calc_total(items):.2f}"
