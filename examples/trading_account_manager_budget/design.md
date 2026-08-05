# Detailed Design: Trading Simulation Account Management System

## 1. System Overview

A Gradio-based web application for managing trading simulation accounts. Users can create accounts, deposit/withdraw funds, buy/sell shares, and view their portfolio holdings, profit/loss, and transaction history. The system enforces balance constraints and share-availability constraints.

---

## 2. File Structure

All files live in the same directory (no subdirectories):

| File | Owner | Purpose |
|---|---|---|
| `account.py` | backend_engineer | Core account model, transaction recording, validation logic, share-price stub |
| `app.py` | frontend_engineer | Gradio 6 Blocks UI with tabs for each operation |
| `test_account.py` | test_engineer | Unit tests for all backend classes and methods |

---

## 3. Backend Design (`account.py`)

### 3.1 Constants / Module-level

```
SUPPORTED_SYMBOLS = ("AAPL", "TSLA", "GOOGL")
PRICES = {"AAPL": 150.0, "TSLA": 200.0, "GOOGL": 120.0}
```

### 3.2 Function: `get_share_price`

```python
def get_share_price(symbol: str) -> float
```
- **Returns** the current price of a share for the given symbol.
- For this simulation, returns fixed prices from the `PRICES` dict for AAPL, TSLA, GOOGL.
- Raises `ValueError` for unsupported symbols.

### 3.3 Enum: `TransactionType`

```python
class TransactionType(Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"
```

### 3.4 Dataclass: `Transaction`

```python
@dataclass
class Transaction:
    id: str
    type: TransactionType
    symbol: str | None       # None for deposit/withdrawal
    quantity: float          # shares for BUY/SELL, 0 for deposit/withdrawal
    price: float             # share price at time of trade, 0 for deposit/withdrawal
    amount: float            # dollar amount for deposit/withdrawal; total cost/proceeds for trades
    timestamp: datetime      # UTC time of transaction
    balance_after: float     # account balance after this transaction
```

### 3.5 Dataclass: `Holding`

```python
@dataclass
class Holding:
    symbol: str
    quantity: float
    average_cost: float       # weighted average purchase price per share
```

### 3.6 Class: `Account`

```python
class Account:
    def __init__(self, account_id: str, owner_name: str) -> None
```
- **Attributes** (all private, exposed via properties):
  - `_account_id: str`
  - `_owner_name: str`
  - `_balance: float` — initialized to `0.0`
  - `_initial_deposit: float` — initialized to `0.0`, set when first deposit is made
  - `_holdings: dict[str, float]` — maps symbol → total quantity held
  - `_cost_basis: dict[str, float]` — maps symbol → total cost paid (for avg cost calculation)
  - `_transactions: list[Transaction]` — chronologically ordered list
  - `_tx_counter: int` — internal counter for generating unique transaction IDs

#### Properties

```python
@property
def account_id(self) -> str

@property
def owner_name(self) -> str

@property
def balance(self) -> float

@property
def initial_deposit(self) -> float

@property
def transactions(self) -> list[Transaction]
```

#### Methods

```python
def deposit(self, amount: float) -> Transaction
```
- **Preconditions**: `amount > 0`, else raise `ValueError("Deposit amount must be positive")`.
- Sets `_initial_deposit` on the **first** deposit only.
- Increments `_balance` by `amount`.
- Records a `Transaction` with `type=DEPOSIT`, `symbol=None`, `quantity=0`, `price=0`, `amount=amount`.
- Returns the `Transaction`.

```python
def withdraw(self, amount: float) -> Transaction
```
- **Preconditions**: `amount > 0`, else raise `ValueError("Withdrawal amount must be positive")`.
- **Preconditions**: `amount <= self._balance`, else raise `ValueError("Insufficient funds for withdrawal")`.
- Decrements `_balance` by `amount`.
- Records a `Transaction` with `type=WITHDRAWAL`, `symbol=None`, `quantity=0`, `price=0`, `amount=amount`.
- Returns the `Transaction`.

```python
def buy_shares(self, symbol: str, quantity: float) -> Transaction
```
- **Preconditions**: `symbol` in `SUPPORTED_SYMBOLS`, else raise `ValueError(f"Unsupported symbol: {symbol}")`.
- **Preconditions**: `quantity > 0`, else raise `ValueError("Quantity must be positive")`.
- Fetches price via `get_share_price(symbol)`.
- Computes `total_cost = price * quantity`.
- **Preconditions**: `total_cost <= self._balance`, else raise `ValueError("Insufficient funds to buy shares")`.
- Decrements `_balance` by `total_cost`.
- Updates `_holdings[symbol] += quantity` and `_cost_basis[symbol] += total_cost`.
- Records a `Transaction` with `type=BUY`, `symbol=symbol`, `quantity=quantity`, `price=price`, `amount=total_cost`.
- Returns the `Transaction`.

```python
def sell_shares(self, symbol: str, quantity: float) -> Transaction
```
- **Preconditions**: `symbol` in `SUPPORTED_SYMBOLS`, else raise `ValueError(f"Unsupported symbol: {symbol}")`.
- **Preconditions**: `quantity > 0`, else raise `ValueError("Quantity must be positive")`.
- **Preconditions**: `self._holdings.get(symbol, 0) >= quantity`, else raise `ValueError("Insufficient shares to sell")`.
- Fetches price via `get_share_price(symbol)`.
- Computes `total_proceeds = price * quantity`.
- Increments `_balance` by `total_proceeds`.
- Updates `_holdings[symbol] -= quantity`; if reaches 0, remove key.
- Updates `_cost_basis[symbol]` proportionally (reduce by `avg_cost * quantity`); if reaches 0, remove key.
- Records a `Transaction` with `type=SELL`, `symbol=symbol`, `quantity=quantity`, `price=price`, `amount=total_proceeds`.
- Returns the `Transaction`.

```python
def get_holdings(self) -> list[Holding]
```
- Returns a list of `Holding` objects for each symbol where `quantity > 0`.
- Computes `average_cost = _cost_basis[symbol] / _holdings[symbol]`.

```python
def get_portfolio_value(self) -> float
```
- Sums `quantity * get_share_price(symbol)` for every holding.
- Returns the total current portfolio value.

```python
def get_profit_or_loss(self) -> float
```
- Computes `(self._balance + self.get_portfolio_value()) - self._initial_deposit`.
- A positive value = profit; negative = loss.

```python
def get_profit_or_loss_at(self, timestamp: datetime) -> float
```
- Replays transactions up to and including `timestamp`.
- Computes the balance and holdings value at that point using the **historical transaction prices** (not current prices, since we cannot query historical prices — we use the recorded transaction prices as the best available estimate).
- Returns `(balance_at + holdings_value_at) - initial_deposit`.

```python
def get_holdings_at(self, timestamp: datetime) -> list[Holding]
```
- Replays transactions up to and including `timestamp` to reconstruct holdings at that point.
- Returns list of `Holding` objects.

```python
def get_transactions(self) -> list[Transaction]
```
- Returns a copy of the full transaction list (sorted by timestamp ascending).

```python
def get_transactions_in_range(self, start: datetime | None, end: datetime | None) -> list[Transaction]
```
- Filters transactions to those within `[start, end]` (inclusive). `None` means unbounded on that side.
- Returns filtered list.

```python
def _record_transaction(self, type: TransactionType, symbol: str | None, quantity: float, price: float, amount: float) -> Transaction
```
- Internal helper. Generates a unique ID (e.g., `f"TX{self._tx_counter:04d}"`), increments counter, creates a `Transaction` with `balance_after=self._balance`, `timestamp=datetime.now(timezone.utc)`, appends to `_transactions`, returns it.

### 3.7 Error Handling Strategy

All constraint violations raise `ValueError` with a descriptive message. The frontend will catch these and display them to the user. No custom exception classes are needed.

---

## 4. Frontend Design (`app.py`)

### 4.1 Gradio 6 API Guidance for the Frontend Engineer

> **IMPORTANT — Gradio 6 Breaking Changes:**
>
> 1. **`theme`, `css`, `css_paths`, `js`, `head`, `head_paths` parameters have moved from `gr.Blocks()` constructor to `demo.launch()`**. Passing them to `gr.Blocks()` will emit a `UserWarning` and be ignored. Example:
>    ```python
>    # WRONG (Gradio 5 style)
>    with gr.Blocks(theme=gr.themes.Soft()) as demo:
>        ...
>    demo.launch()
>
>    # CORRECT (Gradio 6)
>    with gr.Blocks() as demo:
>        ...
>    demo.launch(theme=gr.themes.Soft())
>    ```
>
> 2. **`show_api` parameter in `launch()` is replaced by `footer_links`**. Use `footer_links=["gradio", "settings"]` to control footer links. `show_api=False` → `footer_links=["gradio", "settings"]` or `footer_links=[]` to hide all.
>
> 3. **Component constructors** still use `value`, `label`, `interactive`, `visible` kwargs as in Gradio 5. `gr.Number` has `precision`. `gr.Dataframe` takes `value`, `row_count`, `column_count`, `headers`, `datatype`, `interactive`.
>
> 4. **Event handlers**: Use `btn.click(fn=..., inputs=[...], outputs=[...])` or the newer `gr.on(triggers=[btn.click, ...], fn=..., inputs=[...], outputs=[...])` for multi-trigger bindings.
>
> 5. **`gr.State`** is used for session-level persistence. Pass it as both input and output to event handlers to maintain state across interactions. Example:
>    ```python
>    words = gr.State([])
>    textbox.submit(fn, inputs=[textbox, words], outputs=[number, words])
>    ```
>
> 6. **`gr.Tabs()` + `gr.Tab("label")`** context manager for tabbed layouts.
>
> 7. **`demo.launch()`** signature: `demo.launch(theme=None, css=None, footer_links=None, ...)`. App-level parameters go here.

### 4.2 Application Layout

The app uses `gr.Blocks` with `gr.Tabs()` containing five tabs:

```
┌─────────────────────────────────────────────────────────┐
│  Trading Simulation Platform                            │
│  [Create Account] [Deposit/Withdraw] [Buy/Sell]          │
│  [Portfolio & P/L] [Transaction History]                 │
└─────────────────────────────────────────────────────────┘
```

### 4.3 Session State

```python
account_state = gr.State(value=None)  # holds an Account instance or None
```

All tab event handlers receive `account_state` as an input and return an updated `account_state` as an output (plus UI updates).

### 4.4 Tab 1: Create Account

**Components:**
- `owner_name_input = gr.Textbox(label="Owner Name", placeholder="Enter account owner name")`
- `create_btn = gr.Button("Create Account", variant="primary")`
- `create_status = gr.Textbox(label="Status", interactive=False)`

**Handler:**
```python
def create_account(owner_name: str, account: Account | None) -> tuple[Account | None, str]
```
- If `account` is not None, return it unchanged with status "Account already exists for {owner_name}".
- If `owner_name` is empty, return `None, "Please enter an owner name"`.
- Creates `Account(account_id=uuid4().hex[:8], owner_name=owner_name)`.
- Returns `(account, f"Account created successfully for {owner_name}")`.

**Event binding:**
```python
create_btn.click(
    fn=create_account,
    inputs=[owner_name_input, account_state],
    outputs=[account_state, create_status]
)
```

### 4.5 Tab 2: Deposit / Withdraw

**Components:**
- `deposit_amount = gr.Number(label="Deposit Amount ($)", value=0, precision=2)`
- `deposit_btn = gr.Button("Deposit")`
- `withdraw_amount = gr.Number(label="Withdraw Amount ($)", value=0, precision=2)`
- `withdraw_btn = gr.Button("Withdraw")`
- `balance_display = gr.Textbox(label="Current Balance", interactive=False)`
- `dw_status = gr.Textbox(label="Status", interactive=False)`

**Handlers:**
```python
def handle_deposit(amount: float, account: Account | None) -> tuple[Account | None, str, str]
```
- If account is None: return `(None, "", "No account found. Please create an account first.")`.
- Calls `account.deposit(amount)`, catches `ValueError`.
- Returns `(account, f"${account.balance:.2f}", status_message)`.

```python
def handle_withdraw(amount: float, account: Account | None) -> tuple[Account | None, str, str]
```
- If account is None: return `(None, "", "No account found. Please create an account first.")`.
- Calls `account.withdraw(amount)`, catches `ValueError`.
- Returns `(account, f"${account.balance:.2f}", status_message)`.

**Event bindings:**
```python
deposit_btn.click(fn=handle_deposit, inputs=[deposit_amount, account_state], outputs=[account_state, balance_display, dw_status])
withdraw_btn.click(fn=handle_withdraw, inputs=[withdraw_amount, account_state], outputs=[account_state, balance_display, dw_status])
```

### 4.6 Tab 3: Buy / Sell Shares

**Components:**
- `trade_symbol = gr.Dropdown(choices=["AAPL", "TSLA", "GOOGL"], label="Symbol")`
- `trade_qty = gr.Number(label="Quantity (shares)", value=1, precision=4)`
- `trade_price_display = gr.Textbox(label="Current Price", interactive=False)`
- `buy_btn = gr.Button("Buy Shares", variant="primary")`
- `sell_btn = gr.Button("Sell Shares")`
- `trade_status = gr.Textbox(label="Status", interactive=False)`
- `trade_balance_display = gr.Textbox(label="Current Balance", interactive=False)`

**Handlers:**
```python
def get_price_for_display(symbol: str) -> str
```
- Returns `f"${get_share_price(symbol):.2f}"` or empty string if symbol is None.

```python
def handle_buy(symbol: str, quantity: float, account: Account | None) -> tuple[Account | None, str, str]
```
- If account is None: return error message.
- Calls `account.buy_shares(symbol, quantity)`, catches `ValueError`.
- Returns `(account, f"${account.balance:.2f}", status_message)`.

```python
def handle_sell(symbol: str, quantity: float, account: Account | None) -> tuple[Account | None, str, str]
```
- If account is None: return error message.
- Calls `account.sell_shares(symbol, quantity)`, catches `ValueError`.
- Returns `(account, f"${account.balance:.2f}", status_message)`.

**Event bindings:**
```python
trade_symbol.change(fn=get_price_for_display, inputs=trade_symbol, outputs=trade_price_display)
buy_btn.click(fn=handle_buy, inputs=[trade_symbol, trade_qty, account_state], outputs=[account_state, trade_balance_display, trade_status])
sell_btn.click(fn=handle_sell, inputs=[trade_symbol, trade_qty, account_state], outputs=[account_state, trade_balance_display, trade_status])
```

### 4.7 Tab 4: Portfolio & Profit/Loss

**Components:**
- `portfolio_refresh_btn = gr.Button("Refresh Portfolio")`
- `holdings_df = gr.Dataframe(headers=["Symbol", "Quantity", "Avg Cost", "Current Price", "Market Value"], interactive=False)`
- `portfolio_value_display = gr.Textbox(label="Total Portfolio Value", interactive=False)`
- `balance_pl_display = gr.Textbox(label="Current Cash Balance", interactive=False)`
- `pl_display = gr.Textbox(label="Total Profit / Loss", interactive=False)`
- `as_of_datetime = gr.Textbox(label="As-of Timestamp (ISO format, leave blank for now)", placeholder="2024-01-15T10:00:00")`
- `historical_btn = gr.Button("Get Historical Snapshot")`
- `historical_holdings_df = gr.Dataframe(headers=["Symbol", "Quantity", "Avg Cost"], interactive=False)`
- `historical_pl_display = gr.Textbox(label="Historical Profit/Loss", interactive=False)`
- `portfolio_status = gr.Textbox(label="Status", interactive=False)`

**Handlers:**
```python
def refresh_portfolio(account: Account | None) -> tuple[list[list], str, str, str, str]
```
- If account is None: return empty dataframe + "No account found" status.
- Calls `account.get_holdings()`, builds rows: `[symbol, quantity, avg_cost, current_price, market_value]`.
- Calls `account.get_portfolio_value()`, `account.balance`, `account.get_profit_or_loss()`.
- Returns `(rows, portfolio_value_str, balance_str, pl_str, status)`.

```python
def historical_snapshot(as_of: str, account: Account | None) -> tuple[list[list], str, str]
```
- If account is None: return error.
- Parses `as_of` as ISO datetime (catch `ValueError`).
- Calls `account.get_holdings_at(timestamp)` and `account.get_profit_or_loss_at(timestamp)`.
- Returns `(holdings_rows, pl_str, status)`.

**Event bindings:**
```python
portfolio_refresh_btn.click(fn=refresh_portfolio, inputs=[account_state], outputs=[holdings_df, portfolio_value_display, balance_pl_display, pl_display, portfolio_status])
historical_btn.click(fn=historical_snapshot, inputs=[as_of_datetime, account_state], outputs=[historical_holdings_df, historical_pl_display, portfolio_status])
```

### 4.8 Tab 5: Transaction History

**Components:**
- `tx_refresh_btn = gr.Button("Refresh Transactions")`
- `tx_df = gr.Dataframe(headers=["ID", "Type", "Symbol", "Quantity", "Price", "Amount", "Timestamp", "Balance After"], interactive=False)`
- `tx_status = gr.Textbox(label="Status", interactive=False)`

**Handler:**
```python
def refresh_transactions(account: Account | None) -> tuple[list[list], str]
```
- If account is None: return empty list, "No account found".
- Calls `account.get_transactions()`, builds rows: `[id, type.value, symbol or "", quantity, price, amount, timestamp.isoformat(), balance_after]`.
- Returns `(rows, f"{len(txs)} transactions found")`.

**Event binding:**
```python
tx_refresh_btn.click(fn=refresh_transactions, inputs=[account_state], outputs=[tx_df, tx_status])
```

### 4.9 Launch

```python
demo.launch(
    theme=gr.themes.Soft(),
    footer_links=["gradio", "settings"]
)
```

---

## 5. Test Design (`test_account.py`)

The test engineer will use Python's built-in `unittest` framework (no third-party deps needed).

### 5.1 Test Classes & Cases

#### `class TestGetSharePrice(unittest.TestCase)`

| Test Method | Description |
|---|---|
| `test_known_symbols` | Asserts `get_share_price("AAPL") == 150.0`, `"TSLA" == 200.0`, `"GOOGL" == 120.0` |
| `test_unknown_symbol_raises` | Asserts `ValueError` for `"UNKNOWN"` |

#### `class TestAccountCreation(unittest.TestCase)`

| Test Method | Description |
|---|---|
| `test_create_account_defaults` | New account has balance 0, empty transactions, empty holdings |
| `test_account_properties` | `account_id` and `owner_name` match constructor args |

#### `class TestDeposit(unittest.TestCase)`

| Test Method | Description |
|---|---|
| `test_deposit_positive` | Depositing 1000 sets balance to 1000, records 1 DEPOSIT transaction, sets `initial_deposit` |
| `test_deposit_sets_initial_deposit_once` | Two deposits: `initial_deposit` stays at first deposit amount |
| `test_deposit_zero_raises` | `deposit(0)` raises `ValueError` |
| `test_deposit_negative_raises` | `deposit(-100)` raises `ValueError` |
| `test_transaction_recorded_correctly` | Transaction has correct type, amount, balance_after, timestamp |

#### `class TestWithdraw(unittest.TestCase)`

| Test Method | Description |
|---|---|
| `test_withdraw_sufficient` | Deposit 1000, withdraw 300 → balance 700, 2 transactions |
| `test_withdraw_exact_balance` | Deposit 500, withdraw 500 → balance 0 |
| `test_withdraw_insufficient_raises` | Deposit 100, withdraw 200 → `ValueError` |
| `test_withdraw_zero_raises` | `withdraw(0)` raises `ValueError` |
| `test_withdraw_negative_raises` | `withdraw(-50)` raises `ValueError` |
| `test_withdraw_no_deposit_raises` | Fresh account, withdraw 100 → `ValueError` (balance 0) |

#### `class TestBuyShares(unittest.TestCase)`

| Test Method | Description |
|---|---|
| `test_buy_success` | Deposit 10000, buy 10 AAPL → balance = 10000 - 1500, holding 10 AAPL |
| `test_buy_updates_holdings_and_cost_basis` | Buy AAPL at 150 ×10, then at 150 ×5 → holding 15, avg cost 150 |
| `test_buy_multiple_symbols` | Buy AAPL and TSLA → holdings dict has both |
| `test_buy_insufficient_funds_raises` | Deposit 100, try buy 1 AAPL (cost 150) → `ValueError` |
| `test_buy_invalid_symbol_raises` | `buy_shares("UNKNOWN", 1)` → `ValueError` |
| `test_buy_zero_qty_raises` | `buy_shares("AAPL", 0)` → `ValueError` |
| `test_buy_negative_qty_raises` | `buy_shares("AAPL", -5)` → `ValueError` |
| `test_buy_transaction_correct` | Verify Transaction fields: type=BUY, symbol, quantity, price, amount, balance_after |

#### `class TestSellShares(unittest.TestCase)`

| Test Method | Description |
|---|---|
| `test_sell_success` | Deposit, buy 10 AAPL, sell 5 → balance increases by 5×price, holding 5 |
| `test_sell_all_shares` | Buy 10, sell 10 → holding removed entirely, cost_basis removed |
| `test_sell_more_than_held_raises` | Buy 5, sell 10 → `ValueError` |
| `test_sell_without_holding_raises` | Fresh account (after deposit), sell 1 AAPL → `ValueError` |
| `test_sell_invalid_symbol_raises` | `sell_shares("UNKNOWN", 1)` → `ValueError` |
| `test_sell_zero_qty_raises` | `sell_shares("AAPL", 0)` → `ValueError` |
| `test_sell_negative_qty_raises` | `sell_shares("AAPL", -1)` → `ValueError` |
| `test_sell_transaction_correct` | Verify Transaction fields |
| `test_sell_updates_cost_basis_proportionally` | Buy 10 @ 150, sell 5 → cost_basis halved |

#### `class TestHoldingsAndPortfolioValue(unittest.TestCase)`

| Test Method | Description |
|---|---|
| `test_empty_holdings` | New account → `get_holdings()` returns `[]` |
| `test_holdings_after_buy` | Buy AAPL + TSLA → 2 holdings with correct quantity and avg cost |
| `test_holdings_avg_cost_weighted` | Buy 10 @ 150, buy 5 @ 150 → avg cost still 150 (single price scenario) |
| `test_portfolio_value_empty` | No holdings → portfolio value 0 |
| `test_portfolio_value_after_buys` | Buy 10 AAPL + 5 TSLA → value = 10×150 + 5×200 = 2500 |
| `test_portfolio_value_after_partial_sell` | Buy 10 AAPL, sell 3 → value = 7×150 |

#### `class TestProfitOrLoss(unittest.TestCase)`

| Test Method | Description |
|---|---|
| `test_pl_no_trades` | Deposit 1000 → P/L = 0 (balance 1000, no holdings, initial_deposit 1000) |
| `test_pl_after_buy_no_price_change` | Deposit 1000, buy 5 AAPL (750) → balance 250, portfolio 750 → P/L = 0 |
| `test_pl_after_multiple_ops` | Deposit 2000, buy/sell multiple times, verify P/L = (balance + portfolio) - initial_deposit |
| `test_pl_after_full_sell` | Deposit 1000, buy 5 AAPL (750), sell 5 AAPL (750) → balance 1000, portfolio 0 → P/L 0 |

#### `class TestHistoricalSnapshots(unittest.TestCase)`

| Test Method | Description |
|---|---|
| `test_holdings_at_past_time` | Make transactions, query with a timestamp between two txns, verify holdings at that point |
| `test_holdings_at_before_all_txns` | Query before any transaction → empty holdings |
| `test_holdings_at_after_all_txns` | Query at current time → matches `get_holdings()` |
| `test_pl_at_past_time` | Make transactions, query P/L at a past timestamp |
| `test_transactions_in_range` | Make 3 transactions, query range covering only middle one → 1 result |

#### `class TestTransactionsList(unittest.TestCase)`

| Test Method | Description |
|---|---|
| `test_empty_transactions` | New account → empty list |
| `test_transaction_ordering` | Multiple operations → transactions in chronological order |
| `test_transaction_ids_unique` | All transaction IDs are unique |
| `test_transaction_balance_after` | Each transaction's `balance_after` matches expected running balance |

---

## 6. Engineer Assignments

### 6.1 Backend Engineer (`account.py`)

**Deliverables:**
1. Implement `get_share_price()` with the fixed price stub.
2. Implement `TransactionType` enum, `Transaction` dataclass, `Holding` dataclass.
3. Implement the `Account` class with all methods, properties, and validation logic.
4. Ensure all error conditions raise `ValueError` with clear messages.
5. Ensure `get_holdings_at()` and `get_profit_or_loss_at()` correctly replay transaction history.

**Acceptance criteria:**
- All unit tests in `test_account.py` pass.
- No third-party dependencies — pure Python standard library only (`dataclasses`, `enum`, `datetime`, `uuid`).

### 6.2 Frontend Engineer (`app.py`)

**Deliverables:**
1. Implement the Gradio 6 Blocks application with 5 tabs as described above.
2. Import `Account` from `account.py` and `get_share_price` for price display.
3. Use `gr.State` to persist the `Account` object across interactions.
4. Implement all handler functions with proper error handling (catch `ValueError` from backend and display messages).
5. Use Gradio 6 API correctly — **theme and footer_links in `launch()`, not in `Blocks()` constructor**.
6. Ensure all event bindings are wired correctly (inputs/outputs match handler signatures).

**Acceptance criteria:**
- App launches without warnings (no deprecated parameter usage).
- All 5 tabs are functional and display correct data.
- Error messages from backend are shown to the user gracefully.

### 6.3 Test Engineer (`test_account.py`)

**Deliverables:**
1. Implement all test classes and test methods listed in Section 5.
2. Use `unittest` framework (built-in, no third-party deps).
3. Ensure tests cover all happy paths and all error/edge cases.
4. Tests should be runnable via `python -m pytest test_account.py` or `python -m unittest test_account`.

**Acceptance criteria:**
- All tests pass against the backend implementation.
- Tests cover: creation, deposit, withdrawal, buy, sell, holdings, portfolio value, P/L, historical snapshots, transaction listing, and all constraint violations.

---

## 7. Dependency Diagram

```
test_account.py ──imports──> account.py
app.py ──imports──> account.py (Account, get_share_price, SUPPORTED_SYMBOLS)
```

No circular dependencies. `account.py` is standalone with zero third-party dependencies. `app.py` depends only on `gradio` and `account.py`. `test_account.py` depends only on `account.py` and `unittest`.

---

## 8. Execution Instructions

```bash
# Run the app
python app.py

# Run tests
python -m pytest test_account.py -v
# or
python -m unittest test_account -v
```

The app will start a local Gradio server (default `http://127.0.0.1:7860`).