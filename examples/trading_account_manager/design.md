# Design: Simple Account Management System for Trading Simulation

## Goals

Build a single-user/multi-account trading simulation backend with a Gradio UI.

The system must support:

- Creating accounts.
- Depositing and withdrawing funds.
- Buying and selling shares.
- Preventing invalid operations:
  - Withdrawals that would make cash negative.
  - Buys that exceed available cash.
  - Sells that exceed current holdings.
- Reporting:
  - Current cash balance.
  - Current holdings.
  - Portfolio market value.
  - Total account value.
  - Profit/loss.
  - Holdings as of a point in time.
  - Profit/loss as of a point in time.
  - Full transaction history.

The project will run in a single directory with no packages/subdirectories.

Only standard library modules and `gradio` are available.

---

# File Layout

All files should live in the same directory.

```text
backend.py
prices.py
app.py
test_backend.py
```

Optional if helpful:

```text
README.md
```

---

# Domain Definitions

## Account Value

For an account:

```text
cash_balance = deposits - withdrawals - buys + sells
holdings_value = sum(quantity_held(symbol) * get_share_price(symbol))
total_account_value = cash_balance + holdings_value
```

## Profit/Loss

Use contribution-adjusted profit/loss:

```text
profit_loss = total_account_value + total_withdrawals - total_deposits
```

This correctly handles multiple deposits and withdrawals.

Example:

```text
deposit 1000
buy shares worth 500
portfolio grows to 1200 total value
profit_loss = 1200 - 1000 = 200
```

If the user later withdraws 100:

```text
total_account_value = 1100
total_withdrawals = 100
total_deposits = 1000
profit_loss = 1100 + 100 - 1000 = 200
```

This represents actual trading performance independent of cash movements.

---

# Backend Design

## File: `prices.py`

### Responsibility

Provide the share price lookup function required by the system.

The implementation should be deterministic for testing and demos.

### Constants

```python
FIXED_SHARE_PRICES: dict[str, float]
```

Suggested values:

```text
AAPL  = 150.00
TSLA  = 250.00
GOOGL = 2800.00
```

### Functions

```python
def get_share_price(symbol: str) -> float:
    ...
```

#### Behavior

- Normalize `symbol` to uppercase and strip whitespace.
- Return the fixed price for supported symbols.
- Raise `ValueError` for unknown symbols.

#### Supported Symbols

```text
AAPL
TSLA
GOOGL
```

---

## File: `backend.py`

### Responsibility

Implement all account, transaction, trading, validation, and reporting logic.

No Gradio-specific code should be in this file.

The backend should be fully testable using unit tests.

---

## Backend Data Model

Use standard-library dataclasses.

### Enum: `TransactionType`

```python
class TransactionType(Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"
```

---

## Dataclass: `Transaction`

```python
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
```

### Field Notes

#### `transaction_id`

Unique identifier for the transaction.

Use `uuid.uuid4()` internally.

#### `account_id`

The account this transaction belongs to.

#### `transaction_type`

One of:

```text
DEPOSIT
WITHDRAWAL
BUY
SELL
```

#### `timestamp`

UTC timestamp when the transaction occurred.

Use timezone-aware UTC datetimes.

#### `symbol`

- `None` for deposits and withdrawals.
- Stock symbol for buys and sells.

#### `quantity`

- `None` for deposits and withdrawals.
- Positive integer for buys and sells.

#### `price`

- `None` for deposits and withdrawals.
- Execution price per share for buys and sells.

#### `cash_amount`

Positive cash amount associated with the transaction.

Examples:

```text
deposit 1000 cash_amount = 1000
withdraw 200 cash_amount = 200
buy 2 AAPL at 150 cash_amount = 300
sell 1 AAPL at 150 cash_amount = 150
```

#### `description`

Human-readable transaction summary.

---

## Dataclass: `Account`

```python
@dataclass
class Account:
    account_id: str
    owner_name: str
    created_at: datetime
    transactions: list[Transaction]
```

### Notes

Do not store `cash_balance` or `holdings` as mutable primary state.

Instead, derive balances and holdings by replaying transactions. This makes historical reporting simpler and less error-prone.

---

# Backend Service Class

## Class: `AccountService`

```python
class AccountService:
    def __init__(self) -> None:
        ...
```

### Internal State

```python
self.accounts: dict[str, Account]
```

The service is in-memory only.

Persistence is not required.

---

# AccountService Public Methods

## Create Account

```python
def create_account(self, owner_name: str, initial_deposit: float = 0.0) -> Account:
    ...
```

### Behavior

- Validate `owner_name` is not blank.
- Validate `initial_deposit >= 0`.
- Create a new account.
- If `initial_deposit > 0`, record a deposit transaction.
- Return the created `Account`.

### Raises

```python
ValueError
```

For invalid owner name or negative initial deposit.

---

## Get Account

```python
def get_account(self, account_id: str) -> Account:
    ...
```

### Behavior

- Return the account for the given id.
- Raise `ValueError` if account does not exist.

---

## List Accounts

```python
def list_accounts(self) -> list[Account]:
    ...
```

### Behavior

- Return all accounts sorted by creation time.

---

## Deposit Funds

```python
def deposit(self, account_id: str, amount: float) -> Transaction:
    ...
```

### Behavior

- Validate account exists.
- Validate `amount > 0`.
- Record a `DEPOSIT` transaction.
- Return the transaction.

### Raises

```python
ValueError
```

For invalid amount or missing account.

---

## Withdraw Funds

```python
def withdraw(self, account_id: str, amount: float) -> Transaction:
    ...
```

### Behavior

- Validate account exists.
- Validate `amount > 0`.
- Calculate current cash balance.
- Reject if `amount > current_cash_balance`.
- Record a `WITHDRAWAL` transaction.
- Return the transaction.

### Raises

```python
ValueError
```

For invalid amount, missing account, or insufficient cash.

---

## Buy Shares

```python
def buy_shares(self, account_id: str, symbol: str, quantity: int) -> Transaction:
    ...
```

### Behavior

- Validate account exists.
- Normalize symbol to uppercase.
- Validate `quantity` is a positive integer.
- Get current share price using `get_share_price(symbol)`.
- Calculate total cost:

```text
cost = price * quantity
```

- Reject if `cost > current_cash_balance`.
- Record a `BUY` transaction.
- Return the transaction.

### Raises

```python
ValueError
```

For invalid account, symbol, quantity, or insufficient funds.

---

## Sell Shares

```python
def sell_shares(self, account_id: str, symbol: str, quantity: int) -> Transaction:
    ...
```

### Behavior

- Validate account exists.
- Normalize symbol to uppercase.
- Validate `quantity` is a positive integer.
- Calculate currently held quantity for the symbol.
- Reject if `quantity > currently_held_quantity`.
- Get current share price using `get_share_price(symbol)`.
- Calculate proceeds:

```text
proceeds = price * quantity
```

- Record a `SELL` transaction.
- Return the transaction.

### Raises

```python
ValueError
```

For invalid account, symbol, quantity, or insufficient holdings.

---

## Get Cash Balance

```python
def get_cash_balance(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> float:
    ...
```

### Behavior

Replay transactions up to `as_of`.

If `as_of is None`, use all transactions.

Cash effects:

```text
DEPOSIT    +cash_amount
WITHDRAWAL -cash_amount
BUY        -cash_amount
SELL       +cash_amount
```

Return rounded cash balance to 2 decimal places.

---

## Get Holdings

```python
def get_holdings(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> dict[str, int]:
    ...
```

### Behavior

Replay transactions up to `as_of`.

Share effects:

```text
BUY  +quantity
SELL -quantity
```

Return only symbols with quantity greater than zero.

Example:

```python
{
    "AAPL": 5,
    "TSLA": 2,
}
```

---

## Get Holdings Report

```python
def get_holdings_report(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> list[dict[str, object]]:
    ...
```

### Behavior

Return a UI/test-friendly list of dictionaries.

Each row should include:

```python
{
    "symbol": str,
    "quantity": int,
    "current_price": float,
    "market_value": float,
}
```

Sort rows alphabetically by symbol.

---

## Get Portfolio Value

```python
def get_portfolio_value(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> float:
    ...
```

### Behavior

- Get holdings as of the requested timestamp.
- Multiply each holding by current share price.
- Return total rounded to 2 decimal places.

Note: since only `get_share_price(symbol)` is available, historical reports use current deterministic prices for symbols held as of the requested point in time.

---

## Get Total Account Value

```python
def get_total_account_value(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> float:
    ...
```

### Behavior

```text
total_account_value = cash_balance + portfolio_value
```

Return rounded to 2 decimal places.

---

## Get Profit/Loss

```python
def get_profit_loss(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> float:
    ...
```

### Behavior

Use contribution-adjusted formula:

```text
profit_loss = total_account_value + total_withdrawals - total_deposits
```

Only include transactions up to `as_of`.

Return rounded to 2 decimal places.

---

## Get Profit/Loss Percent

```python
def get_profit_loss_percent(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> float:
    ...
```

### Behavior

```text
profit_loss_percent = profit_loss / total_deposits * 100
```

If total deposits are zero, return `0.0`.

Return rounded to 2 decimal places.

---

## List Transactions

```python
def list_transactions(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> list[Transaction]:
    ...
```

### Behavior

- Return all transactions for the account.
- If `as_of` is provided, only return transactions with `timestamp <= as_of`.
- Sort by timestamp ascending.

---

## Get Transaction Report

```python
def get_transaction_report(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> list[dict[str, object]]:
    ...
```

### Behavior

Return a UI/test-friendly list of dictionaries.

Each row should include:

```python
{
    "timestamp": str,
    "type": str,
    "symbol": str,
    "quantity": int | str,
    "price": float | str,
    "cash_amount": float,
    "description": str,
}
```

For empty values use `""`.

Timestamp should be formatted as ISO string.

---

## Get Account Summary

```python
def get_account_summary(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> dict[str, object]:
    ...
```

### Behavior

Return a dictionary containing:

```python
{
    "account_id": str,
    "owner_name": str,
    "cash_balance": float,
    "portfolio_value": float,
    "total_account_value": float,
    "profit_loss": float,
    "profit_loss_percent": float,
    "holdings": dict[str, int],
}
```

---

# AccountService Private Helper Methods

The backend engineer may implement these helpers to keep public methods clean.

## Validate Amount

```python
def _validate_positive_amount(self, amount: float, field_name: str = "amount") -> None:
    ...
```

## Validate Quantity

```python
def _validate_positive_quantity(self, quantity: int) -> None:
    ...
```

## Normalize Symbol

```python
def _normalize_symbol(self, symbol: str) -> str:
    ...
```

## Create Transaction

```python
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
    ...
```

## Filter Transactions

```python
def _transactions_as_of(
    self,
    account: Account,
    as_of: datetime | None = None,
) -> list[Transaction]:
    ...
```

## UTC Now

```python
def _utc_now(self) -> datetime:
    ...
```

### Behavior

Return timezone-aware UTC datetime.

---

# Validation Rules

## Owner Name

Invalid:

```text
None
""
"   "
```

Valid:

```text
"Alice"
"Bob Smith"
```

---

## Cash Amounts

Invalid:

```text
amount <= 0
NaN
infinity
non-numeric values
```

The backend should raise `ValueError`.

---

## Initial Deposit

Invalid:

```text
initial_deposit < 0
NaN
infinity
non-numeric values
```

Valid:

```text
initial_deposit == 0
initial_deposit > 0
```

---

## Quantity

Invalid:

```text
quantity <= 0
non-integer quantity
```

Valid:

```text
1
2
100
```

---

## Symbol

Invalid:

```text
None
""
"   "
unknown symbol
```

Valid:

```text
"AAPL"
"aapl"
" TSLA "
"googl"
```

Symbols should be normalized to uppercase.

---

# Frontend Design

## File: `app.py`

### Responsibility

Build a Gradio web app that uses `AccountService`.

No business logic should be implemented in the Gradio callbacks except parsing input, calling backend methods, catching exceptions, and formatting outputs.

---

# Gradio 6 API Guidance

The frontend engineer should use Gradio 6 style APIs.

## Import

```python
import gradio as gr
```

## Blocks App

Use:

```python
with gr.Blocks(title="Trading Simulation Account Manager") as demo:
    ...
```

Launch with:

```python
if __name__ == "__main__":
    demo.launch()
```

## State

Use `gr.State` to hold the in-memory `AccountService` instance or selected account id.

Constructor signature guidance:

```python
gr.State(value=None)
```

Recommended:

```python
service_state = gr.State(value=AccountService())
selected_account_state = gr.State(value=None)
```

## Component Constructor Guidance

Use these Gradio 6-compatible components and kwargs.

### Markdown

```python
gr.Markdown(value="...")
```

Important kwargs:

```text
value
label
visible
```

### Textbox

```python
gr.Textbox(value=None, label="Owner Name", lines=1, interactive=True)
```

Important kwargs:

```text
value
label
lines
interactive
visible
```

### Number

```python
gr.Number(value=0, label="Amount", precision=2, interactive=True)
```

Important kwargs:

```text
value
label
precision
interactive
visible
```

### Dropdown

```python
gr.Dropdown(choices=["AAPL", "TSLA", "GOOGL"], label="Symbol", value="AAPL", interactive=True)
```

Important kwargs:

```text
choices
value
label
interactive
visible
```

To update dropdown choices in Gradio 6, return a new component instance from an event callback:

```python
return gr.Dropdown(choices=new_choices, value=new_value, interactive=True)
```

Do not rely on old component-specific `.update()` methods.

### Dataframe

```python
gr.Dataframe(
    value=[],
    headers=["Symbol", "Quantity", "Current Price", "Market Value"],
    label="Holdings",
    interactive=False,
)
```

Important kwargs:

```text
value
headers
row_count
column_count
label
interactive
visible
```

For simple usage, return a list of rows or a list of dictionaries from callbacks.

### Button

```python
gr.Button(value="Create Account", interactive=True)
```

Important kwargs:

```text
value
interactive
visible
```

## Event Listener Guidance

Use `.click(...)`, `.change(...)`, and related event methods.

Preferred signature:

```python
button.click(
    fn=callback_function,
    inputs=[input_component_1, input_component_2, state_component],
    outputs=[output_component_1, output_component_2],
)
```

Single component input/output can be passed directly, but lists are clearer.

Example:

```python
create_button.click(
    fn=create_account_callback,
    inputs=[owner_name_input, initial_deposit_input, service_state],
    outputs=[
        selected_account_state,
        account_dropdown,
        status_markdown,
        summary_markdown,
        holdings_dataframe,
        transactions_dataframe,
    ],
)
```

## Returning Updates

In Gradio 6, to update a component’s properties, return a new component instance:

```python
return gr.Dropdown(choices=account_choices, value=selected_account_id)
```

or use the standalone helper:

```python
return gr.update(value="message", visible=True)
```

Both are acceptable, but prefer returning component instances for dropdown choice updates.

Avoid older patterns like:

```python
gr.Dropdown.update(...)
```

---

# UI Layout

The app should be organized into clear sections.

## Header

```text
Trading Simulation Account Manager
```

Use `gr.Markdown`.

---

## Section 1: Account Creation

Components:

```python
owner_name_input: gr.Textbox
initial_deposit_input: gr.Number
create_account_button: gr.Button
account_dropdown: gr.Dropdown
status_markdown: gr.Markdown
```

### Behavior

- User enters owner name and optional initial deposit.
- Clicking create account:
  - Calls `AccountService.create_account`.
  - Updates selected account.
  - Refreshes account dropdown.
  - Refreshes summary, holdings, and transaction tables.
  - Shows success or error message.

---

## Section 2: Cash Operations

Components:

```python
cash_amount_input: gr.Number
deposit_button: gr.Button
withdraw_button: gr.Button
```

### Behavior

- Deposit button calls backend `deposit`.
- Withdraw button calls backend `withdraw`.
- On success:
  - Refresh summary.
  - Refresh transactions.
  - Show status.
- On error:
  - Show error status.
  - Do not update backend state except for failed operation having no effect.

---

## Section 3: Trading Operations

Components:

```python
symbol_dropdown: gr.Dropdown
quantity_input: gr.Number
buy_button: gr.Button
sell_button: gr.Button
```

### Behavior

Supported symbols:

```python
["AAPL", "TSLA", "GOOGL"]
```

- Buy button calls `buy_shares`.
- Sell button calls `sell_shares`.
- On success:
  - Refresh summary.
  - Refresh holdings.
  - Refresh transactions.
  - Show status.
- On error:
  - Show error status.

### Quantity Input

`gr.Number` returns numeric values that may be floats.

The frontend callback should convert to `int` only if the number is an integer.

Validation should still primarily live in the backend.

---

## Section 4: Reporting

Components:

```python
summary_markdown: gr.Markdown
holdings_dataframe: gr.Dataframe
transactions_dataframe: gr.Dataframe
refresh_button: gr.Button
```

### Summary Markdown Should Display

```text
Account ID
Owner
Cash Balance
Portfolio Value
Total Account Value
Profit/Loss
Profit/Loss %
```

### Holdings DataFrame Columns

```text
Symbol
Quantity
Current Price
Market Value
```

### Transactions DataFrame Columns

```text
Timestamp
Type
Symbol
Quantity
Price
Cash Amount
Description
```

---

## Section 5: Historical Reporting

Components:

```python
as_of_textbox: gr.Textbox
historical_report_button: gr.Button
```

### `as_of_textbox`

Accept ISO datetime strings.

Examples:

```text
2025-01-01T12:30:00+00:00
2025-01-01T12:30:00
```

If timezone is missing, treat as UTC.

### Behavior

- Parse the datetime.
- Call:
  - `get_account_summary(account_id, as_of=parsed_datetime)`
  - `get_holdings_report(account_id, as_of=parsed_datetime)`
  - `get_transaction_report(account_id, as_of=parsed_datetime)`
- Update summary and tables.
- Show status message that report is as of the requested time.

---

# Frontend Callback Function Signatures

These should live in `app.py`.

## Create App

```python
def build_app() -> gr.Blocks:
    ...
```

### Behavior

Construct and return the Gradio `Blocks` app.

The module should call `build_app()` and launch only under the main guard.

---

## Format Account Choices

```python
def format_account_choices(service: AccountService) -> list[tuple[str, str]]:
    ...
```

### Behavior

Return dropdown choices.

Each choice should be:

```python
(label, value)
```

Example label:

```text
Alice - 3f1c2a
```

Value:

```text
full account_id
```

Gradio dropdown supports choices as strings or `(label, value)` tuples.

---

## Parse Optional Datetime

```python
def parse_optional_datetime(as_of_text: str | None) -> datetime | None:
    ...
```

### Behavior

- Return `None` for blank input.
- Parse ISO datetime.
- If parsed datetime has no timezone, set UTC timezone.
- Raise `ValueError` for invalid input.

---

## Format Summary Markdown

```python
def format_summary_markdown(summary: dict[str, object], as_of: datetime | None = None) -> str:
    ...
```

### Behavior

Return Markdown text with account summary.

---

## Format Holdings Rows

```python
def format_holdings_rows(holdings_report: list[dict[str, object]]) -> list[list[object]]:
    ...
```

### Output Row Format

```python
[
    symbol,
    quantity,
    current_price,
    market_value,
]
```

---

## Format Transaction Rows

```python
def format_transaction_rows(transaction_report: list[dict[str, object]]) -> list[list[object]]:
    ...
```

### Output Row Format

```python
[
    timestamp,
    type,
    symbol,
    quantity,
    price,
    cash_amount,
    description,
]
```

---

## Refresh Display

```python
def refresh_display(
    service: AccountService,
    account_id: str | None,
    as_of: datetime | None = None,
) -> tuple[str, list[list[object]], list[list[object]]]:
    ...
```

### Returns

```python
summary_markdown_value,
holdings_rows,
transaction_rows
```

### Behavior

If no account is selected, return:

```text
summary = "No account selected."
holdings_rows = []
transaction_rows = []
```

Otherwise call backend report methods.

---

## Create Account Callback

```python
def on_create_account(
    owner_name: str,
    initial_deposit: float,
    service: AccountService,
) -> tuple[str | None, gr.Dropdown, str, str, list[list[object]], list[list[object]]]:
    ...
```

### Returns

```python
selected_account_id,
updated_account_dropdown,
status_markdown,
summary_markdown,
holdings_rows,
transaction_rows
```

### Behavior

- Call `service.create_account`.
- Select new account.
- Refresh display.
- Return updated dropdown using:

```python
gr.Dropdown(choices=choices, value=new_account.account_id, interactive=True)
```

- Catch `Exception` and return error status.

---

## Account Selection Callback

```python
def on_select_account(
    account_id: str,
    service: AccountService,
) -> tuple[str | None, str, str, list[list[object]], list[list[object]]]:
    ...
```

### Returns

```python
selected_account_id,
status_markdown,
summary_markdown,
holdings_rows,
transaction_rows
```

---

## Deposit Callback

```python
def on_deposit(
    account_id: str | None,
    amount: float,
    service: AccountService,
) -> tuple[str, str, list[list[object]], list[list[object]]]:
    ...
```

### Returns

```python
status_markdown,
summary_markdown,
holdings_rows,
transaction_rows
```

---

## Withdraw Callback

```python
def on_withdraw(
    account_id: str | None,
    amount: float,
    service: AccountService,
) -> tuple[str, str, list[list[object]], list[list[object]]]:
    ...
```

### Returns

```python
status_markdown,
summary_markdown,
holdings_rows,
transaction_rows
```

---

## Buy Callback

```python
def on_buy(
    account_id: str | None,
    symbol: str,
    quantity: float,
    service: AccountService,
) -> tuple[str, str, list[list[object]], list[list[object]]]:
    ...
```

### Returns

```python
status_markdown,
summary_markdown,
holdings_rows,
transaction_rows
```

---

## Sell Callback

```python
def on_sell(
    account_id: str | None,
    symbol: str,
    quantity: float,
    service: AccountService,
) -> tuple[str, str, list[list[object]], list[list[object]]]:
    ...
```

### Returns

```python
status_markdown,
summary_markdown,
holdings_rows,
transaction_rows
```

---

## Refresh Callback

```python
def on_refresh(
    account_id: str | None,
    service: AccountService,
) -> tuple[str, str, list[list[object]], list[list[object]]]:
    ...
```

### Returns

```python
status_markdown,
summary_markdown,
holdings_rows,
transaction_rows
```

---

## Historical Report Callback

```python
def on_historical_report(
    account_id: str | None,
    as_of_text: str | None,
    service: AccountService,
) -> tuple[str, str, list[list[object]], list[list[object]]]:
    ...
```

### Returns

```python
status_markdown,
summary_markdown,
holdings_rows,
transaction_rows
```

---

# Suggested Gradio Wiring

The frontend engineer should wire events approximately as follows.

## Create Account Button

```python
create_account_button.click(
    fn=on_create_account,
    inputs=[owner_name_input, initial_deposit_input, service_state],
    outputs=[
        selected_account_state,
        account_dropdown,
        status_markdown,
        summary_markdown,
        holdings_dataframe,
        transactions_dataframe,
    ],
)
```

## Account Dropdown Change

```python
account_dropdown.change(
    fn=on_select_account,
    inputs=[account_dropdown, service_state],
    outputs=[
        selected_account_state,
        status_markdown,
        summary_markdown,
        holdings_dataframe,
        transactions_dataframe,
    ],
)
```

## Deposit Button

```python
deposit_button.click(
    fn=on_deposit,
    inputs=[selected_account_state, cash_amount_input, service_state],
    outputs=[
        status_markdown,
        summary_markdown,
        holdings_dataframe,
        transactions_dataframe,
    ],
)
```

## Withdraw Button

```python
withdraw_button.click(
    fn=on_withdraw,
    inputs=[selected_account_state, cash_amount_input, service_state],
    outputs=[
        status_markdown,
        summary_markdown,
        holdings_dataframe,
        transactions_dataframe,
    ],
)
```

## Buy Button

```python
buy_button.click(
    fn=on_buy,
    inputs=[selected_account_state, symbol_dropdown, quantity_input, service_state],
    outputs=[
        status_markdown,
        summary_markdown,
        holdings_dataframe,
        transactions_dataframe,
    ],
)
```

## Sell Button

```python
sell_button.click(
    fn=on_sell,
    inputs=[selected_account_state, symbol_dropdown, quantity_input, service_state],
    outputs=[
        status_markdown,
        summary_markdown,
        holdings_dataframe,
        transactions_dataframe,
    ],
)
```

## Refresh Button

```python
refresh_button.click(
    fn=on_refresh,
    inputs=[selected_account_state, service_state],
    outputs=[
        status_markdown,
        summary_markdown,
        holdings_dataframe,
        transactions_dataframe,
    ],
)
```

## Historical Report Button

```python
historical_report_button.click(
    fn=on_historical_report,
    inputs=[selected_account_state, as_of_textbox, service_state],
    outputs=[
        status_markdown,
        summary_markdown,
        holdings_dataframe,
        transactions_dataframe,
    ],
)
```

---

# Unit Test Design

## File: `test_backend.py`

### Responsibility

Test backend behavior only.

Do not test Gradio UI in unit tests.

Use standard library `unittest`.

---

# Test Cases

## Test Account Creation

### Test Function

```python
def test_create_account_without_initial_deposit(self) -> None:
    ...
```

Verify:

- Account is created.
- Owner name is stored.
- Transaction list is empty.
- Cash balance is `0.0`.
- Holdings are empty.

---

### Test Function

```python
def test_create_account_with_initial_deposit(self) -> None:
    ...
```

Verify:

- Account is created.
- One deposit transaction is recorded.
- Cash balance equals initial deposit.
- Profit/loss is `0.0`.

---

### Test Function

```python
def test_create_account_rejects_blank_owner_name(self) -> None:
    ...
```

Verify `ValueError`.

---

### Test Function

```python
def test_create_account_rejects_negative_initial_deposit(self) -> None:
    ...
```

Verify `ValueError`.

---

## Test Deposits

### Test Function

```python
def test_deposit_increases_cash_balance(self) -> None:
    ...
```

Verify:

- Cash increases.
- Transaction is recorded.
- Transaction type is `DEPOSIT`.

---

### Test Function

```python
def test_deposit_rejects_non_positive_amount(self) -> None:
    ...
```

Verify `ValueError` for:

```text
0
-1
```

---

## Test Withdrawals

### Test Function

```python
def test_withdraw_decreases_cash_balance(self) -> None:
    ...
```

Verify:

- Cash decreases.
- Transaction is recorded.
- Transaction type is `WITHDRAWAL`.

---

### Test Function

```python
def test_withdraw_rejects_insufficient_cash(self) -> None:
    ...
```

Example:

```text
deposit 100
withdraw 101
```

Verify:

- Raises `ValueError`.
- Cash remains `100`.
- No withdrawal transaction is recorded.

---

### Test Function

```python
def test_withdraw_rejects_non_positive_amount(self) -> None:
    ...
```

Verify `ValueError`.

---

## Test Buying Shares

### Test Function

```python
def test_buy_shares_decreases_cash_and_increases_holdings(self) -> None:
    ...
```

Example:

```text
deposit 1000
buy 2 AAPL at 150
```

Verify:

```text
cash = 700
holdings["AAPL"] = 2
portfolio_value = 300
total_account_value = 1000
```

---

### Test Function

```python
def test_buy_rejects_insufficient_cash(self) -> None:
    ...
```

Example:

```text
deposit 100
buy 1 AAPL
```

Verify:

- Raises `ValueError`.
- Cash remains `100`.
- Holdings remain empty.
- No buy transaction is recorded.

---

### Test Function

```python
def test_buy_rejects_invalid_quantity(self) -> None:
    ...
```

Verify `ValueError` for:

```text
0
-1
1.5
```

---

### Test Function

```python
def test_buy_rejects_unknown_symbol(self) -> None:
    ...
```

Verify `ValueError`.

---

### Test Function

```python
def test_buy_normalizes_symbol(self) -> None:
    ...
```

Example:

```text
buy " aapl "
```

Verify holdings key is:

```text
"AAPL"
```

---

## Test Selling Shares

### Test Function

```python
def test_sell_shares_increases_cash_and_decreases_holdings(self) -> None:
    ...
```

Example:

```text
deposit 1000
buy 2 AAPL
sell 1 AAPL
```

Verify:

```text
holdings["AAPL"] = 1
cash = 850
```

Calculation:

```text
1000 - 300 + 150 = 850
```

---

### Test Function

```python
def test_sell_all_shares_removes_holding_from_holdings_report(self) -> None:
    ...
```

Example:

```text
deposit 1000
buy 1 AAPL
sell 1 AAPL
```

Verify:

```text
get_holdings(account_id) == {}
```

---

### Test Function

```python
def test_sell_rejects_insufficient_holdings(self) -> None:
    ...
```

Example:

```text
deposit 1000
buy 1 AAPL
sell 2 AAPL
```

Verify:

- Raises `ValueError`.
- Holdings remain unchanged.
- No sell transaction is recorded.

---

### Test Function

```python
def test_sell_rejects_symbol_not_owned(self) -> None:
    ...
```

Example:

```text
deposit 1000
sell 1 TSLA
```

Verify `ValueError`.

---

## Test Portfolio Value

### Test Function

```python
def test_portfolio_value_multiple_symbols(self) -> None:
    ...
```

Example:

```text
deposit 10000
buy 2 AAPL    = 300
buy 3 TSLA    = 750
```

Verify:

```text
portfolio_value = 1050
```

---

## Test Total Account Value

### Test Function

```python
def test_total_account_value_cash_plus_portfolio(self) -> None:
    ...
```

Example:

```text
deposit 10000
buy 2 AAPL
```

Verify:

```text
cash = 9700
portfolio = 300
total = 10000
```

---

## Test Profit/Loss

### Test Function

```python
def test_profit_loss_zero_when_prices_unchanged_after_buy(self) -> None:
    ...
```

Because fixed execution prices and current prices are the same.

Example:

```text
deposit 1000
buy 2 AAPL
```

Verify:

```text
profit_loss = 0
```

---

### Test Function

```python
def test_profit_loss_accounts_for_withdrawals(self) -> None:
    ...
```

Example:

```text
deposit 1000
withdraw 200
```

Verify:

```text
total_account_value = 800
profit_loss = 0
```

Formula:

```text
800 + 200 - 1000 = 0
```

---

### Test Function

```python
def test_profit_loss_accounts_for_multiple_deposits(self) -> None:
    ...
```

Example:

```text
deposit 1000
deposit 500
```

Verify:

```text
total_account_value = 1500
profit_loss = 0
```

---

## Test Transaction Listing

### Test Function

```python
def test_list_transactions_returns_transactions_in_order(self) -> None:
    ...
```

Verify transaction order is chronological.

---

### Test Function

```python
def test_transaction_report_has_expected_fields(self) -> None:
    ...
```

Verify dictionary keys:

```text
timestamp
type
symbol
quantity
price
cash_amount
description
```

---

## Test Historical Holdings

### Test Function

```python
def test_get_holdings_as_of_timestamp(self) -> None:
    ...
```

Implementation strategy:

- Create account.
- Deposit.
- Capture timestamp after deposit.
- Buy AAPL.
- Capture timestamp after buy.
- Buy TSLA.
- Query holdings as of each timestamp.

Verify:

- Before buy: `{}`.
- After AAPL buy: `{"AAPL": quantity}`.
- After TSLA buy: both holdings.

Because timestamps are generated internally, the test may need to use timestamps from recorded transactions.

Example:

```python
transactions = service.list_transactions(account_id)
as_of_deposit = transactions[0].timestamp
as_of_first_buy = transactions[1].timestamp
```

---

## Test Historical Cash Balance

### Test Function

```python
def test_get_cash_balance_as_of_timestamp(self) -> None:
    ...
```

Example:

```text
deposit 1000
buy 2 AAPL
withdraw 100
```

Verify:

```text
as of deposit: 1000
as of buy: 700
as of withdrawal: 600
```

---

## Test Historical Profit/Loss

### Test Function

```python
def test_get_profit_loss_as_of_timestamp(self) -> None:
    ...
```

Verify contribution-adjusted profit/loss at historical timestamps.

---

## Test Account Summary

### Test Function

```python
def test_get_account_summary_contains_expected_values(self) -> None:
    ...
```

Verify keys:

```text
account_id
owner_name
cash_balance
portfolio_value
total_account_value
profit_loss
profit_loss_percent
holdings
```

---

# Engineer Assignments

## backend_engineer

### Owns

```text
prices.py
backend.py
```

### Tasks

1. Implement `prices.py`.
2. Implement all dataclasses and enum in `backend.py`.
3. Implement `AccountService`.
4. Ensure all validation rules are enforced.
5. Ensure failed operations do not mutate account state.
6. Ensure all reports return deterministic, UI-friendly values.
7. Use timezone-aware UTC timestamps.
8. Use only standard library imports.
9. Do not import Gradio in backend files.

### Required Public API

The backend must expose:

```python
TransactionType
Transaction
Account
AccountService
```

And `prices.py` must expose:

```python
get_share_price
```

---

## frontend_engineer

### Owns

```text
app.py
```

### Tasks

1. Build Gradio app using `gr.Blocks`.
2. Import and use `AccountService`.
3. Implement formatting helpers.
4. Implement Gradio callbacks.
5. Wire buttons/dropdowns to callbacks.
6. Display account summary, holdings, and transactions.
7. Show clear success/error messages.
8. Use Gradio 6-compatible component update patterns.
9. Do not implement business rules in UI beyond input parsing.

### Required Public API

`app.py` should expose:

```python
def build_app() -> gr.Blocks:
    ...
```

And should launch with:

```python
if __name__ == "__main__":
    demo = build_app()
    demo.launch()
```

### Important Gradio 6 Notes

- Use `gr.Blocks`.
- Use `gr.State(value=...)`.
- Use `.click(fn=..., inputs=[...], outputs=[...])`.
- Use `.change(fn=..., inputs=[...], outputs=[...])`.
- To update dropdown choices, return:

```python
gr.Dropdown(choices=choices, value=value, interactive=True)
```

- Avoid old APIs like:

```python
gr.Dropdown.update(...)
```

---

## test_engineer

### Owns

```text
test_backend.py
```

### Tasks

1. Write unit tests using `unittest`.
2. Test only backend logic.
3. Cover all validations and invalid operations.
4. Cover cash, holdings, portfolio value, total account value, profit/loss.
5. Cover transaction reports.
6. Cover historical `as_of` reporting.
7. Ensure failed operations do not mutate state.
8. Tests should run with:

```bash
uv run python -m unittest test_backend.py
```

---

# Acceptance Criteria

The implementation is complete when:

1. A user can create an account from the Gradio app.
2. A user can deposit funds.
3. A user can withdraw funds only when enough cash is available.
4. A user can buy supported shares only when enough cash is available.
5. A user can sell shares only when enough shares are owned.
6. The app displays:
   - Cash balance.
   - Holdings.
   - Portfolio value.
   - Total account value.
   - Profit/loss.
   - Transaction history.
7. The app supports historical reporting using an ISO datetime.
8. Backend unit tests pass.
9. No files are placed in subdirectories.
10. No third-party packages are used except Gradio.
11. Backend code has no dependency on Gradio.
12. Gradio app launches successfully with:

```bash
uv run python app.py
```