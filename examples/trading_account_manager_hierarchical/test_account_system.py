"""Comprehensive unit tests for the account system backend module.

Uses only the Python standard library (``unittest``).
"""

import unittest

from account_system import (
    Account,
    InsufficientFundsError,
    InsufficientHoldingsError,
    Transaction,
    get_share_price,
)


class TestGetSharePrice(unittest.TestCase):
    """Tests for the standalone get_share_price lookup function."""

    def test_known_prices(self):
        self.assertEqual(get_share_price("AAPL"), 150.0)
        self.assertEqual(get_share_price("TSLA"), 250.0)
        self.assertEqual(get_share_price("GOOGL"), 2800.0)

    def test_unknown_symbol_raises_value_error(self):
        with self.assertRaises(ValueError):
            get_share_price("ZZZZ")

    def test_case_sensitive(self):
        with self.assertRaises(ValueError):
            get_share_price("aapl")
        with self.assertRaises(ValueError):
            get_share_price("Aapl")
        with self.assertRaises(ValueError):
            get_share_price("tsla")
        with self.assertRaises(ValueError):
            get_share_price("googl")


class TestAccountCreation(unittest.TestCase):
    """Tests for account creation and initial state."""

    def test_initial_state(self):
        acct = Account("Test User")
        self.assertEqual(acct.name, "Test User")
        self.assertEqual(acct.get_balance(), 0.0)
        self.assertEqual(acct.get_holdings(), {})
        self.assertEqual(acct.get_transactions(), [])
        self.assertEqual(acct.get_total_deposits(), 0.0)
        self.assertEqual(acct.get_portfolio_value(), 0.0)
        self.assertEqual(acct.get_profit_loss(), 0.0)


class TestCashOperations(unittest.TestCase):
    """Tests for deposit and withdraw."""

    def test_deposit_updates_balance(self):
        acct = Account("A")
        acct.deposit(100)
        self.assertEqual(acct.get_balance(), 100.0)
        self.assertEqual(acct.get_total_deposits(), 100.0)

    def test_deposit_adds_transaction(self):
        acct = Account("A")
        acct.deposit(100)
        txns = acct.get_transactions()
        self.assertEqual(len(txns), 1)
        txn = txns[0]
        self.assertIsInstance(txn, Transaction)
        self.assertEqual(txn.txn_type, "DEPOSIT")
        self.assertEqual(txn.amount, 100.0)
        self.assertIsNone(txn.symbol)
        self.assertIsNone(txn.quantity)
        self.assertIsNone(txn.price)

    def test_deposit_zero_raises(self):
        acct = Account("A")
        with self.assertRaises(ValueError):
            acct.deposit(0)
        self.assertEqual(acct.get_balance(), 0.0)
        self.assertEqual(len(acct.get_transactions()), 0)

    def test_deposit_negative_raises(self):
        acct = Account("A")
        with self.assertRaises(ValueError):
            acct.deposit(-50)
        self.assertEqual(acct.get_balance(), 0.0)

    def test_withdraw_success(self):
        acct = Account("A")
        acct.deposit(100)
        acct.withdraw(50)
        self.assertEqual(acct.get_balance(), 50.0)
        txns = acct.get_transactions()
        self.assertEqual(len(txns), 2)
        self.assertEqual(txns[1].txn_type, "WITHDRAW")
        self.assertEqual(txns[1].amount, -50.0)

    def test_withdraw_more_than_balance_raises(self):
        acct = Account("A")
        acct.deposit(100)
        with self.assertRaises(InsufficientFundsError):
            acct.withdraw(150)
        # state unchanged
        self.assertEqual(acct.get_balance(), 100.0)
        self.assertEqual(len(acct.get_transactions()), 1)

    def test_withdraw_zero_raises(self):
        acct = Account("A")
        acct.deposit(100)
        with self.assertRaises(ValueError):
            acct.withdraw(0)
        self.assertEqual(acct.get_balance(), 100.0)

    def test_withdraw_negative_raises(self):
        acct = Account("A")
        acct.deposit(100)
        with self.assertRaises(ValueError):
            acct.withdraw(-10)
        self.assertEqual(acct.get_balance(), 100.0)


class TestBuy(unittest.TestCase):
    """Tests for the buy operation."""

    def setUp(self):
        self.acct = Account("A")
        self.acct.deposit(10000)

    def test_successful_buy(self):
        self.acct.buy("AAPL", 10)  # cost 1500
        self.assertEqual(self.acct.get_balance(), 10000 - 1500)
        self.assertEqual(self.acct.get_holdings(), {"AAPL": 10})
        txns = self.acct.get_transactions()
        self.assertEqual(txns[-1].txn_type, "BUY")
        self.assertEqual(txns[-1].symbol, "AAPL")
        self.assertEqual(txns[-1].quantity, 10)
        self.assertEqual(txns[-1].price, 150.0)
        self.assertEqual(txns[-1].amount, -1500.0)

    def test_buy_unknown_symbol_propagates_value_error(self):
        before_balance = self.acct.get_balance()
        with self.assertRaises(ValueError):
            self.acct.buy("ZZZZ", 1)
        self.assertEqual(self.acct.get_balance(), before_balance)
        self.assertEqual(self.acct.get_holdings(), {})

    def test_buy_zero_quantity_raises(self):
        with self.assertRaises(ValueError):
            self.acct.buy("AAPL", 0)
        self.assertEqual(self.acct.get_holdings(), {})

    def test_buy_negative_quantity_raises(self):
        with self.assertRaises(ValueError):
            self.acct.buy("AAPL", -5)
        self.assertEqual(self.acct.get_holdings(), {})

    def test_buy_exceeds_cash_raises(self):
        before_balance = self.acct.get_balance()
        with self.assertRaises(InsufficientFundsError):
            self.acct.buy("GOOGL", 10)  # cost 28000 > 10000
        # state unchanged
        self.assertEqual(self.acct.get_balance(), before_balance)
        self.assertEqual(self.acct.get_holdings(), {})
        self.assertEqual(len(self.acct.get_transactions()), 1)  # only deposit

    def test_multiple_buys_accumulate(self):
        self.acct.buy("AAPL", 3)
        self.acct.buy("AAPL", 4)
        self.assertEqual(self.acct.get_holdings(), {"AAPL": 7})
        self.assertEqual(self.acct.get_balance(), 10000 - 150.0 * 7)
        buys = [t for t in self.acct.get_transactions() if t.txn_type == "BUY"]
        self.assertEqual(len(buys), 2)


class TestSell(unittest.TestCase):
    """Tests for the sell operation."""

    def setUp(self):
        self.acct = Account("A")
        self.acct.deposit(10000)
        self.acct.buy("AAPL", 10)

    def test_successful_sell(self):
        self.acct.sell("AAPL", 3)
        self.assertEqual(self.acct.get_holdings(), {"AAPL": 7})
        self.assertEqual(self.acct.get_balance(), 10000 - 1500 + 450)
        txns = self.acct.get_transactions()
        self.assertEqual(txns[-1].txn_type, "SELL")
        self.assertEqual(txns[-1].symbol, "AAPL")
        self.assertEqual(txns[-1].quantity, 3)
        self.assertEqual(txns[-1].price, 150.0)
        self.assertEqual(txns[-1].amount, 450.0)

    def test_sell_more_than_holdings_raises(self):
        before = self.acct.get_balance()
        before_holdings = self.acct.get_holdings()
        with self.assertRaises(InsufficientHoldingsError):
            self.acct.sell("AAPL", 11)
        self.assertEqual(self.acct.get_balance(), before)
        self.assertEqual(self.acct.get_holdings(), before_holdings)
        self.assertEqual(
            len([t for t in self.acct.get_transactions() if t.txn_type == "SELL"]),
            0,
        )

    def test_sell_exact_holdings_removes_symbol(self):
        self.acct.sell("AAPL", 10)
        self.assertEqual(self.acct.get_holdings(), {})
        self.assertNotIn("AAPL", self.acct.get_holdings())

    def test_sell_zero_quantity_raises(self):
        with self.assertRaises(ValueError):
            self.acct.sell("AAPL", 0)
        self.assertEqual(self.acct.get_holdings(), {"AAPL": 10})

    def test_sell_negative_quantity_raises(self):
        with self.assertRaises(ValueError):
            self.acct.sell("AAPL", -3)
        self.assertEqual(self.acct.get_holdings(), {"AAPL": 10})

    def test_sell_unowned_symbol_raises(self):
        with self.assertRaises(InsufficientHoldingsError):
            self.acct.sell("TSLA", 1)


class TestQueries(unittest.TestCase):
    """Tests for query methods."""

    def setUp(self):
        self.acct = Account("A")
        self.acct.deposit(10000)
        self.acct.buy("AAPL", 10)  # 1500
        self.acct.buy("TSLA", 5)   # 1250
        # balance = 10000 - 1500 - 1250 = 7250

    def test_holdings_returns_copy(self):
        holdings = self.acct.get_holdings()
        holdings["GOOGL"] = 999
        holdings["AAPL"] = -5
        self.assertEqual(self.acct.get_holdings(), {"AAPL": 10, "TSLA": 5})

    def test_balance_reflects_cash_movements(self):
        self.assertEqual(self.acct.get_balance(), 7250.0)

    def test_portfolio_value(self):
        expected = 7250.0 + (10 * 150.0) + (5 * 250.0)
        self.assertEqual(self.acct.get_portfolio_value(), expected)

    def test_total_deposits_sums_only_deposits(self):
        self.assertEqual(self.acct.get_total_deposits(), 10000.0)

    def test_profit_loss(self):
        pv = self.acct.get_portfolio_value()
        self.assertEqual(self.acct.get_profit_loss(), pv - 10000.0)

    def test_transactions_returns_copy(self):
        txns = self.acct.get_transactions()
        txns.clear()
        self.assertEqual(len(self.acct.get_transactions()), 3)


class TestIntegration(unittest.TestCase):
    """End-to-end workflow integration tests."""

    def test_full_workflow(self):
        acct = Account("Trader")
        acct.deposit(10000)
        acct.buy("AAPL", 10)   # -1500
        acct.buy("TSLA", 5)    # -1250
        acct.sell("AAPL", 3)   # +450

        # cash = 10000 - 1500 - 1250 + 450 = 7700
        self.assertEqual(acct.get_balance(), 7700.0)
        self.assertEqual(acct.get_holdings(), {"AAPL": 7, "TSLA": 5})

        expected_pv = 7700.0 + (7 * 150.0) + (5 * 250.0)
        self.assertEqual(acct.get_portfolio_value(), expected_pv)
        self.assertEqual(acct.get_total_deposits(), 10000.0)
        self.assertEqual(acct.get_profit_loss(), expected_pv - 10000.0)

        txns = acct.get_transactions()
        types = [t.txn_type for t in txns]
        self.assertEqual(types, ["DEPOSIT", "BUY", "BUY", "SELL"])

    def test_sell_all_removes_symbol_from_holdings(self):
        acct = Account("A")
        acct.deposit(10000)
        acct.buy("AAPL", 10)
        acct.buy("TSLA", 5)
        acct.sell("AAPL", 10)
        self.assertNotIn("AAPL", acct.get_holdings())
        self.assertEqual(acct.get_holdings(), {"TSLA": 5})
        self.assertEqual(acct.get_balance(), 10000 - 1250)


if __name__ == "__main__":
    unittest.main()
