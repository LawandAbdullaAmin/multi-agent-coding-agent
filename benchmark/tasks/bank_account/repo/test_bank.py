import pytest

from bank import Account, InsufficientFunds, transfer


def test_withdraw():
    account = Account("Ada", 100)
    account.withdraw(30)
    assert account.balance == 70


def test_withdraw_too_much():
    with pytest.raises(InsufficientFunds):
        Account("Ada", 10).withdraw(50)


def test_transfer():
    ada, bob = Account("Ada", 100), Account("Bob")
    transfer(ada, bob, 40)
    assert (ada.balance, bob.balance) == (60, 40)


def test_failed_transfer_changes_nothing():
    ada, bob = Account("Ada", 10), Account("Bob", 5)
    with pytest.raises(InsufficientFunds):
        transfer(ada, bob, 50)
    assert (ada.balance, bob.balance) == (10, 5)
