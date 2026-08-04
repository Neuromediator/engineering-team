import unittest
from datetime import datetime, timedelta, timezone

from backend import AccountService, TransactionType


class TestBackend(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AccountService()

    def test_create_account_without_initial_deposit(self):
        account = self.service.create_account("Alice")
        self.assertEqual(account.owner_name, "Alice")
        self.assertEqual(len(account.transactions), 0)
        self.assertEqual(self.service.get_cash_balance(account.account_id), 0.0)
        self.assertEqual(self.service.get_holdings(account.account_id), {})

    def test_create_account_with_initial_deposit(self):
        account = self.service.create_account("Bob", 1000.0)
        self.assertEqual(len(account.transactions), 1)
        self.assertEqual(account.transactions[0].transaction_type, TransactionType.DEPOSIT)
        self.assertEqual(self.service.get_cash_balance(account.account_id), 1000.0)
        self.assertEqual(self.service.get_profit_loss(account.account_id), 0.0)

    def test_create_account_rejects_blank_owner_name(self):
        with self.assertRaises(ValueError):
            self.service.create_account("")
        with self.assertRaises(ValueError):
            self.service.create_account("   ")

    def test_create_account_rejects_negative_initial_deposit(self):
        with self.assertRaises(ValueError):
            self.service.create_account("Charlie", -10)

    def test_deposit_increases_cash_balance(self):
        account = self.service.create_account("Alice")
        self.service.deposit(account.account_id, 500)
        self.assertEqual(self.service.get_cash_balance(account.account_id), 500.0)
        self.assertEqual(len(account.transactions), 1)
        self.assertEqual(account.transactions[0].transaction_type, TransactionType.DEPOSIT)

    def test_deposit_rejects_non_positive_amount(self):
        account = self.service.create_account("Alice")
        with self.assertRaises(ValueError):
            self.service.deposit(account.account_id, 0)
        with self.assertRaises(ValueError):
            self.service.deposit(account.account_id, -100)

    def test_withdraw_decreases_cash_balance(self):
        account = self.service.create_account("Alice", 1000)
        self.service.withdraw(account.account_id, 200)
        self.assertEqual(self.service.get_cash_balance(account.account_id), 800.0)
        self.assertEqual(account.transactions[1].transaction_type, TransactionType.WITHDRAWAL)

    def test_withdraw_rejects_insufficient_cash(self):
        account = self.service.create_account("Alice", 100)
        with self.assertRaises(ValueError):
            self.service.withdraw(account.account_id, 101)
        self.assertEqual(self.service.get_cash_balance(account.account_id), 100.0)
        self.assertEqual(len(account.transactions), 1)

    def test_withdraw_rejects_non_positive_amount(self):
        account = self.service.create_account("Alice", 1000)
        with self.assertRaises(ValueError):
            self.service.withdraw(account.account_id, 0)
        with self.assertRaises(ValueError):
            self.service.withdraw(account.account_id, -100)

    def test_buy_shares_decreases_cash_and_increases_holdings(self):
        account = self.service.create_account("Alice", 1000)
        self.service.buy_shares(account.account_id, "AAPL", 2)
        self.assertEqual(self.service.get_cash_balance(account.account_id), 700.0)
        self.assertEqual(self.service.get_holdings(account.account_id), {"AAPL": 2})
        self.assertEqual(self.service.get_portfolio_value(account.account_id), 300.0)
        self.assertEqual(self.service.get_total_account_value(account.account_id), 1000.0)

    def test_buy_rejects_insufficient_cash(self):
        account = self.service.create_account("Alice", 100)
        with self.assertRaises(ValueError):
            self.service.buy_shares(account.account_id, "AAPL", 1)
        self.assertEqual(self.service.get_cash_balance(account.account_id), 100.0)
        self.assertEqual(self.service.get_holdings(account.account_id), {})
        self.assertEqual(len(account.transactions), 1)

    def test_buy_rejects_invalid_quantity(self):
        account = self.service.create_account("Alice", 1000)
        with self.assertRaises(ValueError):
            self.service.buy_shares(account.account_id, "AAPL", 0)
        with self.assertRaises(ValueError):
            self.service.buy_shares(account.account_id, "AAPL", -1)
        with self.assertRaises(ValueError):
            self.service.buy_shares(account.account_id, "AAPL", 1.5)

    def test_buy_rejects_unknown_symbol(self):
        account = self.service.create_account("Alice", 1000)
        with self.assertRaises(ValueError):
            self.service.buy_shares(account.account_id, "UNKNOWN", 1)

    def test_buy_normalizes_symbol(self):
        account = self.service.create_account("Alice", 1000)
        self.service.buy_shares(account.account_id, " aapl ", 1)
        self.assertEqual(self.service.get_holdings(account.account_id), {"AAPL": 1})

    def test_sell_shares_increases_cash_and_decreases_holdings(self):
        account = self.service.create_account("Alice", 1000)
        self.service.buy_shares(account.account_id, "AAPL", 2)
        self.service.sell_shares(account.account_id, "AAPL", 1)
        self.assertEqual(self.service.get_holdings(account.account_id), {"AAPL": 1})
        self.assertEqual(self.service.get_cash_balance(account.account_id), 850.0)

    def test_sell_all_shares_removes_holding_from_holdings_report(self):
        account = self.service.create_account("Alice", 1000)
        self.service.buy_shares(account.account_id, "AAPL", 1)
        self.service.sell_shares(account.account_id, "AAPL", 1)
        self.assertEqual(self.service.get_holdings(account.account_id), {})

    def test_sell_rejects_insufficient_holdings(self):
        account = self.service.create_account("Alice", 1000)
        self.service.buy_shares(account.account_id, "AAPL", 1)
        with self.assertRaises(ValueError):
            self.service.sell_shares(account.account_id, "AAPL", 2)
        self.assertEqual(self.service.get_holdings(account.account_id), {"AAPL": 1})
        self.assertEqual(len(account.transactions), 2)

    def test_sell_rejects_symbol_not_owned(self):
        account = self.service.create_account("Alice", 1000)
        with self.assertRaises(ValueError):
            self.service.sell_shares(account.account_id, "TSLA", 1)

    def test_portfolio_value_multiple_symbols(self):
        account = self.service.create_account("Alice", 10000)
        self.service.buy_shares(account.account_id, "AAPL", 2)
        self.service.buy_shares(account.account_id, "TSLA", 3)
        self.assertEqual(self.service.get_portfolio_value(account.account_id), 1050.0)

    def test_total_account_value_cash_plus_portfolio(self):
        account = self.service.create_account("Alice", 10000)
        self.service.buy_shares(account.account_id, "AAPL", 2)
        self.assertEqual(self.service.get_cash_balance(account.account_id), 9700.0)
        self.assertEqual(self.service.get_portfolio_value(account.account_id), 300.0)
        self.assertEqual(self.service.get_total_account_value(account.account_id), 10000.0)

    def test_profit_loss_zero_when_prices_unchanged_after_buy(self):
        account = self.service.create_account("Alice", 1000)
        self.service.buy_shares(account.account_id, "AAPL", 2)
        self.assertEqual(self.service.get_profit_loss(account.account_id), 0.0)

    def test_profit_loss_accounts_for_withdrawals(self):
        account = self.service.create_account("Alice", 1000)
        self.service.withdraw(account.account_id, 200)
        self.assertEqual(self.service.get_total_account_value(account.account_id), 800.0)
        self.assertEqual(self.service.get_profit_loss(account.account_id), 0.0)

    def test_profit_loss_accounts_for_multiple_deposits(self):
        account = self.service.create_account("Alice", 1000)
        self.service.deposit(account.account_id, 500)
        self.assertEqual(self.service.get_total_account_value(account.account_id), 1500.0)
        self.assertEqual(self.service.get_profit_loss(account.account_id), 0.0)

    def test_list_transactions_returns_transactions_in_order(self):
        account = self.service.create_account("Alice", 1000)
        self.service.buy_shares(account.account_id, "AAPL", 1)
        self.service.deposit(account.account_id, 500)
        txs = self.service.list_transactions(account.account_id)
        self.assertEqual(len(txs), 3)
        self.assertTrue(txs[0].timestamp <= txs[1].timestamp <= txs[2].timestamp)

    def test_transaction_report_has_expected_fields(self):
        account = self.service.create_account("Alice", 1000)
        report = self.service.get_transaction_report(account.account_id)
        self.assertEqual(len(report), 1)
        expected_keys = {"timestamp", "type", "symbol", "quantity", "price", "cash_amount", "description"}
        self.assertEqual(set(report[0].keys()), expected_keys)

    def test_get_holdings_as_of_timestamp(self):
        account = self.service.create_account("Alice", 1000)
        txs = self.service.list_transactions(account.account_id)
        as_of_deposit = txs[0].timestamp

        self.service.buy_shares(account.account_id, "AAPL", 1)
        txs = self.service.list_transactions(account.account_id)
        as_of_first_buy = txs[1].timestamp

        self.service.buy_shares(account.account_id, "TSLA", 1)

        self.assertEqual(self.service.get_holdings(account.account_id, as_of=as_of_deposit), {})
        self.assertEqual(self.service.get_holdings(account.account_id, as_of=as_of_first_buy), {"AAPL": 1})
        self.assertEqual(self.service.get_holdings(account.account_id), {"AAPL": 1, "TSLA": 1})

    def test_get_cash_balance_as_of_timestamp(self):
        account = self.service.create_account("Alice", 1000)
        t_deposit = self.service.list_transactions(account.account_id)[-1].timestamp
        self.service.buy_shares(account.account_id, "AAPL", 2)
        t_buy = self.service.list_transactions(account.account_id)[-1].timestamp
        self.service.withdraw(account.account_id, 100)
        t_withdraw = self.service.list_transactions(account.account_id)[-1].timestamp

        self.assertEqual(self.service.get_cash_balance(account.account_id, as_of=t_deposit), 1000.0)
        self.assertEqual(self.service.get_cash_balance(account.account_id, as_of=t_buy), 700.0)
        self.assertEqual(self.service.get_cash_balance(account.account_id, as_of=t_withdraw), 600.0)

    def test_get_profit_loss_as_of_timestamp(self):
        account = self.service.create_account("Alice", 1000)
        t_deposit = self.service.list_transactions(account.account_id)[-1].timestamp
        self.assertEqual(self.service.get_profit_loss(account.account_id, as_of=t_deposit), 0.0)

    def test_get_account_summary_contains_expected_values(self):
        account = self.service.create_account("Alice", 1000)
        summary = self.service.get_account_summary(account.account_id)
        expected_keys = {
            "account_id",
            "owner_name",
            "cash_balance",
            "portfolio_value",
            "total_account_value",
            "profit_loss",
            "profit_loss_percent",
            "holdings",
        }
        self.assertEqual(set(summary.keys()), expected_keys)

    def test_failed_buy_does_not_mutate_state(self):
        account = self.service.create_account("Alice", 1000)
        before = list(account.transactions)
        with self.assertRaises(ValueError):
            self.service.buy_shares(account.account_id, "AAPL", 100)
        self.assertEqual(account.transactions, before)

    def test_failed_sell_does_not_mutate_state(self):
        account = self.service.create_account("Alice", 1000)
        self.service.buy_shares(account.account_id, "AAPL", 1)
        before = list(account.transactions)
        with self.assertRaises(ValueError):
            self.service.sell_shares(account.account_id, "AAPL", 2)
        self.assertEqual(account.transactions, before)

    def test_historical_report_uses_only_prior_transactions(self):
        account = self.service.create_account("Alice", 1000)
        deposit_tx = self.service.list_transactions(account.account_id)[0]
        self.service.buy_shares(account.account_id, "AAPL", 2)
        buy_tx = self.service.list_transactions(account.account_id)[1]
        self.service.withdraw(account.account_id, 100)

        self.assertEqual(self.service.get_cash_balance(account.account_id, as_of=deposit_tx.timestamp), 1000.0)
        self.assertEqual(self.service.get_holdings(account.account_id, as_of=deposit_tx.timestamp), {})
        self.assertEqual(self.service.get_cash_balance(account.account_id, as_of=buy_tx.timestamp), 700.0)
        self.assertEqual(self.service.get_holdings(account.account_id, as_of=buy_tx.timestamp), {"AAPL": 2})

    def test_list_accounts_sorted_by_creation_time(self):
        first = self.service.create_account("Alice")
        second = self.service.create_account("Bob")
        accounts = self.service.list_accounts()
        self.assertEqual([a.account_id for a in accounts], [first.account_id, second.account_id])


if __name__ == "__main__":
    unittest.main()
