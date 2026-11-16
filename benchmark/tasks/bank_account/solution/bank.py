"""Bank accounts."""


class InsufficientFunds(Exception):
    pass


class Account:
    def __init__(self, owner: str, balance: float = 0.0):
        self.owner = owner
        self.balance = balance

    def deposit(self, amount: float) -> None:
        """Deposits a positive amount, otherwise ValueError."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self.balance += amount

    def withdraw(self, amount: float) -> None:
        """Withdraws a positive amount. Raises InsufficientFunds if the balance is not sufficient."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if amount > self.balance:
            raise InsufficientFunds(f"Balance {self.balance} is not sufficient for {amount}")
        self.balance -= amount


def transfer(source: Account, target: Account, amount: float) -> None:
    """Transfers amount from source to target. If the transfer fails, both accounts stay unchanged."""
    source.withdraw(amount)
    target.deposit(amount)
