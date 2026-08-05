import unittest
from datetime import datetime, timedelta, timezone

from account import (
    Account,
    Holding,
    TransactionType,
    get_share_price,
)


class TestGetSharePrice(unittest.TestCase):
    def test_known_symbols(self):
        self.assertEqual(get_share_price("AAPL"), 150.0)
        self.assertEqual(get_share_price("TSLA"), 200.0)
        self.assertEqual(get_share_price("GOOGL"), 120.0)

    def test_unknown_symbol_raises(self):
        with self.assertRaises(ValueError):
            get_share_price("UNKNOWN")


class TestAccountCreation(unittest.TestCase):
    def test_create_account_defaults(self):
        acc = Account("A1", "Alice")
        self.assertEqual(acc.balance, 0.0)
        self.assertEqual(acc.transactions, [])
        self.assertEqual(acc.get_holdings(), [])

    def test_account_properties(self):
        acc = Account("A1", "Alice")
        self.assertEqual(acc.account_id, "A1")
        self.assertEqual(acc.owner_name, "Alice")


class TestDeposit(unittest.TestCase):
    def test_deposit_positive(self):
        acc = Account("A1", "Alice")
        acc.deposit(1000)
        self.assertEqual(acc.balance, 1000.0)
        self.assertEqual(len(acc.transactions), 1)
        self.assertEqual(acc.transactions[0].type, TransactionType.DEPOSIT)
        self.assertEqual(acc.initial_deposit, 1000.0)

    def test_deposit_sets_initial_deposit_once(self):
        acc = Account("A1", "Alice")
        acc.deposit(1000)
        acc.deposit(500)
        self.assertEqual(acc.initial_deposit, 1000.0)
        self.assertEqual(acc.balance, 1500.0)

    def test_deposit_zero_raises(self):
        acc = Account("A1", "Alice")
        with self.assertRaises(ValueError):
            acc.deposit(0)

    def test_deposit_negative_raises(self):
        acc = Account("A1", "Alice")
        with self.assertRaises(ValueError):
            acc.deposit(-100)

    def test_transaction_recorded_correctly(self):
        acc = Account("A1", "Alice")
        tx = acc.deposit(1000)
        self.assertEqual(tx.type, TransactionType.DEPOSIT)
        self.assertEqual(tx.amount, 1000.0)
        self.assertEqual(tx.balance_after, 1000.0)
        self.assertIsNotNone(tx.timestamp)
        self.assertEqual(tx.symbol, None)
        self.assertEqual(tx.quantity, 0)


class TestWithdraw(unittest.TestCase):
    def setUp(self):
        self.acc = Account("A1", "Alice")

    def test_withdraw_sufficient(self):
        self.acc.deposit(1000)
        self.acc.withdraw(300)
        self.assertEqual(self.acc.balance, 700.0)
        self.assertEqual(len(self.acc.transactions), 2)

    def test_withdraw_exact_balance(self):
        self.acc.deposit(500)
        self.acc.withdraw(500)
        self.assertEqual(self.acc.balance, 0.0)

    def test_withdraw_insufficient_raises(self):
        self.acc.deposit(100)
        with self.assertRaises(ValueError):
            self.acc.withdraw(200)

    def test_withdraw_zero_raises(self):
        self.acc.deposit(100)
        with self.assertRaises(ValueError):
            self.acc.withdraw(0)

    def test_withdraw_negative_raises(self):
        self.acc.deposit(100)
        with self.assertRaises(ValueError):
            self.acc.withdraw(-50)

    def test_withdraw_no_deposit_raises(self):
        with self.assertRaises(ValueError):
            self.acc.withdraw(100)


class TestBuyShares(unittest.TestCase):
    def setUp(self):
        self.acc = Account("A1", "Alice")
        self.acc.deposit(10000)

    def test_buy_success(self):
        tx = self.acc.buy_shares("AAPL", 10)
        self.assertEqual(self.acc.balance, 10000 - 1500)
        holding = self.acc.get_holdings()[0]
        self.assertEqual(holding.symbol, "AAPL")
        self.assertEqual(holding.quantity, 10)

    def test_buy_updates_holdings_and_cost_basis(self):
        self.acc.buy_shares("AAPL", 10)
        self.acc.buy_shares("AAPL", 5)
        holding = self.acc.get_holdings()[0]
        self.assertEqual(holding.quantity, 15)
        self.assertEqual(holding.average_cost, 150.0)

    def test_buy_multiple_symbols(self):
        self.acc.buy_shares("AAPL", 10)
        self.acc.buy_shares("TSLA", 5)
        symbols = {h.symbol for h in self.acc.get_holdings()}
        self.assertEqual(symbols, {"AAPL", "TSLA"})

    def test_buy_insufficient_funds_raises(self):
        acc = Account("A2", "Bob")
        acc.deposit(100)
        with self.assertRaises(ValueError):
            acc.buy_shares("AAPL", 1)

    def test_buy_invalid_symbol_raises(self):
        with self.assertRaises(ValueError):
            self.acc.buy_shares("UNKNOWN", 1)

    def test_buy_zero_qty_raises(self):
        with self.assertRaises(ValueError):
            self.acc.buy_shares("AAPL", 0)

    def test_buy_negative_qty_raises(self):
        with self.assertRaises(ValueError):
            self.acc.buy_shares("AAPL", -5)

    def test_buy_transaction_correct(self):
        tx = self.acc.buy_shares("AAPL", 10)
        self.assertEqual(tx.type, TransactionType.BUY)
        self.assertEqual(tx.symbol, "AAPL")
        self.assertEqual(tx.quantity, 10)
        self.assertEqual(tx.price, 150.0)
        self.assertEqual(tx.amount, 1500.0)
        self.assertEqual(tx.balance_after, 10000 - 1500)


class TestSellShares(unittest.TestCase):
    def setUp(self):
        self.acc = Account("A1", "Alice")
        self.acc.deposit(10000)
        self.acc.buy_shares("AAPL", 10)

    def test_sell_success(self):
        self.acc.sell_shares("AAPL", 5)
        self.assertEqual(self.acc.balance, 10000 - 1500 + 5 * 150)
        holding = self.acc.get_holdings()[0]
        self.assertEqual(holding.quantity, 5)

    def test_sell_all_shares(self):
        self.acc.sell_shares("AAPL", 10)
        self.assertEqual(self.acc.get_holdings(), [])

    def test_sell_more_than_held_raises(self):
        acc = Account("A2", "Bob")
        acc.deposit(10000)
        acc.buy_shares("AAPL", 5)
        with self.assertRaises(ValueError):
            acc.sell_shares("AAPL", 10)

    def test_sell_without_holding_raises(self):
        acc = Account("A2", "Bob")
        acc.deposit(10000)
        with self.assertRaises(ValueError):
            acc.sell_shares("AAPL", 1)

    def test_sell_invalid_symbol_raises(self):
        with self.assertRaises(ValueError):
            self.acc.sell_shares("UNKNOWN", 1)

    def test_sell_zero_qty_raises(self):
        with self.assertRaises(ValueError):
            self.acc.sell_shares("AAPL", 0)

    def test_sell_negative_qty_raises(self):
        with self.assertRaises(ValueError):
            self.acc.sell_shares("AAPL", -1)

    def test_sell_transaction_correct(self):
        tx = self.acc.sell_shares("AAPL", 5)
        self.assertEqual(tx.type, TransactionType.SELL)
        self.assertEqual(tx.symbol, "AAPL")
        self.assertEqual(tx.quantity, 5)
        self.assertEqual(tx.price, 150.0)
        self.assertEqual(tx.amount, 750.0)
        self.assertEqual(tx.balance_after, 10000 - 1500 + 750)

    def test_sell_updates_cost_basis_proportionally(self):
        self.acc.sell_shares("AAPL", 5)
        holding = self.acc.get_holdings()[0]
        self.assertEqual(holding.average_cost, 150.0)


class TestHoldingsAndPortfolioValue(unittest.TestCase):
    def test_empty_holdings(self):
        acc = Account("A1", "Alice")
        self.assertEqual(acc.get_holdings(), [])

    def test_holdings_after_buy(self):
        acc = Account("A1", "Alice")
        acc.deposit(10000)
        acc.buy_shares("AAPL", 10)
        acc.buy_shares("TSLA", 5)
        holdings = {h.symbol: h for h in acc.get_holdings()}
        self.assertEqual(holdings["AAPL"].quantity, 10)
        self.assertEqual(holdings["AAPL"].average_cost, 150.0)
        self.assertEqual(holdings["TSLA"].quantity, 5)
        self.assertEqual(holdings["TSLA"].average_cost, 200.0)

    def test_holdings_avg_cost_weighted(self):
        acc = Account("A1", "Alice")
        acc.deposit(10000)
        acc.buy_shares("AAPL", 10)
        acc.buy_shares("AAPL", 5)
        holding = acc.get_holdings()[0]
        self.assertEqual(holding.average_cost, 150.0)

    def test_portfolio_value_empty(self):
        acc = Account("A1", "Alice")
        self.assertEqual(acc.get_portfolio_value(), 0.0)

    def test_portfolio_value_after_buys(self):
        acc = Account("A1", "Alice")
        acc.deposit(10000)
        acc.buy_shares("AAPL", 10)
        acc.buy_shares("TSLA", 5)
        self.assertEqual(acc.get_portfolio_value(), 10 * 150 + 5 * 200)

    def test_portfolio_value_after_partial_sell(self):
        acc = Account("A1", "Alice")
        acc.deposit(10000)
        acc.buy_shares("AAPL", 10)
        acc.sell_shares("AAPL", 3)
        self.assertEqual(acc.get_portfolio_value(), 7 * 150)


class TestProfitOrLoss(unittest.TestCase):
    def test_pl_no_trades(self):
        acc = Account("A1", "Alice")
        acc.deposit(1000)
        self.assertEqual(acc.get_profit_or_loss(), 0.0)

    def test_pl_after_buy_no_price_change(self):
        acc = Account("A1", "Alice")
        acc.deposit(1000)
        acc.buy_shares("AAPL", 5)
        self.assertEqual(acc.get_profit_or_loss(), 0.0)

    def test_pl_after_multiple_ops(self):
        acc = Account("A1", "Alice")
        acc.deposit(2000)
        acc.buy_shares("AAPL", 5)   # 750
        acc.buy_shares("TSLA", 2)   # 400
        acc.sell_shares("AAPL", 2)  # +300
        expected = (acc.balance + acc.get_portfolio_value()) - acc.initial_deposit
        self.assertAlmostEqual(acc.get_profit_or_loss(), expected)

    def test_pl_after_full_sell(self):
        acc = Account("A1", "Alice")
        acc.deposit(1000)
        acc.buy_shares("AAPL", 5)
        acc.sell_shares("AAPL", 5)
        self.assertEqual(acc.get_profit_or_loss(), 0.0)


class TestHistoricalSnapshots(unittest.TestCase):
    def _make_account_with_controlled_times(self):
        # We create transactions and then manipulate timestamps directly
        # to simulate historical snapshots.
        acc = Account("A1", "Alice")
        acc.deposit(1000)
        acc.buy_shares("AAPL", 5)
        acc.sell_shares("AAPL", 5)
        return acc

    def test_holdings_at_past_time(self):
        acc = self._make_account_with_controlled_times()
        txs = acc.get_transactions()
        past = txs[1].timestamp  # after buy, before sell
        holdings = acc.get_holdings_at(past)
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0].symbol, "AAPL")
        self.assertEqual(holdings[0].quantity, 5)

    def test_holdings_at_before_all_txns(self):
        acc = self._make_account_with_controlled_times()
        earliest = acc.get_transactions()[0].timestamp - timedelta(days=1)
        self.assertEqual(acc.get_holdings_at(earliest), [])

    def test_holdings_at_after_all_txns(self):
        acc = self._make_account_with_controlled_times()
        latest = acc.get_transactions()[-1].timestamp + timedelta(days=1)
        self.assertEqual(acc.get_holdings_at(latest), acc.get_holdings())

    def test_pl_at_past_time(self):
        acc = self._make_account_with_controlled_times()
        txs = acc.get_transactions()
        past = txs[1].timestamp
        pl = acc.get_profit_or_loss_at(past)
        # At that point: balance 250, holdings 5*150=750, initial 1000 -> 0
        self.assertAlmostEqual(pl, 0.0)

    def test_transactions_in_range(self):
        acc = Account("A1", "Alice")
        acc.deposit(100)
        acc.deposit(200)
        acc.deposit(300)
        txs = acc.get_transactions()
        middle = txs[1]
        result = acc.get_transactions_in_range(middle.timestamp, middle.timestamp)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, middle.id)
        all_result = acc.get_transactions_in_range(None, None)
        self.assertEqual(len(all_result), 3)


class TestTransactionsList(unittest.TestCase):
    def test_empty_transactions(self):
        acc = Account("A1", "Alice")
        self.assertEqual(acc.get_transactions(), [])

    def test_transaction_ordering(self):
        acc = Account("A1", "Alice")
        acc.deposit(100)
        acc.withdraw(50)
        acc.deposit(25)
        txs = acc.get_transactions()
        stamps = [t.timestamp for t in txs]
        self.assertEqual(stamps, sorted(stamps))

    def test_transaction_ids_unique(self):
        acc = Account("A1", "Alice")
        acc.deposit(100)
        acc.deposit(200)
        acc.buy_shares("AAPL", 1)
        ids = [t.id for t in acc.get_transactions()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_transaction_balance_after(self):
        acc = Account("A1", "Alice")
        acc.deposit(1000)    # 1000
        acc.withdraw(200)    # 800
        acc.buy_shares("AAPL", 2)  # 800-300=500
        acc.sell_shares("AAPL", 1) # 500+150=650
        expected = [1000.0, 800.0, 500.0, 650.0]
        for tx, exp in zip(acc.get_transactions(), expected):
            self.assertAlmostEqual(tx.balance_after, exp)


if __name__ == "__main__":
    unittest.main()
