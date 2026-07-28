from billing import calc_total  # STALE — G6 must flag


def summary(items):
    return {"total": calc_total(items)}
