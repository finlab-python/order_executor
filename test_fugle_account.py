import os
import time
import unittest
from decimal import Decimal
from finlab.online.enums import OrderCondition, OrderStatus, Action
from finlab.online.order_executor import OrderExecutor, Position
from fugle_account import FugleAccount

class TestFugleAccount(unittest.TestCase):
    """測試 FugleAccount 類別的功能"""

    def setUp(self):
        """每個測試開始前執行的設定"""
        self.fugle_account = FugleAccount()

    def tearDown(self):
        """每個測試結束後執行的清理"""
        oe = OrderExecutor(Position({}), self.fugle_account)
        oe.cancel_orders()

    def test_get_total_balance(self):
        """測試獲取總資產餘額"""
        total_balance = self.fugle_account.get_total_balance()
        self.assertGreaterEqual(total_balance, 0)

    def test_fugle_order(self):
        """測試富果帳戶正常下單"""
        self._test_account(odd_lot=False)

    def test_fugle_order_odd_lot(self):
        """測試富果帳戶零股下單"""
        self._test_account(odd_lot=True)

    def test_fugle_update_price(self):
        """測試富果帳戶更新價格"""
        self._test_update_price(odd_lot=False)

    def test_fugle_update_price_odd_lot(self):
        """測試富果帳戶零股更新價格"""
        self._test_update_price(odd_lot=True)

    def _test_account(self, odd_lot=False):
        """測試帳戶下單和取消訂單功能"""
        # 選擇測試用股票代碼
        sid1 = '3661'
        sid2 = '1101'

        # 設定張數或零股數量
        if odd_lot:
            q_sid1 = 2.1
            q_sid2 = 1.1
        else:
            q_sid1 = 2
            q_sid2 = 1

        # 測試買單
        time.sleep(11)  # 避免過於頻繁下單
        oe = OrderExecutor(Position({sid1: q_sid1, sid2: q_sid2}), account=self.fugle_account)
        self._check_order_executor(oe)

        # 測試混合買賣單，包括當沖放空
        if odd_lot:
            q_sid1 = 2.1
            q_sid2 = -1.1
        else:
            q_sid1 = 2
            q_sid2 = -1

        time.sleep(11)
        oe = OrderExecutor(
            Position({sid1: q_sid1, sid2: q_sid2}, day_trading_short=True), 
            account=self.fugle_account
        )
        self._check_order_executor(oe)

        # 測試市價單
        time.sleep(11)
        oe = OrderExecutor(
            Position({sid1: q_sid1, sid2: q_sid2}, day_trading_short=True), 
            account=self.fugle_account
        )
        self._check_order_executor(oe, market_order=True)

    def _test_update_price(self, odd_lot=False):
        """測試更新訂單價格功能"""
        sid1 = '6016'
        if odd_lot:
            q_sid1 = 0.1
        else:
            q_sid1 = 2
            
        oe = OrderExecutor(Position({sid1: q_sid1}), account=self.fugle_account)
        view_orders = oe.create_orders(view_only=True)
        time.sleep(11)
        oe.create_orders()
        orders = oe.account.get_orders()

        # 獲取第一批訂單ID
        oids = []
        for oid, o in orders.items():
            if o.status == OrderStatus.NEW:
                oids.append(oid)

        time.sleep(11)
        oe.update_order_price(extra_bid_pct=0.05)
        time.sleep(1)

        # 檢查訂單更新後狀態
        orders_new = oe.account.get_orders()
        
        # 檢查第二批訂單狀態
        stock_orders = {o['stock_id']: o for o in view_orders}
        stock_quantity = {o.stock_id: 0 for oid, o in orders_new.items()}
        for oid, o in orders_new.items():
            if o.status == OrderStatus.CANCEL\
                or o.stock_id not in stock_orders\
                or o.stock_id != sid1\
                or o.status == OrderStatus.FILLED:
                continue

            stock_quantity[sid1] += o.quantity
            self.assertEqual(o.order_condition,
                            stock_orders[sid1]['order_condition'])
        
        for sid, q in stock_quantity.items():
            if q != 0:
                self.assertEqual(float(round(q, 4)), abs(
                    stock_orders[sid]['quantity']))

        oe.cancel_orders()

    def _check_order_executor(self, oe, **args_for_creating_orders):
        """檢查訂單執行器的功能"""
        # 查看訂單執行器結果
        view_orders = oe.create_orders(view_only=True)

        oe.cancel_orders()
        time.sleep(11)
        oe.create_orders(**args_for_creating_orders)
        time.sleep(5)
        orders = oe.account.get_orders()

        stock_orders = {o['stock_id']: o for o in view_orders}
        stock_quantity = {o.stock_id: 0 for oid, o in orders.items()}

        for oid, o in orders.items():
            if o.status == OrderStatus.CANCEL\
                or o.stock_id not in stock_orders\
                or o.status == OrderStatus.FILLED:
                continue

            # 獲取股票ID
            sid = o.stock_id

            # 檢查訂單條件和操作
            expect_action = Action.BUY if stock_orders[sid]['quantity'] > 0 else Action.SELL

            stock_quantity[sid] += o.quantity
            self.assertEqual(o.action, expect_action)
            self.assertEqual(o.order_condition,
                             stock_orders[sid]['order_condition'])

        for sid, q in stock_quantity.items():
            if q != 0:
                self.assertEqual(float(round(q, 4)), float(
                    abs(stock_orders[sid]['quantity'])))

        oe.cancel_orders()

if __name__ == "__main__":
    unittest.main()
