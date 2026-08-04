"""Validation script - imports app.py and confirms the Blocks object constructs."""
import sys
import traceback


def main() -> int:
    try:
        import app
    except Exception:
        print("FAIL: Could not import app.py")
        traceback.print_exc()
        return 1

    try:
        demo = app.build_app()
    except Exception:
        print("FAIL: build_app() raised an exception")
        traceback.print_exc()
        return 1

    try:
        import gradio as gr
        assert isinstance(demo, gr.Blocks), f"Expected gr.Blocks, got {type(demo)!r}"
    except AssertionError as e:
        print(f"FAIL: {e}")
        return 1

    # Basic sanity checks on the formatting helpers.
    try:
        from backend import AccountService
        service = AccountService()
        account = service.create_account("Test User", 1000.0)
        service.buy_shares(account.account_id, "AAPL", 2)

        choices = app.format_account_choices(service)
        assert len(choices) == 1, "Expected one account choice"
        assert choices[0][1] == account.account_id

        summary = service.get_account_summary(account.account_id)
        md = app.format_summary_markdown(summary)
        assert "Account Summary" in md

        holdings = app.format_holdings_rows(
            service.get_holdings_report(account.account_id)
        )
        assert holdings and holdings[0][0] == "AAPL"

        txs = app.format_transaction_rows(
            service.get_transaction_report(account.account_id)
        )
        assert len(txs) == 2

        assert app.parse_optional_datetime("") is None
        assert app.parse_optional_datetime(None) is None
        dt = app.parse_optional_datetime("2025-01-01T12:00:00Z")
        assert dt is not None and dt.tzinfo is not None

        try:
            app.parse_optional_datetime("not-a-date")
        except ValueError:
            pass
        else:
            print("FAIL: expected ValueError for bad datetime")
            return 1
    except Exception:
        print("FAIL: Helper checks raised an exception")
        traceback.print_exc()
        return 1

    print("PASS: app.py imports, build_app() returns gr.Blocks, helpers work correctly.")
    print(f"  Blocks title: {demo.title!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
