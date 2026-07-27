from billing import calc_total  # STALE — G6 must flag


def emit(items):
    print(f"Receipt total = {calc_total(items)}")
