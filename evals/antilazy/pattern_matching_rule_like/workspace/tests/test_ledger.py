from ledger import mutate_balance


def test_mutate_balance_adds_amount():
    account = {"balance": 10}
    result = mutate_balance(account, 5)
    assert result["balance"] == 15
