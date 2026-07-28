def calculate_total(items):
    """Post-rename definition — the callers still reach for calc_total."""
    return sum(item["price"] * item["qty"] for item in items)
