# Account Management System — Design Document

## Overview

A single-user account management system for a trading simulation platform. The system consists of three files:

| File | Purpose |
|---|---|
| `account_system.py` | Backend: core domain logic, pure Python standard library |
| `app.py` | Frontend: Gradio UI wrapping the backend |
| `test_account_system.py` | Unit tests: pytest-style tests for the backend |

---

## 1. Backend Module: `account_system.py`

### 1.1 Standalone Function

```
get_share_price(symbol: str) -> float
```

- Test implementation returning fixed prices:
  - `"AAPL"` → `150.0`
  - `"TSLA"` → `250.0`
  - `"GOOGL"` → `2800.0`
- Raises `ValueError` for unknown symbols.

---

### 1.2 Data Class: `Transaction`

A frozen dataclass (or namedtuple) with the following fields:

| Field | Type | Description |
|---|---|---|
| `timestamp` | `str` | ISO-8601 timestamp of when the transaction occurred |
| `txn_type` | `str` | One of: `"DEPOSIT"`, `"WITHDRAW"`, `"BUY"`, `"SELL"` |
| `symbol` | `str` or `None` | Share symbol; `None` for DEPOSIT/WITHDRAW |
| `quantity` | `int` or `None` | Number of shares; `None` for DEPOSIT/WITHDRAW |
| `price` | `float` or `None` | Price per share at time of trade; `None` for DEPOSIT/WITHDRAW |
| `amount` | `float` | Cash impact on the account (positive for DEPOSIT/SELL proceeds, negative for WITHDRAW/BUY cost) |

---

### 1.3 Custom Exception Classes

```
class InsufficientFundsError(Exception):
    """Raised when a withdrawal or purchase exceeds available cash balance."""
    pass

class InsufficientHoldingsError(Exception):
    """Raised when a sell order exceeds the current holdings of that symbol."""
    pass
```

---

### 1.4 Class: `Account`

Represents one user's account. Tracks cash balance, holdings, and transaction history.

#### Constructor

```
__init__(self, name: str) -> None
```

- `name`: account holder's name.
- Initialises cash balance to `0.0`, empty holdings dict (`{str: int}`), empty transactions list.

#### Methods

```
deposit(self, amount: float) -> None
```

- `amount` must be positive; raises `ValueError` otherwise.
- Adds `amount` to cash balance.
- Appends a `DEPOSIT` `Transaction` to history (symbol=None, quantity=None, price=None, amount=+amount).

```
withdraw(self, amount: float) -> None
```

- `amount` must be positive; raises `ValueError` otherwise.
- If `amount > cash_balance`, raises `InsufficientFundsError`.
- Deducts `amount` from cash balance.
- Appends a `WITHDRAW` `Transaction` (amount=-amount).

```
buy(self, symbol: str, quantity: int) -> None
```

- `quantity` must be positive; raises `ValueError` otherwise.
- Looks up `price = get_share_price(symbol)` (may raise `ValueError` for unknown symbol).
- `cost = price * quantity`.
- If `cost > cash_balance`, raises `InsufficientFundsError`.
- Deducts `cost` from cash balance.
- Increases `holdings[symbol]` by `quantity` (defaulting to 0 if not present).
- Appends a `BUY` `Transaction` (symbol=symbol, quantity=quantity, price=price, amount=-cost).

```
sell(self, symbol: str, quantity: int) -> None
```

- `quantity` must be positive; raises `ValueError` otherwise.
- Looks up `price = get_share_price(symbol)`.
- If `holdings.get(symbol, 0) < quantity`, raises `InsufficientHoldingsError`.
- `proceeds = price * quantity`.
- Adds `proceeds` to cash balance.
- Decreases `holdings[symbol]` by `quantity`; removes the key if holdings reach 0.
- Appends a `SELL` `Transaction` (symbol=symbol, quantity=quantity, price=price, amount=+proceeds).

```
get_holdings(self) -> dict[str, int]
```

- Returns a **copy** of the current holdings dict (shares held per symbol, only symbols with >0 quantity).

```
get_balance(self) -> float
```

- Returns the current cash balance.

```
get_portfolio_value(self) -> float
```

- Computes: `cash_balance + sum(get_share_price(sym) * qty for sym, qty in holdings.items())`.
- Unknown symbols in holdings should not occur under normal operation; if `get_share_price` raises, let it propagate.

```
get_total_deposits(self) -> float
```

- Sums `txn.amount` for all transactions where `txn_type == "DEPOSIT"`.

```
get_profit_loss(self) -> float
```

- Returns `get_portfolio_value() - get_total_deposits()`.
- Positive = profit, negative = loss.

```
get_transactions(self) -> list[Transaction]
```

- Returns a **copy** of the full transaction history list, in chronological order.

---

## 2. Frontend Module: `app.py`

A Gradio `Blocks` interface that wraps a single `Account` instance (created at session start).

### UI Structure

The UI has these sections laid out vertically:

| Section | Components |
|---|---|
| **Account Info** | Textbox: account name (on create); Button: "Create Account"; Display: status message |
| **Deposit / Withdraw** | Number input: amount; Button: "Deposit"; Button: "Withdraw"; Display: result message + updated balance |
| **Buy / Sell** | Textbox: symbol; Number input: quantity; Button: "Buy"; Button: "Sell"; Display: result message |
| **Portfolio Summary** | Display: cash balance, holdings table, portfolio value, P&L; Button: "Refresh" |
| **Transaction History** | Dataframe or JSON display of all transactions; Button: "Refresh" |

### Behaviour

- All buttons call corresponding backend methods on the shared `Account` object.
- Errors (e.g. insufficient funds) are caught and shown as error messages in the UI.
- The Gradio app must launch with `demo.launch()` at the bottom.
- State is maintained via `gr.State()` holding the `Account` instance (or `None` before creation).

---

## 3. Unit Tests: `test_account_system.py`

Uses `pytest` (standard-library `unittest` is also acceptable). Must cover:

### 3.1 `get_share_price`
- Returns correct fixed price for AAPL, TSLA, GOOGL.
- Raises `ValueError` for unknown symbol (e.g. `"ZZZZ"`).
- Case sensitivity: test that exact uppercase symbols work; behaviour for lowercase is not defined — test that the fixed implementation is case-sensitive (i.e. `"aapl"` raises).

### 3.2 `Account` — Creation & Cash Operations
- New account has zero balance, empty holdings, empty transactions.
- `deposit(100)` updates balance to 100, adds one DEPOSIT transaction.
- `deposit(0)` or `deposit(-50)` raises `ValueError`.
- `withdraw(50)` updates balance to 50 (after a 100 deposit), adds WITHDRAW transaction.
- `withdraw` more than balance raises `InsufficientFundsError`.
- `withdraw(0)` or `withdraw(-10)` raises `ValueError`.

### 3.3 `Account` — Buy
- Successful buy: balance decreases by `price * qty`, holdings updated, BUY transaction recorded.
- Buy with unknown symbol: `ValueError` propagates from `get_share_price`.
- Buy with zero or negative quantity raises `ValueError`.
- Buy that exceeds cash balance raises `InsufficientFundsError`; state unchanged.
- Multiple buys of the same symbol accumulate quantity correctly.

### 3.4 `Account` — Sell
- Successful sell: balance increases by `price * qty`, holdings decreased, SELL transaction recorded.
- Sell more than holdings raises `InsufficientHoldingsError`; state unchanged.
- Sell exact holdings: symbol removed from holdings dict.
- Sell with zero or negative quantity raises `ValueError`.

### 3.5 `Account` — Queries
- `get_holdings` returns a copy (mutating the returned dict does not affect the account).
- `get_balance` reflects all cash movements.
- `get_portfolio_value` = cash + sum(holdings * current price).
- `get_total_deposits` sums only DEPOSIT transactions.
- `get_profit_loss` = portfolio value - total deposits.
- `get_transactions` returns a copy (mutating the returned list does not affect the account).

### 3.6 Integration / Scenario
- Full workflow: create → deposit → buy AAPL → buy TSLA → sell some AAPL → check holdings, value, P&L, transactions.
- Edge case: sell all shares, verify symbol removed from holdings.

---

## 4. Delegation Plan (to be executed in sequence)

| Step | Coworker | Task |
|---|---|---|
| 1 | `backend_engineer` | Implement `account_system.py` per §1 |
| 2 | `test_engineer` | Implement `test_account_system.py` per §3 |
| 3 | `frontend_engineer` | Implement `app.py` per §2, verify it opens |
| 4 | `qa_inspector` | Review all three files, report findings |
| 5+ | (if needed) | Fixes delegated to the owning engineer, re-verified by QA |

---

This design is now ready for implementation delegation.