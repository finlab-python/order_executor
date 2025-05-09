"""
MasterlinkAccount 測試模塊

針對元富證券帳戶 API 進行測試
"""
import os
import time
import unittest
import logging
from decimal import Decimal
from datetime import timezone as tz

# 設定測試環境的日誌級別
logging.basicConfig(level=logging.DEBUG)  # 顯示詳細日誌訊息

from finlab.online.enums import OrderCondition, OrderStatus, Action
from finlab.online.order_executor import OrderExecutor, Position

# 導入待測試的 MasterlinkAccount
from masterlink_account import MasterlinkAccount

class TestMasterlinkAccount(unittest.TestCase):
    """測試 MasterlinkAccount 類"""
    
    def setUp(self):
        """每個測試開始前執行的設定"""
        try:
            self.masterlink_account = MasterlinkAccount()
        except Exception as e:
            print(f"設定 MasterlinkAccount 時發生錯誤: {e}")
            raise
    
    def tearDown(self):
        """每個測試結束後執行的清理"""
        try:
            oe = OrderExecutor(Position({}), self.masterlink_account)
            oe.cancel_orders()
        except Exception as e:
            print(f"清理測試環境時發生錯誤: {e}")
            # 即使清理失敗，我們仍希望其他測試能繼續
    
    def test_account_initialization(self):
        """測試帳戶初始化"""
        # 確認帳戶是否正確初始化
        self.assertIsNotNone(self.masterlink_account)
        # 其他初始化檢查可以根據實際情況添加
    
    def test_get_total_balance(self):
        """測試獲取總資產餘額"""
        total_balance = self.masterlink_account.get_total_balance()
        print(f'總資產餘額: {total_balance}')
        self.assertIsInstance(total_balance, (int, float))
    
    def test_get_cash(self):
        """測試獲取可用資金"""
        cash = self.masterlink_account.get_cash()
        print(f'可用資金: {cash}')
        self.assertIsInstance(cash, (int, float))
    
    def test_get_settlement(self):
        """測試獲取未交割款項"""
        settlement = self.masterlink_account.get_settlement()
        print(f'未交割款項: {settlement}')
        self.assertIsInstance(settlement, (int, float))
    
    def test_get_position(self):
        """測試獲取持有部位"""
        position = self.masterlink_account.get_position()
        print(f'持有部位: \n{position}')
        self.assertIsInstance(position, Position)
    
    def test_get_orders(self):
        """測試獲取委託單"""
        orders = self.masterlink_account.get_orders()
        print(f'委託單: {orders}')
        self.assertIsInstance(orders, dict)
    
    def test_get_stocks(self):
        """測試獲取股票報價"""
        # 選擇一些測試用股票代碼
        test_stocks = ['2330', '2317']
        stocks = self.masterlink_account.get_stocks(test_stocks)
        print(f'股票報價: {stocks}')
        self.assertIsInstance(stocks, dict)
        for stock_id in test_stocks:
            if stock_id in stocks:
                self.assertEqual(stocks[stock_id].stock_id, stock_id)
    
    def test_create_and_cancel_order(self):
        """測試建立和取消委託單"""
        # 選擇一個測試用股票代碼和數量
        stock_id = '2330'
        quantity = 1  # 1張
        
        # 建立委託單
        order_id = self.masterlink_account.create_order(
            action=Action.BUY,
            stock_id=stock_id,
            quantity=quantity,
            price=500.0  # 使用比市價低的價格以避免實際成交
        )
        
        # 如果成功建立委託單，則取消
        if order_id:
            # 等待委託單創建完成
            time.sleep(2)
            
            # 獲取委託單
            orders = self.masterlink_account.get_orders()
            self.assertIn(order_id, orders)
            
            # 檢查委託單詳情
            order = orders[order_id]
            self.assertEqual(order.stock_id, stock_id)
            self.assertEqual(order.action, Action.BUY)
            self.assertEqual(float(order.quantity), float(quantity))
            
            # 取消委託單
            self.masterlink_account.cancel_order(order_id)
            
            # 等待取消完成
            time.sleep(2)
            
            # 再次獲取委託單並檢查狀態
            orders = self.masterlink_account.get_orders()
            if order_id in orders:
                self.assertEqual(orders[order_id].status, OrderStatus.CANCEL)
    
    def test_update_order(self):
        """測試更新委託單"""
        # 選擇一個測試用股票代碼和數量
        stock_id = '2330'
        quantity = 1  # 1張
        original_price = 500.0
        new_price = 510.0
        
        # 建立委託單
        order_id = self.masterlink_account.create_order(
            action=Action.BUY,
            stock_id=stock_id,
            quantity=quantity,
            price=original_price
        )
        
        # 如果成功建立委託單，則更新
        if order_id:
            # 等待委託單創建完成
            time.sleep(3)
            
            # 更新委託單價格
            self.masterlink_account.update_order(order_id, price=new_price)
            
            # 等待更新完成
            time.sleep(3)
            
            # 獲取委託單並檢查價格是否更新
            orders = self.masterlink_account.get_orders()
            if order_id in orders:
                self.assertAlmostEqual(float(orders[order_id].price), new_price, places=2)
            
            # 取消委託單
            self.masterlink_account.cancel_order(order_id)

    def test_update_odd_lot_order(self):
        """測試更新委託單"""
        # 選擇一個測試用股票代碼和數量
        stock_id = '2330'
        quantity = 100
        original_price = 500.0
        new_price = 510.0

        # 建立委託單
        order_id = self.masterlink_account.create_order(
            action=Action.BUY,
            stock_id=stock_id,
            quantity=quantity,
            price=original_price,
            odd_lot=True
        )

        # 如果成功建立委託單，則更新
        if order_id:
            # 等待委託單創建完成
            time.sleep(3)

            # 更新委託單價格
            order_id = self.masterlink_account.update_order(order_id, price=new_price)

            # 等待更新完成
            time.sleep(3)

            # 獲取委託單並檢查價格是否更新
            orders = self.masterlink_account.get_orders()
            if order_id in orders:
                self.assertAlmostEqual(float(orders[order_id].price), new_price, places=2)

            # 取消委託單
            self.masterlink_account.cancel_order(order_id)

    # 以下是新增的集成測試，參考 FugleAccount 測試風格
    def test_masterlink_order(self):
        """測試元富帳戶正常下單"""
        self._test_account(odd_lot=False)

    def test_masterlink_order_odd_lot(self):
        """測試元富帳戶零股下單"""
        self._test_account(odd_lot=True)

    def test_masterlink_update_price(self):
        """測試元富帳戶更新價格"""
        self._test_update_price(odd_lot=False)

    def test_masterlink_update_price_odd_lot(self):
        """測試元富帳戶零股更新價格"""
        self._test_update_price(odd_lot=True)

    def _test_account(self, odd_lot=False):
        """測試帳戶下單和取消訂單功能"""
        # 選擇測試用股票代碼
        sid1 = '2330'
        sid2 = '2317'

        # 設定張數或零股數量
        if odd_lot:
            q_sid1 = 0.1  # 零股
            q_sid2 = 0.2  # 零股
        else:
            q_sid1 = 1  # 1張
            q_sid2 = 1  # 1張

        # 測試買單
        time.sleep(5)  # 避免過於頻繁下單
        oe = OrderExecutor(Position({sid1: q_sid1, sid2: q_sid2}), account=self.masterlink_account)
        self._check_order_executor(oe)

        # 測試混合買賣單
        if self.masterlink_account.support_day_trade_condition():
            if odd_lot:
                q_sid1 = 0.1
                q_sid2 = -0.1  # 負數表示賣出
            else:
                q_sid1 = 1
                q_sid2 = -1  # 負數表示賣出
    
            time.sleep(10)
            oe = OrderExecutor(
                Position({sid1: q_sid1, sid2: q_sid2}, day_trading_short=True), 
                account=self.masterlink_account
            )
            self._check_order_executor(oe)

    def _test_update_price(self, odd_lot=False):
        """測試更新訂單價格功能"""
        sid1 = '2330'
        if odd_lot:
            q_sid1 = 0.1  # 零股
        else:
            q_sid1 = 1  # 1張
            
        oe = OrderExecutor(Position({sid1: q_sid1}), account=self.masterlink_account)
        view_orders = oe.create_orders(view_only=True)
        time.sleep(5)
        oe.create_orders()
        time.sleep(2)
        orders = oe.account.get_orders()

        # 獲取訂單ID
        oids = []
        for oid, o in orders.items():
            if o.status == OrderStatus.NEW:
                oids.append(oid)

        if not oids:
            self.skipTest("沒有待更新的訂單，跳過測試")

        time.sleep(5)
        # 更新價格 (提高5%)
        oe.update_order_price(extra_bid_pct=0.05)
        time.sleep(3)

        # 檢查訂單更新後狀態
        orders_new = oe.account.get_orders()
        
        # 檢查訂單狀態
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
        time.sleep(5)
        oe.create_orders(**args_for_creating_orders)
        time.sleep(3)
        orders = oe.account.get_orders()

        if not orders:
            self.skipTest("沒有創建的訂單，跳過測試")

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
                logging.debug(q)
                logging.debug(stock_orders[sid])
                self.assertEqual(float(round(q, 4)), float(
                    abs(stock_orders[sid]['quantity'])))

        oe.cancel_orders()

if __name__ == "__main__":

    full_suite = unittest.TestLoader().loadTestsFromTestCase(TestMasterlinkAccount)
    unittest.TextTestRunner(verbosity=2).run(full_suite)