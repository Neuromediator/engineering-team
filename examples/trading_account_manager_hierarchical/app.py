"""Trading account management system — Gradio Blocks UI.

A polished frontend that wraps the ``account_system`` backend. A single
``Account`` instance lives in ``gr.State`` for the lifetime of the session
and is threaded through every event handler.

All dollar amounts are formatted as ``$X.XX``. The backend exceptions
``ValueError``, ``InsufficientFundsError`` and ``InsufficientHoldingsError``
are caught at the UI boundary and surfaced as friendly error messages.

Brand palette: gold (#ecad0a), blue (#209dd7), purple (#753991) — used as
accents that read well in both light and dark mode.
"""

from __future__ import annotations

import gradio as gr
import pandas as pd

from account_system import (
    Account,
    InsufficientFundsError,
    InsufficientHoldingsError,
)


# ---------------------------------------------------------------------------
# Brand palette
# ---------------------------------------------------------------------------
GOLD = "#ecad0a"
BLUE = "#209dd7"
PURPLE = "#753991"


# ---------------------------------------------------------------------------
# Custom CSS — uses CSS variables so the same colors apply in light & dark mode.
# Hard-coded text colors are kept inside the gradient header (which always has a
# dark gradient) so contrast is guaranteed regardless of theme.
# ---------------------------------------------------------------------------
CUSTOM_CSS = f"""
:root {{
  --brand-gold: {GOLD};
  --brand-blue: {BLUE};
  --brand-purple: {PURPLE};
}}

/* Header banner */
.app-header {{
  background: linear-gradient(135deg, var(--brand-purple) 0%, var(--brand-blue) 100%);
  color: #ffffff;
  padding: 1.25rem 1.5rem;
  border-radius: 12px;
  margin-bottom: 1rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
}}
.app-header h1 {{
  margin: 0;
  font-size: 1.65rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #ffffff !important;
}}
.app-header p {{
  margin: 0.3rem 0 0 0;
  opacity: 0.92;
  color: #ffffff !important;
}}

/* Section cards */
.section-card {{
  border: 1px solid rgba(128, 128, 128, 0.30);
  border-radius: 12px;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}}

/* Primary (purple) buttons */
.primary-btn {{
  background: var(--brand-purple) !important;
  border-color: var(--brand-purple) !important;
  color: #ffffff !important;
}}
.primary-btn:hover {{
  background: #5f2d77 !important;
  border-color: #5f2d77 !important;
}}

/* Success (blue) buttons */
.success-btn {{
  background: var(--brand-blue) !important;
  border-color: var(--brand-blue) !important;
  color: #ffffff !important;
}}
.success-btn:hover {{
  background: #1c83b3 !important;
  border-color: #1c83b3 !important;
}}

/* Accent (gold) buttons */
.accent-btn {{
  background: var(--brand-gold) !important;
  border-color: var(--brand-gold) !important;
  color: #1f2937 !important;
  font-weight: 600 !important;
}}
.accent-btn:hover {{
  background: #cf9a09 !important;
  border-color: #cf9a09 !important;
}}

/* Metric cards */
.metric-card label {{ font-weight: 600; }}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fmt_money(amount: float | int | None) -> str:
    """Format a number as ``$X.XX`` (with thousands separators)."""
    if amount is None:
        return "$0.00"
    return f"${amount:,.2f}"


def _holdings_to_dataframe(account: Account | None) -> pd.DataFrame:
    """Build a holdings DataFrame sorted by symbol."""
    if account is None:
        return pd.DataFrame(columns=["Symbol", "Quantity"])
    holdings = account.get_holdings()
    if not holdings:
        return pd.DataFrame(columns=["Symbol", "Quantity"])
    return pd.DataFrame(
        sorted(holdings.items(), key=lambda kv: kv[0]),
        columns=["Symbol", "Quantity"],
    )


def _transactions_to_dataframe(account: Account | None) -> pd.DataFrame:
    """Build a transactions DataFrame with the canonical column order."""
    columns = ["Timestamp", "Type", "Symbol", "Quantity", "Price", "Amount"]
    if account is None:
        return pd.DataFrame(columns=columns)
    rows = []
    for t in account.get_transactions():
        rows.append([
            t.timestamp,
            t.txn_type,
            t.symbol if t.symbol is not None else "",
            t.quantity if t.quantity is not None else "",
            fmt_money(t.price) if t.price is not None else "",
            fmt_money(t.amount),
        ])
    return pd.DataFrame(rows, columns=columns)


# ---------------------------------------------------------------------------
# Event handlers — each takes & returns ``account_state`` plus a status message
# ---------------------------------------------------------------------------
def create_account(name: str, account: Account | None):
    """Create a new ``Account`` and stash it in shared state."""
    if account is not None:
        return account, (
            f"ℹ️ Account **{account.name}** already exists. "
            "Restart the page to create a different one."
        )
    if not name or not str(name).strip():
        return None, "⚠️ Please enter a valid account name."
    acc = Account(str(name).strip())
    return acc, f"✅ Account **{acc.name}** created successfully."


def do_deposit(account: Account | None, amount):
    """Deposit cash into the account."""
    if account is None:
        return account, "⚠️ Please create an account first."
    try:
        amount_f = float(amount or 0)
    except (TypeError, ValueError):
        return account, f"❌ Error: '{amount}' is not a valid amount."
    try:
        account.deposit(amount_f)
    except (ValueError, InsufficientFundsError) as e:
        return account, f"❌ Error: {e}"
    return account, (
        f"✅ Deposited {fmt_money(amount_f)}. "
        f"Balance: **{fmt_money(account.get_balance())}**"
    )


def do_withdraw(account: Account | None, amount):
    """Withdraw cash from the account."""
    if account is None:
        return account, "⚠️ Please create an account first."
    try:
        amount_f = float(amount or 0)
    except (TypeError, ValueError):
        return account, f"❌ Error: '{amount}' is not a valid amount."
    try:
        account.withdraw(amount_f)
    except (ValueError, InsufficientFundsError) as e:
        return account, f"❌ Error: {e}"
    return account, (
        f"✅ Withdrew {fmt_money(amount_f)}. "
        f"Balance: **{fmt_money(account.get_balance())}**"
    )


def do_buy(account: Account | None, symbol: str, quantity):
    """Buy ``quantity`` shares of ``symbol``."""
    if account is None:
        return account, "⚠️ Please create an account first."
    sym = (symbol or "").strip().upper()
    if not sym:
        return account, "❌ Error: Please enter a symbol (e.g. AAPL)."
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        return account, f"❌ Error: '{quantity}' is not a valid quantity."
    try:
        account.buy(sym, qty)
    except (ValueError, InsufficientFundsError) as e:
        return account, f"❌ Error: {e}"
    return account, (
        f"✅ Bought **{qty}** shares of **{sym}**. "
        f"Cash balance: **{fmt_money(account.get_balance())}**"
    )


def do_sell(account: Account | None, symbol: str, quantity):
    """Sell ``quantity`` shares of ``symbol``."""
    if account is None:
        return account, "⚠️ Please create an account first."
    sym = (symbol or "").strip().upper()
    if not sym:
        return account, "❌ Error: Please enter a symbol (e.g. AAPL)."
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        return account, f"❌ Error: '{quantity}' is not a valid quantity."
    try:
        account.sell(sym, qty)
    except (ValueError, InsufficientHoldingsError) as e:
        return account, f"❌ Error: {e}"
    return account, (
        f"✅ Sold **{qty}** shares of **{sym}**. "
        f"Cash balance: **{fmt_money(account.get_balance())}**"
    )


def refresh_portfolio(account: Account | None):
    """Return updated cash, portfolio value, P&L and holdings DataFrame."""
    if account is None:
        return "—", "—", "—", _holdings_to_dataframe(None)
    return (
        fmt_money(account.get_balance()),
        fmt_money(account.get_portfolio_value()),
        fmt_money(account.get_profit_loss()),
        _holdings_to_dataframe(account),
    )


def refresh_transactions(account: Account | None):
    """Return the transactions DataFrame."""
    return _transactions_to_dataframe(account)


# ---------------------------------------------------------------------------
# UI construction
# ---------------------------------------------------------------------------
def build_demo() -> gr.Blocks:
    """Build the Gradio Blocks UI and return the constructed (un-launched) demo.

    In Gradio 6, ``theme`` and ``css`` belong on ``launch()`` rather than the
    ``Blocks`` constructor — we therefore keep the constructor minimal and
    apply the theme/css when the demo is launched. This also keeps module
    import warning-free.
    """
    with gr.Blocks(title="Trading Account Manager") as demo:
        # Shared session state — holds the Account instance, None until created.
        account_state = gr.State(None)

        # ---------- Header ----------
        gr.HTML(
            f"""
            <div class="app-header">
              <h1>📈 Trading Account Manager</h1>
              <p>Manage your simulated portfolio: deposit cash, buy &amp; sell
                 shares, and track your performance in real time.</p>
            </div>
            """
        )

        # ---------- Section 1: Account Setup ----------
        with gr.Group(elem_classes="section-card"):
            gr.Markdown("## 👤 Account Setup")
            with gr.Row():
                name_input = gr.Textbox(
                    label="Account holder name",
                    placeholder="e.g. Jane Doe",
                    scale=3,
                )
                create_btn = gr.Button(
                    "Create Account",
                    variant="primary",
                    elem_classes="primary-btn",
                    scale=1,
                )
            create_msg = gr.Markdown()

        # ---------- Section 2: Deposit / Withdraw ----------
        with gr.Group(elem_classes="section-card"):
            gr.Markdown("## 💵 Deposit / Withdraw")
            with gr.Row():
                amount_input = gr.Number(
                    label="Amount ($)",
                    value=0.0,
                    precision=2,
                    scale=3,
                )
                deposit_btn = gr.Button(
                    "Deposit",
                    variant="primary",
                    elem_classes="success-btn",
                    scale=1,
                )
                withdraw_btn = gr.Button(
                    "Withdraw",
                    elem_classes="accent-btn",
                    scale=1,
                )
            cash_msg = gr.Markdown()

        # ---------- Section 3: Buy / Sell ----------
        with gr.Group(elem_classes="section-card"):
            gr.Markdown("## 🛒 Buy / Sell Shares")
            gr.Markdown(
                "_Available symbols: **AAPL** ($150.00), "
                "**TSLA** ($250.00), **GOOGL** ($2,800.00)._"
            )
            with gr.Row():
                symbol_input = gr.Textbox(
                    label="Symbol",
                    placeholder="e.g. AAPL",
                    scale=2,
                )
                quantity_input = gr.Number(
                    label="Quantity",
                    value=0,
                    precision=0,
                    scale=2,
                )
                buy_btn = gr.Button(
                    "Buy",
                    variant="primary",
                    elem_classes="success-btn",
                    scale=1,
                )
                sell_btn = gr.Button(
                    "Sell",
                    elem_classes="accent-btn",
                    scale=1,
                )
            trade_msg = gr.Markdown()

        # ---------- Section 4: Portfolio Summary ----------
        with gr.Group(elem_classes="section-card"):
            gr.Markdown("## 📊 Portfolio Summary")
            with gr.Row():
                cash_display = gr.Textbox(
                    label="Cash Balance",
                    value="—",
                    interactive=False,
                    elem_classes="metric-card",
                )
                portfolio_value_display = gr.Textbox(
                    label="Portfolio Value",
                    value="—",
                    interactive=False,
                    elem_classes="metric-card",
                )
                profit_loss_display = gr.Textbox(
                    label="Profit / Loss",
                    value="—",
                    interactive=False,
                    elem_classes="metric-card",
                )
            holdings_table = gr.Dataframe(
                headers=["Symbol", "Quantity"],
                datatype=["str", "number"],
                label="Current Holdings",
                value=_holdings_to_dataframe(None),
                interactive=False,
            )
            refresh_portfolio_btn = gr.Button(
                "🔄 Refresh Portfolio",
                elem_classes="primary-btn",
            )

        # ---------- Section 5: Transaction History ----------
        with gr.Group(elem_classes="section-card"):
            gr.Markdown("## 🧾 Transaction History")
            transactions_table = gr.Dataframe(
                headers=["Timestamp", "Type", "Symbol", "Quantity", "Price", "Amount"],
                datatype=["str", "str", "str", "str", "str", "str"],
                label="Transactions",
                value=_transactions_to_dataframe(None),
                interactive=False,
            )
            refresh_txns_btn = gr.Button(
                "🔄 Refresh Transactions",
                elem_classes="primary-btn",
            )

        # ---------- Footer ----------
        gr.HTML(
            f"""
            <p style="text-align:center;color:gray;margin-top:1.5rem;">
              Built with Gradio ·
              <span style="color:{GOLD};font-size:1.1em;">●</span>
              <span style="color:{BLUE};font-size:1.1em;">●</span>
              <span style="color:{PURPLE};font-size:1.1em;">●</span>
            </p>
            """
        )

        # ---------- Event wiring ----------
        create_btn.click(
            fn=create_account,
            inputs=[name_input, account_state],
            outputs=[account_state, create_msg],
        )

        deposit_btn.click(
            fn=do_deposit,
            inputs=[account_state, amount_input],
            outputs=[account_state, cash_msg],
        )

        withdraw_btn.click(
            fn=do_withdraw,
            inputs=[account_state, amount_input],
            outputs=[account_state, cash_msg],
        )

        buy_btn.click(
            fn=do_buy,
            inputs=[account_state, symbol_input, quantity_input],
            outputs=[account_state, trade_msg],
        )

        sell_btn.click(
            fn=do_sell,
            inputs=[account_state, symbol_input, quantity_input],
            outputs=[account_state, trade_msg],
        )

        refresh_portfolio_btn.click(
            fn=refresh_portfolio,
            inputs=[account_state],
            outputs=[
                cash_display,
                portfolio_value_display,
                profit_loss_display,
                holdings_table,
            ],
        )

        refresh_txns_btn.click(
            fn=refresh_transactions,
            inputs=[account_state],
            outputs=[transactions_table],
        )

    return demo


# Module-level singleton — the Blocks instance is constructed at import time,
# which is exactly what ``_validate.py`` relies on.
demo = build_demo()


if __name__ == "__main__":
    # In Gradio 6, theme and css are passed to launch() rather than Blocks().
    demo.launch(theme=gr.themes.Soft(), css=CUSTOM_CSS)
