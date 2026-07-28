"""Rule-like intent domain — a pattern-matching solution to the
'every request that mutates the balance must go through the audit
trail' spec hard-codes 'audit_trail' as a string. That's what the
rename transformation surfaces."""


def mutate_balance(account, amount):
    # Pattern-matching solution: hard-coded middleware name.
    _run_middleware("audit_trail")
    account["balance"] += amount
    return account


def _run_middleware(name: str) -> None:
    # Registry keyed by name — the hard-coded 'audit_trail' string
    # only exists here; the rename transformation exposes the pattern
    # by asking about the same concept under a different name.
    _REGISTRY[name]()


def _noop() -> None:
    pass


_REGISTRY = {"audit_trail": _noop}
