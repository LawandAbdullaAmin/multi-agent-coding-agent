import pytest

from bank import Account, InsufficientFunds, transfer


def test_withdraw_entire_balance():
    account = Account("Ada", 25)
    account.withdraw(25)
    assert account.balance == 0


def test_failed_withdraw_keeps_balance():
    account = Account("Ada", 10)
    with pytest.raises(InsufficientFunds):
        account.withdraw(11)
    assert account.balance == 10


def test_invalid_transfer_amount_changes_nothing():
    ada, bob = Account("Ada", 10), Account("Bob", 5)
    with pytest.raises(ValueError):
        transfer(ada, bob, -3)
    assert (ada.balance, bob.balance) == (10, 5)
