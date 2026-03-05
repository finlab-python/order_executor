"""Integration tests for real broker account order execution flows."""

import unittest

from finlab import data
from finlab.online.order_executor import OrderExecutor, Position

from .real_order_helpers import (
    run_account_order_flow,
    run_account_update_price_flow,
)

try:
    from finlab.online.sinopac_account import SinopacAccount
except ImportError:
    SinopacAccount = None

try:
    from finlab.online.fugle_account import FugleAccount
except ImportError:
    FugleAccount = None


class TestSinopacRealOrder(unittest.TestCase):
    def setUp(self):
        if SinopacAccount is None:
            self.skipTest("SinopacAccount dependency is unavailable")
        self.sinopac_account = SinopacAccount()

    def test_get_total_balance(self):
        total_balance = self.sinopac_account.get_total_balance()
        assert total_balance >= 0

    def test_order(self):
        run_account_order_flow(self, self.sinopac_account, odd_lot=False)

    def test_order_odd_lot(self):
        run_account_order_flow(self, self.sinopac_account, odd_lot=True)

    def test_update_price(self):
        run_account_update_price_flow(self, self.sinopac_account, odd_lot=False)

    def test_update_price_odd_lot(self):
        run_account_update_price_flow(self, self.sinopac_account, odd_lot=True)

    def test_show_alerting_stocks(self):
        self.sinopac_account.get_total_balance()
        df = data.get("reference_price")
        stocks = df.stock_id[df.stock_id.str.len() == 4].to_list()
        oe = OrderExecutor(Position(dict(zip(stocks, len(stocks) * [1]))), self.sinopac_account)
        oe.show_alerting_stocks()

    def tearDown(self):
        oe = OrderExecutor(Position({}), self.sinopac_account)
        oe.cancel_orders()


class TestFugleRealOrder(unittest.TestCase):
    def setUp(self):
        if FugleAccount is None:
            self.skipTest("FugleAccount dependency is unavailable")
        self.fugle_account = FugleAccount()

    def test_order(self):
        run_account_order_flow(self, self.fugle_account, odd_lot=False)

    def test_order_odd_lot(self):
        run_account_order_flow(self, self.fugle_account, odd_lot=True)

    def test_update_price(self):
        run_account_update_price_flow(self, self.fugle_account, odd_lot=False)

    def test_update_price_odd_lot(self):
        run_account_update_price_flow(self, self.fugle_account, odd_lot=True)

    def tearDown(self):
        oe = OrderExecutor(Position({}), self.fugle_account)
        oe.cancel_orders()
