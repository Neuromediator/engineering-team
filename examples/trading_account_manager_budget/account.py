"""Backend account management for a trading simulation platform.

Pure Python standard library only. No third-party dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

SUPPORTED_SYMBOLS = ("AAPL", "TSLA", "GOOGL")
PRICES = {"AAPL": 150.0, "TSLA": 200.0, "GOOGL": 120.0}


def get_share_price(symbol: str) -> float:
    """Return the current share price for a supported symbol.

    Raises ValueError for unsupported symbols.
    """
    if symbol not in PRICES:
        raise ValueError(f"Unsupported symbol: {symbol}")
    return PRICES[symbol]


class TransactionType(Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Transaction:
    id: str
    type: TransactionType
    symbol: str | None  # None for deposit/withdrawal
    quantity: float     # shares for BUY/SELL, 0 for deposit/withdrawal
    price: float        # share price at time of trade, 0 for deposit/withdrawal
    amount: float       # dollar amount for deposit/withdrawal; total cost/proceeds for trades
    timestamp: datetime  # UTC time of transaction
    balance_after: float  # account balance after this transaction


@dataclass
class Holding:
    symbol: str
    quantity: float
    average_cost: float  # weighted average purchase price per share


class Account:
    """A single trading simulation account."""

    def __init__(self, account_id: str, owner_name: str) -> None:
        self._account_id = account_id
        self._owner_name = owner_name
        self._balance = 0.0
        self._initial_deposit = 0.0
        self._holdings: dict[str, float] = {}
        self._cost_basis: dict[str, float] = {}
        self._transactions: list[Transaction] = []
        self._tx_counter = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def owner_name(self) -> str:
        return self._owner_name

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def initial_deposit(self) -> float:
        return self._initial_deposit

    @property
    def transactions(self) -> list[Transaction]:
        return list(self._transactions)

    # ------------------------------------------------------------------
    # Deposit / Withdraw
    # ------------------------------------------------------------------
    def deposit(self, amount: float) -> Transaction:
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        if not self._transactions:
            self._initial_deposit = amount
        self._balance += amount
        return self._record_transaction(
            TransactionType.DEPOSIT, None, 0, 0.0, amount
        )

    def withdraw(self, amount: float) -> Transaction:
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if amount > self._balance:
            raise ValueError("Insufficient funds for withdrawal")
        self._balance -= amount
        return self._record_transaction(
            TransactionType.WITHDRAWAL, None, 0, 0.0, amount
        )

    # ------------------------------------------------------------------
    # Buy / Sell
    # ------------------------------------------------------------------
    def buy_shares(self, symbol: str, quantity: float) -> Transaction:
        if symbol not in SUPPORTED_SYMBOLS:
            raise ValueError(f"Unsupported symbol: {symbol}")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        price = get_share_price(symbol)
        total_cost = price * quantity
        if total_cost > self._balance:
            raise ValueError("Insufficient funds to buy shares")
        self._balance -= total_cost
        self._holdings[symbol] = self._holdings.get(symbol, 0.0) + quantity
        self._cost_basis[symbol] = self._cost_basis.get(symbol, 0.0) + total_cost
        return self._record_transaction(
            TransactionType.BUY, symbol, quantity, price, total_cost
        )

    def sell_shares(self, symbol: str, quantity: float) -> Transaction:
        if symbol not in SUPPORTED_SYMBOLS:
            raise ValueError(f"Unsupported symbol: {symbol}")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if self._holdings.get(symbol, 0.0) < quantity:
            raise ValueError("Insufficient shares to sell")
        price = get_share_price(symbol)
        total_proceeds = price * quantity
        current_qty = self._holdings[symbol]
        avg_cost = self._cost_basis[symbol] / current_qty
        self._balance += total_proceeds
        self._holdings[symbol] = current_qty - quantity
        remaining_cost = self._cost_basis[symbol] - (avg_cost * quantity)
        if self._holdings[symbol] == 0:
            del self._holdings[symbol]
            del self._cost_basis[symbol]
        else:
            self._cost_basis[symbol] = remaining_cost
        return self._record_transaction(
            TransactionType.SELL, symbol, quantity, price, total_proceeds
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def get_holdings(self) -> list[Holding]:
        holdings = []
        for symbol, quantity in self._holdings.items():
            avg_cost = self._cost_basis[symbol] / quantity
            holdings.append(Holding(symbol, quantity, avg_cost))
        return holdings

    def get_portfolio_value(self) -> float:
        total = 0.0
        for symbol, quantity in self._holdings.items():
            total += quantity * get_share_price(symbol)
        return total

    def get_profit_or_loss(self) -> float:
        return (self._balance + self.get_portfolio_value()) - self._initial_deposit

    def get_holdings_at(self, timestamp: datetime) -> list[Holding]:
        return Replay(self).holdings_at(timestamp)

    def get_profit_or_loss_at(self, timestamp: datetime) -> float:
        replay = Replay(self)
        balance, holdings_value = replay.state_at(timestamp)
        return (balance + holdings_value) - self._initial_deposit

    def get_transactions(self) -> list[Transaction]:
        return sorted(self._transactions, key=lambda t: t.timestamp)

    def get_transactions_in_range(
        self,
        start: datetime | None,
        end: datetime | None,
    ) -> list[Transaction]:
        filtered = []
        for tx in self.get_transactions():
            if start is not None and tx.timestamp < start:
                continue
            if end is not None and tx.timestamp > end:
                continue
            filtered.append(tx)
        return filtered

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _record_transaction(
        self,
        type_: TransactionType,
        symbol: str | None,
        quantity: float,
        price: float,
        amount: float,
    ) -> Transaction:
        self._tx_counter += 1
        tx_id = f"TX{self._tx_counter:04d}"
        tx = Transaction(
            id=tx_id,
            type=type_,
            symbol=symbol,
            quantity=quantity,
            price=price,
            amount=amount,
            timestamp=datetime.now(timezone.utc),
            balance_after=self._balance,
        )
        self._transactions.append(tx)
        return tx


class Replay:
    """Replays a transaction history to reconstruct an earlier account state."""

    def __init__(self, account: Account) -> None:
        self._transactions = sorted(
            account.transactions, key=lambda t: t.timestamp
        )

    def holdings_at(self, timestamp: datetime) -> list[Holding]:
        holdings, cost_basis = self._state_at(timestamp)
        result = []
        for symbol, quantity in holdings.items():
            avg_cost = cost_basis.get(symbol, 0.0) / quantity
            result.append(Holding(symbol, quantity, avg_cost))
        return result

    def state_at(self, timestamp: datetime) -> tuple[float, float]:
        holdings, _ = self._state_at(timestamp)
        value = 0.0
        for symbol, quantity in holdings.items():
            value += quantity * self._price_at(symbol, timestamp)
        return self._balance_at(timestamp), value

    def _balance_at(self, timestamp: datetime) -> float:
        balance = 0.0
        for tx in self._transactions:
            if tx.timestamp > timestamp:
                break
            if tx.type == TransactionType.DEPOSIT:
                balance += tx.amount
            elif tx.type == TransactionType.WITHDRAWAL:
                balance -= tx.amount
            elif tx.type == TransactionType.BUY:
                balance -= tx.amount
            elif tx.type == TransactionType.SELL:
                balance += tx.amount
        return balance

    def _state_at(
        self, timestamp: datetime
    ) -> tuple[dict[str, float], dict[str, float]]:
        holdings: dict[str, float] = {}
        cost_basis: dict[str, float] = {}
        for tx in self._transactions:
            if tx.timestamp > timestamp:
                break
            if tx.type == TransactionType.BUY:
                holdings[tx.symbol] = holdings.get(tx.symbol, 0.0) + tx.quantity
                cost_basis[tx.symbol] = (
                    cost_basis.get(tx.symbol, 0.0) + tx.amount
                )
            elif tx.type == TransactionType.SELL:
                qty = holdings.get(tx.symbol, 0.0)
                avg = cost_basis.get(tx.symbol, 0.0) / qty if qty else 0.0
                holdings[tx.symbol] = qty - tx.quantity
                cost_basis[tx.symbol] = cost_basis.get(tx.symbol, 0.0) - (
                    avg * tx.quantity
                )
                if holdings[tx.symbol] <= 0:
                    del holdings[tx.symbol]
                    if tx.symbol in cost_basis:
                        del cost_basis[tx.symbol]
        return holdings, cost_basis

    def _price_at(self, symbol: str, timestamp: datetime) -> float:
        """Most recent recorded price for the symbol at/before timestamp.

        Since we cannot query historical prices, recorded transaction prices
        are the best available estimate. Falls back to current price.
        """
        last_price = None
        for tx in self._transactions:
            if tx.timestamp > timestamp:
                break
            if (
                tx.symbol == symbol
                and tx.type in (TransactionType.BUY, TransactionType.SELL)
            ):
                last_price = tx.price
        if last_price is not None:
            return last_price
        return get_share_price(symbol)
