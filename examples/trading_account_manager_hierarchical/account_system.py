"""Trading simulation account management system — core domain logic.

Pure Python standard library implementation.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# 1. Standalone share-price lookup
# ---------------------------------------------------------------------------
def get_share_price(symbol: str) -> float:
    """Return the fixed price for a known share symbol.

    Raises ValueError for unknown symbols (lookup is case-sensitive).
    """
    prices = {
        "AAPL": 150.0,
        "TSLA": 250.0,
        "GOOGL": 2800.0,
    }
    try:
        return prices[symbol]
    except KeyError:
        raise ValueError(f"Unknown symbol: {symbol!r}") from None


# ---------------------------------------------------------------------------
# 2. Transaction data class
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Transaction:
    """An immutable record of a single account transaction.

    ``amount`` is the cash impact: positive for DEPOSIT/SELL, negative for
    WITHDRAW/BUY. ``symbol``/``quantity``/``price`` are None for cash-only
    transactions (DEPOSIT/WITHDRAW).
    """

    timestamp: str
    txn_type: str
    symbol: Optional[str]
    quantity: Optional[int]
    price: Optional[float]
    amount: float


# ---------------------------------------------------------------------------
# 3. Custom exceptions
# ---------------------------------------------------------------------------
class InsufficientFundsError(Exception):
    """Raised when a withdrawal or purchase exceeds available cash balance."""

    pass


class InsufficientHoldingsError(Exception):
    """Raised when a sell order exceeds the current holdings of that symbol."""

    pass


# ---------------------------------------------------------------------------
# 4. Account
# ---------------------------------------------------------------------------
class Account:
    """Represents one user's trading account."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.cash_balance = 0.0
        self.holdings: dict[str, int] = {}
        self.transactions: list[Transaction] = []

    # -- cash operations ---------------------------------------------------
    def deposit(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("Deposit amount must be positive.")
        self.cash_balance += amount
        self.transactions.append(
            Transaction(
                timestamp=datetime.now().isoformat(),
                txn_type="DEPOSIT",
                symbol=None,
                quantity=None,
                price=None,
                amount=+amount,
            )
        )

    def withdraw(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive.")
        if amount > self.cash_balance:
            raise InsufficientFundsError(
                "Insufficient funds for withdrawal."
            )
        self.cash_balance -= amount
        self.transactions.append(
            Transaction(
                timestamp=datetime.now().isoformat(),
                txn_type="WITHDRAW",
                symbol=None,
                quantity=None,
                price=None,
                amount=-amount,
            )
        )

    # -- share operations --------------------------------------------------
    def buy(self, symbol: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("Buy quantity must be positive.")
        price = get_share_price(symbol)  # may raise ValueError
        cost = price * quantity
        if cost > self.cash_balance:
            raise InsufficientFundsError("Insufficient funds for purchase.")
        self.cash_balance -= cost
        self.holdings[symbol] = self.holdings.get(symbol, 0) + quantity
        self.transactions.append(
            Transaction(
                timestamp=datetime.now().isoformat(),
                txn_type="BUY",
                symbol=symbol,
                quantity=quantity,
                price=price,
                amount=-cost,
            )
        )

    def sell(self, symbol: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("Sell quantity must be positive.")
        price = get_share_price(symbol)  # may raise ValueError
        held = self.holdings.get(symbol, 0)
        if held < quantity:
            raise InsufficientHoldingsError(
                f"Insufficient holdings of {symbol} to sell."
            )
        proceeds = price * quantity
        self.cash_balance += proceeds
        self.holdings[symbol] = held - quantity
        if self.holdings[symbol] == 0:
            del self.holdings[symbol]
        self.transactions.append(
            Transaction(
                timestamp=datetime.now().isoformat(),
                txn_type="SELL",
                symbol=symbol,
                quantity=quantity,
                price=price,
                amount=proceeds,
            )
        )

    # -- queries -----------------------------------------------------------
    def get_holdings(self) -> dict[str, int]:
        """Return a copy of the current holdings (only symbols with >0 qty)."""
        return dict(self.holdings)

    def get_balance(self) -> float:
        """Return the current cash balance."""
        return self.cash_balance

    def get_portfolio_value(self) -> float:
        """Return cash plus the current market value of all holdings."""
        holdings_value = sum(
            get_share_price(sym) * qty for sym, qty in self.holdings.items()
        )
        return self.cash_balance + holdings_value

    def get_total_deposits(self) -> float:
        """Return the sum of all cash deposited into the account."""
        return sum(
            txn.amount
            for txn in self.transactions
            if txn.txn_type == "DEPOSIT"
        )

    def get_total_withdrawals(self) -> float:
        """Return the sum of all cash withdrawn from the account."""
        return sum(
            abs(txn.amount)
            for txn in self.transactions
            if txn.txn_type == "WITHDRAW"
        )

    def get_profit_loss(self) -> float:
        """Return portfolio value minus net invested capital (deposits
        minus withdrawals), representing the genuine profit/loss."""
        net_invested = self.get_total_deposits() - self.get_total_withdrawals()
        return self.get_portfolio_value() - net_invested

    def get_transactions(self) -> list[Transaction]:
        """Return a copy of the full transaction history, in order."""
        return list(self.transactions)
