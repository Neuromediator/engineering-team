"""Gradio frontend for the trading simulation account management platform."""

from __future__ import annotations

import uuid

import gradio as gr

from account import Account, SUPPORTED_SYMBOLS, get_share_price

# ---------------------------------------------------------------
# Custom accent CSS — works in light and dark mode
# ---------------------------------------------------------------
CSS = """
.accent-btn {
    background-color: #209dd7 !important;
    color: #ffffff !important;
    border: none !important;
}
.accent-btn:hover {
    background-color: #ecad0a !important;
    color: #1a1a1a !important;
}
.buy-btn {
    background-color: #209dd7 !important;
    color: #ffffff !important;
    border: none !important;
}
.buy-btn:hover {
    background-color: #ecad0a !important;
    color: #1a1a1a !important;
}
.sell-btn {
    background-color: #753991 !important;
    color: #ffffff !important;
    border: none !important;
}
.sell-btn:hover {
    background-color: #ecad0a !important;
    color: #1a1a1a !important;
}
.title-text {
    color: #753991 !important;
}
.status-ok {
    color: #209dd7 !important;
}
.status-bad {
    color: #d7263d !important;
}
"""

# ---------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------

def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def _fmt_pl(value: float) -> str:
    if value >= 0:
        return f"+${_fmt_money(value)[1:]}"
    return f"-${abs(value):,.2f}"


def create_account(owner_name: str, account: Account | None):
    if account is not None:
        return account, f"Account already exists for {account.owner_name} (ID: {account.account_id})"
    name = owner_name.strip() if owner_name else ""
    if not name:
        return None, "Please enter an owner name."
    acc = Account(account_id=uuid.uuid4().hex[:8].upper(), owner_name=name)
    return acc, f"✅ Account created for {acc.owner_name} — ID {acc.account_id}"


def handle_deposit(amount, account: Account | None):
    if account is None:
        return None, "", "⚠️ No account found. Create an account first."
    try:
        amt = float(amount) if amount is not None else 0.0
        account.deposit(amt)
        return account, _fmt_money(account.balance), f"✅ Deposited {_fmt_money(amt)} — balance is now {_fmt_money(account.balance)}"
    except ValueError as exc:
        return account, _fmt_money(account.balance), f"❌ {exc}"
    except Exception as exc:
        return account, _fmt_money(account.balance), f"❌ Unexpected error: {exc}"


def handle_withdraw(amount, account: Account | None):
    if account is None:
        return None, "", "⚠️ No account found. Create an account first."
    try:
        amt = float(amount) if amount is not None else 0.0
        account.withdraw(amt)
        return account, _fmt_money(account.balance), f"✅ Withdrew {_fmt_money(amt)} — balance is now {_fmt_money(account.balance)}"
    except ValueError as exc:
        return account, _fmt_money(account.balance), f"❌ {exc}"
    except Exception as exc:
        return account, _fmt_money(account.balance), f"❌ Unexpected error: {exc}"


def get_price_for_display(symbol: str) -> str:
    if not symbol:
        return ""
    try:
        return _fmt_money(get_share_price(symbol))
    except ValueError:
        return ""


def handle_buy(symbol: str, quantity, account: Account | None):
    if account is None:
        return None, "", "⚠️ No account found. Create an account first."
    try:
        qty = float(quantity) if quantity is not None else 0.0
        account.buy_shares(symbol, qty)
        return account, _fmt_money(account.balance), f"✅ Bought {qty} shares of {symbol} — balance is now {_fmt_money(account.balance)}"
    except ValueError as exc:
        return account, _fmt_money(account.balance), f"❌ {exc}"
    except Exception as exc:
        return account, _fmt_money(account.balance), f"❌ Unexpected error: {exc}"


def handle_sell(symbol: str, quantity, account: Account | None):
    if account is None:
        return None, "", "⚠️ No account found. Create an account first."
    try:
        qty = float(quantity) if quantity is not None else 0.0
        account.sell_shares(symbol, qty)
        return account, _fmt_money(account.balance), f"✅ Sold {qty} shares of {symbol} — balance is now {_fmt_money(account.balance)}"
    except ValueError as exc:
        return account, _fmt_money(account.balance), f"❌ {exc}"
    except Exception as exc:
        return account, _fmt_money(account.balance), f"❌ Unexpected error: {exc}"


def refresh_portfolio(account: Account | None):
    if account is None:
        return [], "", "", "", "⚠️ No account found. Create an account first."
    rows: list[list] = []
    for h in account.get_holdings():
        price = get_share_price(h.symbol)
        mkt = h.quantity * price
        rows.append([
            h.symbol,
            round(float(h.quantity), 4),
            _fmt_money(h.average_cost),
            _fmt_money(price),
            _fmt_money(mkt),
        ])
    port_val = account.get_portfolio_value()
    bal = account.balance
    pl = account.get_profit_or_loss()
    return (
        rows,
        _fmt_money(port_val),
        _fmt_money(bal),
        _fmt_pl(pl),
        "✅ Portfolio refreshed",
    )


def historical_snapshot(as_of_str: str, account: Account | None):
    from datetime import datetime

    if account is None:
        return [], "", "⚠️ No account found. Create an account first."
    s = as_of_str.strip() if as_of_str else ""
    if not s:
        return [], "", "Please provide an ISO timestamp (e.g. 2024-01-15T10:00:00)."
    try:
        ts = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return [], "", "Invalid timestamp. Use ISO format (e.g. 2024-01-15T10:00:00)."
    try:
        holdings = account.get_holdings_at(ts)
        pl = account.get_profit_or_loss_at(ts)
        rows: list[list] = []
        for h in holdings:
            rows.append([
                h.symbol,
                round(float(h.quantity), 4),
                _fmt_money(h.average_cost),
            ])
        return rows, _fmt_pl(pl), f"✅ Snapshot as of {ts.isoformat()}"
    except Exception as exc:
        return [], "", f"❌ Error: {exc}"


def refresh_transactions(account: Account | None):
    if account is None:
        return [], "⚠️ No account found. Create an account first."
    rows: list[list] = []
    for t in account.get_transactions():
        rows.append([
            t.id,
            t.type.value,
            t.symbol or "",
            round(float(t.quantity), 4) if t.quantity else 0,
            _fmt_money(t.price) if t.price else "$0.00",
            _fmt_money(t.amount),
            t.timestamp.isoformat(),
            _fmt_money(t.balance_after),
        ])
    return rows, f"✅ {len(rows)} transactions loaded."


# ---------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------
with gr.Blocks() as demo:
    gr.Markdown(
        "# 📈 Trading Simulation Platform",
        elem_classes=["title-text"],
    )
    gr.Markdown("Manage your simulated trading account — deposit, withdraw, trade shares, and track performance.")

    account_state = gr.State(None)

    with gr.Tabs():
        # ---------------- Tab 1: Create Account ----------------
        with gr.Tab("Create Account"):
            with gr.Row():
                with gr.Column(scale=2):
                    owner_name_input = gr.Textbox(
                        label="Owner Name",
                        placeholder="Enter the account owner's full name",
                    )
                    create_btn = gr.Button(
                        "Create Account",
                        variant="primary",
                        elem_classes=["accent-btn"],
                    )
                with gr.Column(scale=3):
                    create_status = gr.Textbox(
                        label="Status",
                        interactive=False,
                        lines=2,
                    )

            create_btn.click(
                fn=create_account,
                inputs=[owner_name_input, account_state],
                outputs=[account_state, create_status],
            )

        # ---------------- Tab 2: Deposit / Withdraw ----------------
        with gr.Tab("Deposit / Withdraw"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### 💰 Deposit Funds")
                    deposit_amount = gr.Number(
                        label="Deposit Amount ($)",
                        value=0,
                        precision=2,
                    )
                    deposit_btn = gr.Button(
                        "Deposit",
                        elem_classes=["accent-btn"],
                    )
                with gr.Column():
                    gr.Markdown("### 🏧 Withdraw Funds")
                    withdraw_amount = gr.Number(
                        label="Withdraw Amount ($)",
                        value=0,
                        precision=2,
                    )
                    withdraw_btn = gr.Button(
                        "Withdraw",
                        elem_classes=["accent-btn"],
                    )
            with gr.Row():
                dw_balance = gr.Textbox(
                    label="Current Balance",
                    interactive=False,
                    value="$0.00",
                )
                dw_status = gr.Textbox(
                    label="Status",
                    interactive=False,
                    lines=2,
                )

            deposit_btn.click(
                fn=handle_deposit,
                inputs=[deposit_amount, account_state],
                outputs=[account_state, dw_balance, dw_status],
            )
            withdraw_btn.click(
                fn=handle_withdraw,
                inputs=[withdraw_amount, account_state],
                outputs=[account_state, dw_balance, dw_status],
            )

        # ---------------- Tab 3: Buy / Sell ----------------
        with gr.Tab("Buy / Sell Shares"):
            with gr.Row():
                with gr.Column():
                    trade_symbol = gr.Dropdown(
                        choices=list(SUPPORTED_SYMBOLS),
                        label="Symbol",
                        value=SUPPORTED_SYMBOLS[0] if SUPPORTED_SYMBOLS else None,
                    )
                    trade_price_display = gr.Textbox(
                        label="Current Price",
                        interactive=False,
                        value=_fmt_money(get_share_price(SUPPORTED_SYMBOLS[0])),
                    )
                with gr.Column():
                    trade_qty = gr.Number(
                        label="Quantity (shares)",
                        value=1,
                        precision=4,
                    )
            with gr.Row():
                buy_btn = gr.Button(
                    "Buy Shares",
                    variant="primary",
                    elem_classes=["buy-btn"],
                )
                sell_btn = gr.Button(
                    "Sell Shares",
                    elem_classes=["sell-btn"],
                )
            with gr.Row():
                trade_balance_display = gr.Textbox(
                    label="Current Balance",
                    interactive=False,
                    value="$0.00",
                )
                trade_status = gr.Textbox(
                    label="Status",
                    interactive=False,
                    lines=2,
                )

            trade_symbol.change(
                fn=get_price_for_display,
                inputs=trade_symbol,
                outputs=trade_price_display,
            )
            buy_btn.click(
                fn=handle_buy,
                inputs=[trade_symbol, trade_qty, account_state],
                outputs=[account_state, trade_balance_display, trade_status],
            )
            sell_btn.click(
                fn=handle_sell,
                inputs=[trade_symbol, trade_qty, account_state],
                outputs=[account_state, trade_balance_display, trade_status],
            )

        # ---------------- Tab 4: Portfolio & P/L ----------------
        with gr.Tab("Portfolio & P/L"):
            with gr.Row():
                portfolio_refresh_btn = gr.Button(
                    "Refresh Portfolio",
                    elem_classes=["accent-btn"],
                )
            with gr.Row():
                holdings_df = gr.Dataframe(
                    headers=["Symbol", "Quantity", "Avg Cost", "Current Price", "Market Value"],
                    interactive=False,
                    label="Current Holdings",
                )
            with gr.Row():
                portfolio_value_display = gr.Textbox(
                    label="Total Portfolio Value",
                    interactive=False,
                )
                balance_pl_display = gr.Textbox(
                    label="Current Cash Balance",
                    interactive=False,
                )
                pl_display = gr.Textbox(
                    label="Total Profit / Loss",
                    interactive=False,
                )
            with gr.Row():
                as_of_datetime = gr.Textbox(
                    label="As-of Timestamp (ISO format, leave blank for now)",
                    placeholder="2024-01-15T10:00:00",
                )
                historical_btn = gr.Button(
                    "Get Historical Snapshot",
                    elem_classes=["accent-btn"],
                )
            with gr.Row():
                historical_holdings_df = gr.Dataframe(
                    headers=["Symbol", "Quantity", "Avg Cost"],
                    interactive=False,
                    label="Historical Holdings",
                )
                historical_pl_display = gr.Textbox(
                    label="Historical Profit/Loss",
                    interactive=False,
                )
            with gr.Row():
                portfolio_status = gr.Textbox(
                    label="Status",
                    interactive=False,
                    lines=2,
                )

            portfolio_refresh_btn.click(
                fn=refresh_portfolio,
                inputs=[account_state],
                outputs=[
                    holdings_df,
                    portfolio_value_display,
                    balance_pl_display,
                    pl_display,
                    portfolio_status,
                ],
            )
            historical_btn.click(
                fn=historical_snapshot,
                inputs=[as_of_datetime, account_state],
                outputs=[
                    historical_holdings_df,
                    historical_pl_display,
                    portfolio_status,
                ],
            )

        # ---------------- Tab 5: Transaction History ----------------
        with gr.Tab("Transaction History"):
            with gr.Row():
                tx_refresh_btn = gr.Button(
                    "Refresh Transactions",
                    elem_classes=["accent-btn"],
                )
            with gr.Row():
                tx_df = gr.Dataframe(
                    headers=["ID", "Type", "Symbol", "Quantity", "Price", "Amount", "Timestamp", "Balance After"],
                    interactive=False,
                    label="All Transactions",
                )
            with gr.Row():
                tx_status = gr.Textbox(
                    label="Status",
                    interactive=False,
                    lines=2,
                )

            tx_refresh_btn.click(
                fn=refresh_transactions,
                inputs=[account_state],
                outputs=[tx_df, tx_status],
            )

if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),
        css=CSS,
        footer_links=[],
    )
