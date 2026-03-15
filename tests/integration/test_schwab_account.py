"""Integration tests for Schwab account."""

from __future__ import annotations

import os
import unittest
from typing import Any

from finlab.online.base_account import Action
from finlab.online.enums import OrderCondition
from finlab.online.order_executor import OrderExecutor, Position

try:
    from schwab_account import SchwabAccount
except ImportError:
    SchwabAccount = None


@unittest.skipIf(SchwabAccount is None, "SchwabAccount dependency is unavailable")
class TestSchwabAccount(unittest.TestCase):
    """Integration tests for SchwabAccount.

    Required environment variables:
        SCHWAB_API_KEY, SCHWAB_SECRET, SCHWAB_TOKEN_PATH
    """

    @classmethod
    def setUpClass(cls) -> None:
        api_key = os.environ["SCHWAB_API_KEY"]
        api_secret = os.environ["SCHWAB_SECRET"]
        token_path = os.environ["SCHWAB_TOKEN_PATH"]

        cls.schwab_account = SchwabAccount(
            api_key=api_key,
            app_secret=api_secret,
            token_path=token_path,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        oe = OrderExecutor(Position({}), cls.schwab_account)
        oe.cancel_orders()

    def test_create_order(self) -> None:
        self.schwab_account.create_order(
            action=Action.BUY,
            stock_id="AAPL",
            quantity=1,
            price=30.0,
            odd_lot=True,
            market_order=False,
            best_price_limit=False,
            order_cond=OrderCondition.CASH,
        )

    def test_get_price_info(self) -> None:
        price_info = self.schwab_account.get_price_info(["AAPL"])
        self.assertIn("AAPL", price_info)
        self.assertIn("收盤價", price_info["AAPL"])
        self.assertIn("漲停價", price_info["AAPL"])
        self.assertIn("跌停價", price_info["AAPL"])

    def test_get_position(self) -> None:
        positions = self.schwab_account.get_position()
        self.assertIsInstance(positions, Position)

    def test_get_orders(self) -> None:
        orders = self.schwab_account.get_orders()
        self.assertIsInstance(orders, dict)

    def test_get_stocks(self) -> None:
        stocks = self.schwab_account.get_stocks(["AAPL"])
        self.assertIn("AAPL", stocks)

    def test_get_total_balance(self) -> None:
        balance = self.schwab_account.get_total_balance()
        self.assertIsInstance(balance, float)

    def test_get_cash(self) -> None:
        cash = self.schwab_account.get_cash()
        self.assertIsInstance(cash, float)
