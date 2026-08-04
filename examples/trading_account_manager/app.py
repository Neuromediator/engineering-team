import gradio as gr
from datetime import datetime, timezone

from backend import AccountService

# ---------------------------------------------------------------------------
# Theming: custom palette that works in both light and dark mode.
# Palette:
#   Primary  (gold):    #ecad0a
#   Secondary (blue):   #209dd7
#   Accent   (purple):  #753991
# ---------------------------------------------------------------------------

THEME = gr.themes.Soft(
    primary_hue=gr.themes.Color(
        c50="#fff8e1",
        c100="#ffecb3",
        c200="#ffe082",
        c300="#ffd54f",
        c400="#ffca28",
        c500="#ecad0a",
        c600="#d19a09",
        c700="#a67908",
        c800="#7a5906",
        c900="#4d3803",
        c950="#2b1f02",
    ),
    secondary_hue=gr.themes.Color(
        c50="#e6f5fb",
        c100="#c1e6f4",
        c200="#98d5ed",
        c300="#6ec4e5",
        c400="#4eb7df",
        c500="#209dd7",
        c600="#1c8dc1",
        c700="#1670a0",
        c800="#0f537c",
        c900="#0a3956",
        c950="#052030",
    ),
    neutral_hue="slate",
    font=(gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"),
).set(
    body_background_fill="*neutral_50",
    body_background_fill_dark="*neutral_950",
    block_title_text_weight="600",
    button_primary_background_fill="#ecad0a",
    button_primary_background_fill_hover="#d19a09",
    button_primary_text_color="#1f1300",
    button_primary_background_fill_dark="#ecad0a",
    button_primary_background_fill_hover_dark="#ffca28",
    button_primary_text_color_dark="#1f1300",
    button_secondary_background_fill="#209dd7",
    button_secondary_background_fill_hover="#1c8dc1",
    button_secondary_text_color="#ffffff",
    button_secondary_background_fill_dark="#209dd7",
    button_secondary_background_fill_hover_dark="#4eb7df",
    button_secondary_text_color_dark="#ffffff",
)

# CSS tuned for both color schemes: uses CSS variables so it adapts automatically.
CUSTOM_CSS = """
:root {
    --tsam-gold: #ecad0a;
    --tsam-blue: #209dd7;
    --tsam-purple: #753991;
}

.gradio-container {
    max-width: 1200px !important;
    margin: 0 auto !important;
}

/* App header banner */
#tsam-header {
    background: linear-gradient(135deg, var(--tsam-purple) 0%, var(--tsam-blue) 100%);
    border-radius: 12px;
    padding: 18px 24px;
    margin-bottom: 8px;
    color: #ffffff;
    box-shadow: 0 4px 14px rgba(117, 57, 145, 0.25);
}
#tsam-header h1 {
    margin: 0;
    color: #ffffff !important;
    font-size: 1.6rem;
    letter-spacing: 0.2px;
}
#tsam-header p {
    margin: 4px 0 0 0;
    color: rgba(255, 255, 255, 0.9) !important;
    font-size: 0.95rem;
}

/* Section cards - subtle borders that render in both light/dark */
.tsam-card {
    border: 1px solid var(--border-color-primary);
    border-radius: 10px;
    padding: 14px 16px;
    background: var(--background-fill-secondary);
}
.tsam-card h2, .tsam-card h3 {
    margin-top: 0 !important;
    color: var(--body-text-color) !important;
}

/* Colored section accents on the left edge */
.tsam-accent-gold   { border-left: 4px solid var(--tsam-gold);   }
.tsam-accent-blue   { border-left: 4px solid var(--tsam-blue);   }
.tsam-accent-purple { border-left: 4px solid var(--tsam-purple); }

/* Status pill */
#tsam-status {
    padding: 10px 14px;
    border-radius: 8px;
    background: var(--background-fill-secondary);
    border: 1px solid var(--border-color-primary);
    color: var(--body-text-color);
    font-size: 0.95rem;
}

/* Summary block emphasis */
#tsam-summary {
    padding: 6px 4px;
    color: var(--body-text-color);
}
#tsam-summary strong {
    color: var(--tsam-blue);
}

/* Footer */
#tsam-footer {
    text-align: center;
    color: var(--body-text-color-subdued);
    font-size: 0.85rem;
    margin-top: 8px;
}
"""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_account_choices(service: AccountService) -> list[tuple[str, str]]:
    choices = []
    for account in service.list_accounts():
        label = f"{account.owner_name} — {account.account_id[:6]}"
        choices.append((label, account.account_id))
    return choices


def parse_optional_datetime(as_of_text: str | None) -> datetime | None:
    if not as_of_text or not as_of_text.strip():
        return None
    text = as_of_text.strip()
    # Accept trailing "Z" as UTC.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime format: {as_of_text!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_summary_markdown(summary: dict[str, object], as_of: datetime | None = None) -> str:
    as_of_str = as_of.isoformat() if as_of else "Now"
    pl = float(summary["profit_loss"])
    pl_pct = float(summary["profit_loss_percent"])
    pl_arrow = "▲" if pl > 0 else ("▼" if pl < 0 else "▬")
    return (
        f"### 📊 Account Summary  \n"
        f"*As of: `{as_of_str}`*\n\n"
        f"- **Account ID:** `{summary['account_id']}`\n"
        f"- **Owner:** {summary['owner_name']}\n"
        f"- **Cash Balance:** ${float(summary['cash_balance']):,.2f}\n"
        f"- **Portfolio Value:** ${float(summary['portfolio_value']):,.2f}\n"
        f"- **Total Account Value:** ${float(summary['total_account_value']):,.2f}\n"
        f"- **Profit / Loss:** {pl_arrow} ${pl:,.2f}  ({pl_pct:+.2f}%)\n"
    )


def format_holdings_rows(holdings_report: list[dict[str, object]]) -> list[list[object]]:
    return [
        [row["symbol"], row["quantity"], row["current_price"], row["market_value"]]
        for row in holdings_report
    ]


def format_transaction_rows(transaction_report: list[dict[str, object]]) -> list[list[object]]:
    return [
        [
            row["timestamp"],
            row["type"],
            row["symbol"],
            row["quantity"],
            row["price"],
            row["cash_amount"],
            row["description"],
        ]
        for row in transaction_report
    ]


def refresh_display(
    service: AccountService,
    account_id: str | None,
    as_of: datetime | None = None,
) -> tuple[str, list[list[object]], list[list[object]]]:
    if not account_id:
        return "_No account selected._", [], []

    summary = service.get_account_summary(account_id, as_of)
    holdings_report = service.get_holdings_report(account_id, as_of)
    transaction_report = service.get_transaction_report(account_id, as_of)

    return (
        format_summary_markdown(summary, as_of),
        format_holdings_rows(holdings_report),
        format_transaction_rows(transaction_report),
    )


# ---------------------------------------------------------------------------
# Event callbacks
# ---------------------------------------------------------------------------

def on_create_account(owner_name, initial_deposit, service):
    try:
        deposit = float(initial_deposit) if initial_deposit is not None else 0.0
        account = service.create_account(owner_name, deposit)
        choices = format_account_choices(service)
        summary, holdings, txs = refresh_display(service, account.account_id)
        return (
            account.account_id,
            gr.Dropdown(choices=choices, value=account.account_id, interactive=True),
            f"✅ Account created for **{account.owner_name}**.",
            summary,
            holdings,
            txs,
        )
    except Exception as e:
        return None, gr.Dropdown(), f"❌ Error: {e}", "_No account selected._", [], []


def on_select_account(account_id, service):
    if account_id:
        summary, holdings, txs = refresh_display(service, account_id)
        return account_id, "🔎 Account selected.", summary, holdings, txs
    return None, "_No account selected._", "_No account selected._", [], []


def on_deposit(account_id, amount, service):
    if not account_id:
        return "❌ Error: No account selected.", "_No account selected._", [], []
    try:
        service.deposit(account_id, float(amount))
        summary, holdings, txs = refresh_display(service, account_id)
        return f"💰 Deposited **${float(amount):,.2f}**.", summary, holdings, txs
    except Exception as e:
        summary, holdings, txs = refresh_display(service, account_id)
        return f"❌ Error: {e}", summary, holdings, txs


def on_withdraw(account_id, amount, service):
    if not account_id:
        return "❌ Error: No account selected.", "_No account selected._", [], []
    try:
        service.withdraw(account_id, float(amount))
        summary, holdings, txs = refresh_display(service, account_id)
        return f"🏧 Withdrew **${float(amount):,.2f}**.", summary, holdings, txs
    except Exception as e:
        summary, holdings, txs = refresh_display(service, account_id)
        return f"❌ Error: {e}", summary, holdings, txs


def on_buy(account_id, symbol, quantity, service):
    if not account_id:
        return "❌ Error: No account selected.", "_No account selected._", [], []
    try:
        qf = float(quantity)
        if not qf.is_integer():
            raise ValueError("Quantity must be a whole number.")
        service.buy_shares(account_id, symbol, int(qf))
        summary, holdings, txs = refresh_display(service, account_id)
        return f"🟢 Bought **{int(qf)} {symbol}**.", summary, holdings, txs
    except Exception as e:
        summary, holdings, txs = refresh_display(service, account_id)
        return f"❌ Error: {e}", summary, holdings, txs


def on_sell(account_id, symbol, quantity, service):
    if not account_id:
        return "❌ Error: No account selected.", "_No account selected._", [], []
    try:
        qf = float(quantity)
        if not qf.is_integer():
            raise ValueError("Quantity must be a whole number.")
        service.sell_shares(account_id, symbol, int(qf))
        summary, holdings, txs = refresh_display(service, account_id)
        return f"🔴 Sold **{int(qf)} {symbol}**.", summary, holdings, txs
    except Exception as e:
        summary, holdings, txs = refresh_display(service, account_id)
        return f"❌ Error: {e}", summary, holdings, txs


def on_refresh(account_id, service):
    if not account_id:
        return "_No account selected._", "_No account selected._", [], []
    summary, holdings, txs = refresh_display(service, account_id)
    return "🔄 Refreshed.", summary, holdings, txs


def on_historical_report(account_id, as_of_text, service):
    if not account_id:
        return "❌ Error: No account selected.", "_No account selected._", [], []
    try:
        dt = parse_optional_datetime(as_of_text)
        summary, holdings, txs = refresh_display(service, account_id, dt)
        msg_time = dt.isoformat() if dt else "Now"
        return f"🕒 Report generated as of `{msg_time}`.", summary, holdings, txs
    except Exception as e:
        summary, holdings, txs = refresh_display(service, account_id)
        return f"❌ Error: {e}", summary, holdings, txs


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def build_app() -> gr.Blocks:
    with gr.Blocks(
        title="Trading Simulation Account Manager",
        theme=THEME,
        css=CUSTOM_CSS,
    ) as demo:
        service_state = gr.State(value=AccountService())
        selected_account_state = gr.State(value=None)

        gr.HTML(
            """
            <div id="tsam-header">
                <h1>📈 Trading Simulation Account Manager</h1>
                <p>Create accounts, manage cash, trade AAPL / TSLA / GOOGL, and track P&amp;L over time.</p>
            </div>
            """
        )

        status_markdown = gr.Markdown("Ready.", elem_id="tsam-status")

        with gr.Row(equal_height=True):
            with gr.Column(scale=1):
                with gr.Group(elem_classes=["tsam-card", "tsam-accent-purple"]):
                    gr.Markdown("### 1. Account")
                    owner_name_input = gr.Textbox(
                        label="Owner Name",
                        placeholder="e.g. Alice Johnson",
                        lines=1,
                        interactive=True,
                    )
                    initial_deposit_input = gr.Number(
                        value=0,
                        label="Initial Deposit ($)",
                        precision=2,
                        interactive=True,
                    )
                    create_account_button = gr.Button(
                        value="Create Account",
                        variant="primary",
                        interactive=True,
                    )
                    account_dropdown = gr.Dropdown(
                        choices=[],
                        label="Active Account",
                        interactive=True,
                    )

            with gr.Column(scale=1):
                with gr.Group(elem_classes=["tsam-card", "tsam-accent-gold"]):
                    gr.Markdown("### 2. Cash Operations")
                    cash_amount_input = gr.Number(
                        value=0,
                        label="Amount ($)",
                        precision=2,
                        interactive=True,
                    )
                    with gr.Row():
                        deposit_button = gr.Button(
                            value="Deposit",
                            variant="primary",
                            interactive=True,
                        )
                        withdraw_button = gr.Button(
                            value="Withdraw",
                            variant="secondary",
                            interactive=True,
                        )

            with gr.Column(scale=1):
                with gr.Group(elem_classes=["tsam-card", "tsam-accent-blue"]):
                    gr.Markdown("### 3. Trading")
                    symbol_dropdown = gr.Dropdown(
                        choices=["AAPL", "TSLA", "GOOGL"],
                        value="AAPL",
                        label="Symbol",
                        interactive=True,
                    )
                    quantity_input = gr.Number(
                        value=1,
                        label="Quantity",
                        precision=0,
                        interactive=True,
                    )
                    with gr.Row():
                        buy_button = gr.Button(
                            value="Buy",
                            variant="primary",
                            interactive=True,
                        )
                        sell_button = gr.Button(
                            value="Sell",
                            variant="secondary",
                            interactive=True,
                        )

        with gr.Row():
            with gr.Column(scale=2):
                with gr.Group(elem_classes=["tsam-card", "tsam-accent-blue"]):
                    summary_markdown = gr.Markdown(
                        "_No account selected._",
                        elem_id="tsam-summary",
                    )
                    refresh_button = gr.Button(
                        value="🔄 Refresh Summary",
                        variant="secondary",
                        interactive=True,
                    )

            with gr.Column(scale=3):
                with gr.Group(elem_classes=["tsam-card", "tsam-accent-gold"]):
                    gr.Markdown("### Holdings")
                    holdings_dataframe = gr.Dataframe(
                        value=[],
                        headers=["Symbol", "Quantity", "Current Price", "Market Value"],
                        datatype=["str", "number", "number", "number"],
                        interactive=False,
                        wrap=True,
                    )

        with gr.Group(elem_classes=["tsam-card", "tsam-accent-purple"]):
            gr.Markdown("### Transaction History")
            transactions_dataframe = gr.Dataframe(
                value=[],
                headers=[
                    "Timestamp",
                    "Type",
                    "Symbol",
                    "Quantity",
                    "Price",
                    "Cash Amount",
                    "Description",
                ],
                datatype=["str", "str", "str", "str", "str", "number", "str"],
                interactive=False,
                wrap=True,
            )

        with gr.Group(elem_classes=["tsam-card", "tsam-accent-blue"]):
            gr.Markdown("### 5. Historical Reporting")
            with gr.Row():
                as_of_textbox = gr.Textbox(
                    label="As-Of Datetime (ISO format)",
                    placeholder="e.g. 2025-01-01T12:00:00Z",
                    lines=1,
                    interactive=True,
                    scale=3,
                )
                historical_report_button = gr.Button(
                    value="Generate Historical Report",
                    variant="primary",
                    interactive=True,
                    scale=1,
                )

        gr.HTML(
            '<div id="tsam-footer">Trading Simulation Platform · '
            "Prices are fixed for demo: AAPL $150.00 · TSLA $250.00 · GOOGL $2,800.00</div>"
        )

        # ------------------------- Wiring -------------------------

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

    return demo


if __name__ == "__main__":
    demo = build_app()
    demo.launch()
