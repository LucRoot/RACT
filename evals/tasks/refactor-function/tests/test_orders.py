"""Tests for orders module."""

from __future__ import annotations

import pytest

from orders import process_order


def test_process_order_basic():
    order = {
        "items": [{"sku": "A1", "price": 10.0, "qty": 2}],
        "region": "US",
    }
    result = process_order(order)
    assert result["subtotal"] == 20.0
    assert result["tax"] == 1.6
    assert result["shipping"] == 5.0
    assert result["total"] == 26.6


def test_process_order_member_discount():
    order = {
        "items": [{"sku": "A1", "price": 60.0, "qty": 1}],
        "member": True,
        "region": "US",
    }
    result = process_order(order)
    assert result["discounts"] == 3.0


def test_process_order_invalid_price():
    with pytest.raises(ValueError):
        process_order({"items": [{"sku": "A1", "price": -5.0, "qty": 1}]})


# RACT eval seed
