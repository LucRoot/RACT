from billing import calc_total  # STALE — G6 must flag


def bill(items):
    return calc_total(items) * 1.1  # add tax
