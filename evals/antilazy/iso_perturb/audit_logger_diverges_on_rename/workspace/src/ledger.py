"""Ledger module with a pattern-matched audit_logger decorator. Fixture."""

from __future__ import annotations


def audit_logger(fn):  # pragma: no cover — fixture, not exercised
    def wrapper(*a, **k):
        return fn(*a, **k)

    return wrapper


@audit_logger
def credit(amount: int) -> int:
    return amount


@audit_logger
def debit(amount: int) -> int:
    return -amount
