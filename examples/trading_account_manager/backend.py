import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from prices import get_share_price

class TransactionType(Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"

@dataclass
class Transaction:
    transaction_id: str
    account_id: str
    transaction_type: TransactionType
    timestamp: datetime
    symbol: str | None
    quantity: int | None
    price: float | None
    cash_amount: float
    description: str

@dataclass
class Account:
    account_id: str
    owner_name: str
    created_at: datetime
    transactions: list[Transaction] = field(default_factory=list)

class AccountService:
    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _validate_positive_amount(self, amount: float, field_name: str = "amount") -> None:
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise ValueError(f"{field_name} must be greater than 0")

    def _validate_positive_quantity(self, quantity: int) -> None:
        if not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")

    def _normalize_symbol(self, symbol: str) -> str:
        if not symbol or not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("Symbol must be a non-empty string")
        return symbol.strip().upper()

    def _create_transaction(
        self,
        account_id: str,
        transaction_type: TransactionType,
        symbol: str | None,
        quantity: int | None,
        price: float | None,
        cash_amount: float,
        description: str,
    ) -> Transaction:
        return Transaction(
            transaction_id=str(uuid.uuid4()),
            account_id=account_id,
            transaction_type=transaction_type,
            timestamp=self._utc_now(),
            symbol=symbol,
            quantity=quantity,
            price=price,
            cash_amount=cash_amount,
            description=description,
        )

    def _transactions_as_of(
        self,
        account: Account,
        as_of: datetime | None = None,
    ) -> list[Transaction]:
        if as_of is None:
            return account.transactions
        return [t for t in account.transactions if t.timestamp <= as_of]

    def create_account(self, owner_name: str, initial_deposit: float = 0.0) -> Account:
        if not owner_name or not isinstance(owner_name, str) or not owner_name.strip():
            raise ValueError("owner_name cannot be blank")
        if not isinstance(initial_deposit, (int, float)) or initial_deposit < 0:
            raise ValueError("initial_deposit must be >= 0")

        account_id = str(uuid.uuid4())
        account = Account(
            account_id=account_id,
            owner_name=owner_name.strip(),
            created_at=self._utc_now(),
        )
        self.accounts[account_id] = account

        if initial_deposit > 0:
            self.deposit(account_id, initial_deposit)

        return account

    def get_account(self, account_id: str) -> Account:
        if account_id not in self.accounts:
            raise ValueError("Account not found")
        return self.accounts[account_id]

    def list_accounts(self) -> list[Account]:
        return sorted(list(self.accounts.values()), key=lambda a: a.created_at)

    def deposit(self, account_id: str, amount: float) -> Transaction:
        account = self.get_account(account_id)
        self._validate_positive_amount(amount)
        
        transaction = self._create_transaction(
            account_id=account_id,
            transaction_type=TransactionType.DEPOSIT,
            symbol=None,
            quantity=None,
            price=None,
            cash_amount=amount,
            description=f"Deposit of {amount:.2f}",
        )
        account.transactions.append(transaction)
        return transaction

    def withdraw(self, account_id: str, amount: float) -> Transaction:
        account = self.get_account(account_id)
        self._validate_positive_amount(amount)
        
        current_cash = self.get_cash_balance(account_id)
        if amount > current_cash:
            raise ValueError("Insufficient cash balance")

        transaction = self._create_transaction(
            account_id=account_id,
            transaction_type=TransactionType.WITHDRAWAL,
            symbol=None,
            quantity=None,
            price=None,
            cash_amount=amount,
            description=f"Withdrawal of {amount:.2f}",
        )
        account.transactions.append(transaction)
        return transaction

    def buy_shares(self, account_id: str, symbol: str, quantity: int) -> Transaction:
        account = self.get_account(account_id)
        normalized_symbol = self._normalize_symbol(symbol)
        self._validate_positive_quantity(quantity)
        
        price = get_share_price(normalized_symbol)
        cost = price * quantity
        current_cash = self.get_cash_balance(account_id)
        
        if cost > current_cash:
            raise ValueError("Insufficient cash balance for purchase")

        transaction = self._create_transaction(
            account_id=account_id,
            transaction_type=TransactionType.BUY,
            symbol=normalized_symbol,
            quantity=quantity,
            price=price,
            cash_amount=cost,
            description=f"Buy {quantity} {normalized_symbol} @ {price:.2f}",
        )
        account.transactions.append(transaction)
        return transaction

    def sell_shares(self, account_id: str, symbol: str, quantity: int) -> Transaction:
        account = self.get_account(account_id)
        normalized_symbol = self._normalize_symbol(symbol)
        self._validate_positive_quantity(quantity)
        
        holdings = self.get_holdings(account_id)
        currently_held = holdings.get(normalized_symbol, 0)
        
        if quantity > currently_held:
            raise ValueError("Insufficient shares for sale")

        price = get_share_price(normalized_symbol)
        proceeds = price * quantity

        transaction = self._create_transaction(
            account_id=account_id,
            transaction_type=TransactionType.SELL,
            symbol=normalized_symbol,
            quantity=quantity,
            price=price,
            cash_amount=proceeds,
            description=f"Sell {quantity} {normalized_symbol} @ {price:.2f}",
        )
        account.transactions.append(transaction)
        return transaction

    def get_cash_balance(self, account_id: str, as_of: datetime | None = None) -> float:
        account = self.get_account(account_id)
        transactions = self._transactions_as_of(account, as_of)
        
        balance = 0.0
        for t in transactions:
            if t.transaction_type == TransactionType.DEPOSIT:
                balance += t.cash_amount
            elif t.transaction_type == TransactionType.WITHDRAWAL:
                balance -= t.cash_amount
            elif t.transaction_type == TransactionType.BUY:
                balance -= t.cash_amount
            elif t.transaction_type == TransactionType.SELL:
                balance += t.cash_amount
                
        return round(balance, 2)

    def get_holdings(self, account_id: str, as_of: datetime | None = None) -> dict[str, int]:
        account = self.get_account(account_id)
        transactions = self._transactions_as_of(account, as_of)
        
        holdings: dict[str, int] = {}
        for t in transactions:
            if t.transaction_type in (TransactionType.BUY, TransactionType.SELL):
                sym = t.symbol
                if sym is not None:
                    if t.transaction_type == TransactionType.BUY:
                        holdings[sym] = holdings.get(sym, 0) + (t.quantity or 0)
                    elif t.transaction_type == TransactionType.SELL:
                        holdings[sym] = holdings.get(sym, 0) - (t.quantity or 0)
                        
        return {sym: qty for sym, qty in holdings.items() if qty > 0}

    def get_holdings_report(self, account_id: str, as_of: datetime | None = None) -> list[dict[str, object]]:
        holdings = self.get_holdings(account_id, as_of)
        report = []
        for sym in sorted(holdings.keys()):
            qty = holdings[sym]
            price = get_share_price(sym)
            market_value = round(qty * price, 2)
            report.append({
                "symbol": sym,
                "quantity": qty,
                "current_price": price,
                "market_value": market_value,
            })
        return report

    def get_portfolio_value(self, account_id: str, as_of: datetime | None = None) -> float:
        holdings = self.get_holdings(account_id, as_of)
        total_value = 0.0
        for sym, qty in holdings.items():
            price = get_share_price(sym)
            total_value += qty * price
        return round(total_value, 2)

    def get_total_account_value(self, account_id: str, as_of: datetime | None = None) -> float:
        cash = self.get_cash_balance(account_id, as_of)
        portfolio = self.get_portfolio_value(account_id, as_of)
        return round(cash + portfolio, 2)

    def get_profit_loss(self, account_id: str, as_of: datetime | None = None) -> float:
        account = self.get_account(account_id)
        transactions = self._transactions_as_of(account, as_of)
        
        total_deposits = sum(t.cash_amount for t in transactions if t.transaction_type == TransactionType.DEPOSIT)
        total_withdrawals = sum(t.cash_amount for t in transactions if t.transaction_type == TransactionType.WITHDRAWAL)
        
        total_value = self.get_total_account_value(account_id, as_of)
        
        pl = total_value + total_withdrawals - total_deposits
        return round(pl, 2)

    def get_profit_loss_percent(self, account_id: str, as_of: datetime | None = None) -> float:
        account = self.get_account(account_id)
        transactions = self._transactions_as_of(account, as_of)
        
        total_deposits = sum(t.cash_amount for t in transactions if t.transaction_type == TransactionType.DEPOSIT)
        if total_deposits == 0:
            return 0.0
            
        pl = self.get_profit_loss(account_id, as_of)
        return round((pl / total_deposits) * 100, 2)

    def list_transactions(self, account_id: str, as_of: datetime | None = None) -> list[Transaction]:
        account = self.get_account(account_id)
        transactions = self._transactions_as_of(account, as_of)
        return sorted(transactions, key=lambda t: t.timestamp)

    def get_transaction_report(self, account_id: str, as_of: datetime | None = None) -> list[dict[str, object]]:
        transactions = self.list_transactions(account_id, as_of)
        report = []
        for t in transactions:
            report.append({
                "timestamp": t.timestamp.isoformat(),
                "type": t.transaction_type.value,
                "symbol": t.symbol if t.symbol is not None else "",
                "quantity": t.quantity if t.quantity is not None else "",
                "price": t.price if t.price is not None else "",
                "cash_amount": round(t.cash_amount, 2),
                "description": t.description,
            })
        return report

    def get_account_summary(self, account_id: str, as_of: datetime | None = None) -> dict[str, object]:
        account = self.get_account(account_id)
        return {
            "account_id": account.account_id,
            "owner_name": account.owner_name,
            "cash_balance": self.get_cash_balance(account_id, as_of),
            "portfolio_value": self.get_portfolio_value(account_id, as_of),
            "total_account_value": self.get_total_account_value(account_id, as_of),
            "profit_loss": self.get_profit_loss(account_id, as_of),
            "profit_loss_percent": self.get_profit_loss_percent(account_id, as_of),
            "holdings": self.get_holdings(account_id, as_of),
        }
