"""Order processing module (seed)."""

from __future__ import annotations


# RACT eval seed: this function is intentionally monolithic. The agent must
# split it into smaller units without changing behavior.
def process_order(raw: dict) -> dict:
    """Process a raw order dictionary end-to-end."""
    # Validate input shape.
    if not isinstance(raw, dict):
        raise ValueError("order must be a dict")
    if "items" not in raw or not isinstance(raw["items"], list):
        raise ValueError("order must contain an items list")
    if not raw["items"]:
        raise ValueError("order must contain at least one item")

    # Validate each item.
    total = 0.0
    discounts = 0.0
    tax = 0.0
    validated_items: list[dict] = []
    for item in raw["items"]:
        if not isinstance(item, dict):
            raise ValueError("each item must be a dict")
        if "sku" not in item or not isinstance(item["sku"], str):
            raise ValueError("item missing sku")
        if "price" not in item or not isinstance(item["price"], (int, float)):
            raise ValueError("item missing price")
        if item["price"] < 0:
            raise ValueError("price cannot be negative")
        if "qty" not in item or not isinstance(item["qty"], int):
            raise ValueError("item missing qty")
        if item["qty"] <= 0:
            raise ValueError("qty must be positive")
        line_total = item["price"] * item["qty"]
        total += line_total
        validated_items.append(
            {"sku": item["sku"], "price": item["price"], "qty": item["qty"]}
        )

    # Apply membership discount.
    is_member = bool(raw.get("member", False))
    if is_member:
        if total > 100.0:
            discounts += total * 0.10
        elif total > 50.0:
            discounts += total * 0.05
        else:
            discounts += 0.0

    # Apply coupon code.
    coupon = raw.get("coupon", "")
    if coupon == "SAVE10":
        discounts += total * 0.10
    elif coupon == "SAVE5":
        discounts += total * 0.05
    elif coupon:
        # Unknown coupon: ignore but log a warning placeholder.
        pass

    # Calculate tax.
    region = raw.get("region", "US")
    taxable = total - discounts
    if region == "US":
        tax = taxable * 0.08
    elif region == "EU":
        tax = taxable * 0.20
    elif region == "CA":
        tax = taxable * 0.13
    else:
        tax = taxable * 0.10

    # Apply shipping.
    shipping = 0.0
    if raw.get("shipping", "standard") == "express":
        if total > 200.0:
            shipping = 0.0
        else:
            shipping = 15.0
    else:
        if total > 100.0:
            shipping = 0.0
        else:
            shipping = 5.0

    # Final total.
    final_total = taxable + tax + shipping

    # Build result.
    result: dict = {
        "items": validated_items,
        "subtotal": round(total, 2),
        "discounts": round(discounts, 2),
        "tax": round(tax, 2),
        "shipping": round(shipping, 2),
        "total": round(final_total, 2),
        "region": region,
        "member": is_member,
    }
    return result
