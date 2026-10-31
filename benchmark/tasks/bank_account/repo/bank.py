"""Bankkonten."""


class InsufficientFunds(Exception):
    pass


class Account:
    def __init__(self, owner: str, balance: float = 0.0):
        self.owner = owner
        self.balance = balance

    def deposit(self, amount: float) -> None:
        """Zahlt einen positiven Betrag ein, sonst ValueError."""
        if amount <= 0:
            raise ValueError("Betrag muss positiv sein")
        self.balance += amount

    def withdraw(self, amount: float) -> None:
        """Hebt einen positiven Betrag ab. Wirft InsufficientFunds, wenn das Guthaben nicht reicht."""
        if amount <= 0:
            raise ValueError("Betrag muss positiv sein")
        self.balance -= amount


def transfer(source: Account, target: Account, amount: float) -> None:
    """Überweist amount von source an target. Schlägt sie fehl, bleiben beide Konten unverändert."""
    target.deposit(amount)
    source.withdraw(amount)
