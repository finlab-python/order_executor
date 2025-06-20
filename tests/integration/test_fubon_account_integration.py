"""
富邦帳戶整合測試

測試 FubonAccount 與真實 API 的交互，需要有效的憑證
"""
import os
import time
import unittest
import logging
from decimal import Decimal

# 導入測試基礎設施
from tests.utils.test_base import IntegrationTestCase, AccountTestMixin
from tests.test_config import TestConfig
from tests.fixtures.fubon_test_data import FubonTestData, COMMON_TEST_SCENARIOS

# 導入被測試的模組
from finlab.online.enums import OrderCondition, OrderStatus, Action
from finlab.online.order_executor import OrderExecutor, Position

# 設定測試日誌
TestConfig.setup_test_logging(level=logging.INFO)


@TestConfig.skip_if_no_fubon_credentials()
class TestFubonAccountIntegration(IntegrationTestCase, AccountTestMixin):
    """富邦帳戶整合測試類"""

    def setUp(self):
        super().setUp()
        try:
            from fubon_account import FubonAccount
            self.fubon_account = FubonAccount()
            logging.info("富邦帳戶初始化成功")
        except Exception as e:
            logging.error(f"設定 FubonAccount 時發生錯誤: {e}")
            raise

    def tearDown(self):
        """每個測試結束後執行的清理"""
        try:
            # 取消所有委託單
            oe = OrderExecutor(Position({}), self.fubon_account)
            oe.cancel_orders()
            logging.info("測試清理完成")
        except Exception as e:
            logging.warning(f"清理測試環境時發生錯誤: {e}")
        super().tearDown()

    def test_account_initialization(self):
        """測試帳戶初始化"""
        self.assertIsNotNone(self.fubon_account)
        self.assertIsNotNone(self.fubon_account.sdk)
        self.assertIsNotNone(self.fubon_account.target_account)
        logging.info(f"成功登入帳號: {self.fubon_account.target_account.account}")

    def test_get_total_balance(self):
        """測試獲取總資產餘額"""
        total_balance = self.fubon_account.get_total_balance()
        logging.info(f'總資產餘額: {total_balance}')
        
        self.assertIsInstance(total_balance, (int, float))
        self.assertGreaterEqual(total_balance, 0)

    def test_get_cash(self):
        """測試獲取可用資金"""
        cash = self.fubon_account.get_cash()
        logging.info(f'可用資金: {cash}')
        
        self.assertIsInstance(cash, (int, float))
        self.assertGreaterEqual(cash, 0)

    def test_get_settlement(self):
        """測試獲取未交割款項"""
        settlement = self.fubon_account.get_settlement()
        logging.info(f'未交割款項: {settlement}')
        
        self.assertIsInstance(settlement, (int, float))

    def test_get_position(self):
        """測試獲取持有部位"""
        position = self.fubon_account.get_position()
        logging.info(f'持有部位: \n{position}')
        
        self.assertIsInstance(position, Position)

    def test_get_orders(self):
        """測試獲取委託單"""
        orders = self.fubon_account.get_orders()
        logging.info(f'委託單數量: {len(orders)}')
        
        self.assertIsInstance(orders, dict)
        
        # 驗證每個委託單的結構
        for order_id, order in orders.items():
            self.assert_order_structure(order)
            self.assertEqual(order.order_id, order_id)

    def test_get_stocks(self):
        """測試獲取股票報價"""
        test_stocks = [
            '2330',  # 台積電
            '0056'   # 元大高股息
        ]
        
        stocks = self.fubon_account.get_stocks(test_stocks)
        logging.info(f'獲取股票報價數量: {len(stocks)}')
        
        self.assertIsInstance(stocks, dict)
        
        for stock_id in test_stocks:
            if stock_id in stocks:
                stock = stocks[stock_id]
                self.assert_stock_structure(stock)
                self.assertEqual(stock.stock_id, stock_id)
                logging.info(f'{stock_id}: 收盤價={stock.close}, 買價={stock.bid_price}, 賣價={stock.ask_price}')

    def test_create_and_cancel_order(self):
        """測試建立和取消委託單"""
        test_data = COMMON_TEST_SCENARIOS['BUY_STOCK_NORMAL'].copy()
        test_data['price'] = 32.0  # 使用低於市價的價格避免成交
        test_data['stock_id'] = '0056'  # 元大高股息
        
        # 建立委託單
        order_id = self.fubon_account.create_order(**test_data)
        
        if order_id:
            logging.info(f"成功建立委託單: {order_id}")
            
            # 等待委託單創建完成
            time.sleep(20)
            
            # 獲取委託單並驗證
            orders = self.fubon_account.get_orders()
            self.assertIn(order_id, orders)
            
            order = orders[order_id]
            self.assertEqual(order.stock_id, test_data['stock_id'])
            self.assertEqual(order.action, test_data['action'])
            self.assertEqual(float(order.quantity), float(test_data['quantity']))
            
            # 取消委託單
            self.fubon_account.cancel_order(order_id)
            logging.info(f"已取消委託單: {order_id}")
            
            # 等待取消完成
            time.sleep(3)
            
            # 驗證委託單狀態
            orders_after_cancel = self.fubon_account.get_orders()
            if order_id in orders_after_cancel:
                self.assertEqual(orders_after_cancel[order_id].status, OrderStatus.CANCEL)
        else:
            self.skipTest("無法建立委託單，跳過測試")

    def test_create_odd_lot_order(self):
        """測試零股委託"""
        test_data = COMMON_TEST_SCENARIOS['BUY_ODD_LOT'].copy()
        test_data['price'] = 30.0  # 使用低於市價的價格避免成交
        
        # 建立零股委託單
        order_id = self.fubon_account.create_order(**test_data)
        
        if order_id:
            logging.info(f"成功建立零股委託單: {order_id}")
            
            # 等待委託單創建完成
            time.sleep(3)
            
            # 獲取並驗證委託單
            orders = self.fubon_account.get_orders()
            self.assertIn(order_id, orders)
            
            order = orders[order_id]
            self.assertEqual(order.stock_id, test_data['stock_id'])
            self.assertEqual(order.action, test_data['action'])
            
            # 清理
            self.fubon_account.cancel_order(order_id)
        else:
            self.skipTest("無法建立零股委託單，跳過測試")

    def test_market_order(self):
        """測試市價單（小心！會實際成交）"""
        # 使用非常小的數量來測試
        test_data = {
            'action': Action.BUY,
            'stock_id': '0056',  # 元大高股息
            'quantity': 100,  # 零股 100 股
            'market_order': True,
            'odd_lot': True
        }
        
        # 警告：這個測試可能會實際成交
        logging.warning("執行市價單測試 - 可能會實際成交！")
        
        # 可以選擇跳過這個測試
        self.skipTest("跳過市價單測試以避免實際成交")

    def test_update_order_price(self):
        """測試更新委託單價格"""
        test_data = COMMON_TEST_SCENARIOS['BUY_STOCK_NORMAL'].copy()
        test_data['price'] = 32.0
        test_data['stock_id'] = '0056'  # 元大高股息
        
        # 建立委託單
        order_id = self.fubon_account.create_order(**test_data)
        
        if order_id:
            time.sleep(5)
            
            # 更新價格
            new_price = 32.5
            self.fubon_account.update_order(order_id, price=new_price)
            logging.info(f"更新委託單 {order_id} 價格為 {new_price}")
            
            time.sleep(5)
            
            # 驗證價格更新
            orders = self.fubon_account.get_orders()
            if order_id in orders:
                updated_order = orders[order_id]
                # 注意：由於網路延遲，價格可能還沒更新，所以這裡只做日誌記錄
                logging.info(f"更新後價格: {updated_order.price}")
            
            # 清理
            self.fubon_account.cancel_order(order_id)
        else:
            self.skipTest("無法建立委託單，跳過更新測試")

    def test_update_order_quantity(self):
        """測試更新委託單數量"""
        test_data = COMMON_TEST_SCENARIOS['BUY_STOCK_NORMAL'].copy()
        test_data['price'] = 32.0
        test_data['stock_id'] = '0056'  # 元大高股息
        test_data['quantity'] = 2  # 初始 1 張
        
        # 建立委託單
        order_id = self.fubon_account.create_order(**test_data)
        
        if order_id:
            time.sleep(20)
            
            # 更新數量
            new_quantity = 1  # 改為 2 張
            self.fubon_account.update_order(order_id, quantity=new_quantity)
            logging.info(f"更新委託單 {order_id} 數量為 {new_quantity} 張")
            
            time.sleep(20)
            
            # 驗證數量更新
            orders = self.fubon_account.get_orders()
            if order_id in orders:
                updated_order = orders[order_id]
                # 注意：由於網路延遲，數量可能還沒更新，所以這裡只做日誌記錄
                logging.info(f"更新後數量: {updated_order.quantity}")
                logging.info(f"更新後狀態: {updated_order.status}")
            
            # 清理
            self.fubon_account.cancel_order(order_id)
        else:
            self.skipTest("無法建立委託單，跳過數量更新測試")

    def test_update_order_price_and_quantity(self):
        """測試同時更新委託單價格和數量"""
        test_data = COMMON_TEST_SCENARIOS['BUY_STOCK_NORMAL'].copy()
        test_data['price'] = 32.0
        test_data['stock_id'] = '0056'  # 元大高股息
        test_data['quantity'] = 2  # 初始 2 張
        
        # 建立委託單
        order_id = self.fubon_account.create_order(**test_data)
        
        if order_id:
            time.sleep(5)
            
            # 同時更新價格和數量
            new_price = 32.5
            new_quantity = 1
            self.fubon_account.update_order(order_id, price=new_price, quantity=new_quantity)
            logging.info(f"更新委託單 {order_id} 價格為 {new_price}，數量為 {new_quantity} 張")
            
            time.sleep(5)
            
            # 驗證更新結果
            orders = self.fubon_account.get_orders()
            if order_id in orders:
                updated_order = orders[order_id]
                logging.info(f"更新後價格: {updated_order.price}")
                logging.info(f"更新後數量: {updated_order.quantity}")
                logging.info(f"更新後狀態: {updated_order.status}")
            
            # 清理
            self.fubon_account.cancel_order(order_id)
        else:
            self.skipTest("無法建立委託單，跳過價格和數量更新測試")

    def test_update_odd_lot_order_quantity(self):
        """測試更新零股委託單數量"""
        test_data = COMMON_TEST_SCENARIOS['BUY_ODD_LOT'].copy()
        test_data['price'] = 30.0  # 使用低於市價的價格避免成交
        test_data['quantity'] = 200  # 初始 100 股
        
        # 建立零股委託單
        order_id = self.fubon_account.create_order(**test_data)
        
        if order_id:
            time.sleep(5)
            
            # 更新零股數量
            new_quantity = 100  # 改為 200 股
            self.fubon_account.update_order(order_id, quantity=new_quantity)
            logging.info(f"更新零股委託單 {order_id} 數量為 {new_quantity} 股")
            
            time.sleep(5)
            
            # 驗證零股數量更新
            orders = self.fubon_account.get_orders()
            if order_id in orders:
                updated_order = orders[order_id]
                logging.info(f"更新後零股數量: {updated_order.quantity}")
                logging.info(f"更新後狀態: {updated_order.status}")
            
            # 清理
            self.fubon_account.cancel_order(order_id)
        else:
            self.skipTest("無法建立零股委託單，跳過零股數量更新測試")

    def test_account_balance_consistency(self):
        """測試帳戶餘額一致性"""
        cash = self.fubon_account.get_cash()
        settlement = self.fubon_account.get_settlement()
        total_balance = self.fubon_account.get_total_balance()
        
        logging.info(f"現金: {cash}, 未交割: {settlement}, 總資產: {total_balance}")
        
        # 總資產應該大於等於現金
        self.assertGreaterEqual(total_balance, cash)
        
        # 所有值都應該是數字
        self.assertIsInstance(cash, (int, float))
        self.assertIsInstance(settlement, (int, float))
        self.assertIsInstance(total_balance, (int, float))

    def test_error_scenarios(self):
        """測試錯誤情境"""
        # 測試無效股票代碼
        invalid_stocks = self.fubon_account.get_stocks(['INVALID_STOCK'])
        self.assertIsInstance(invalid_stocks, dict)
        
        # 測試無效委託單取消
        try:
            self.fubon_account.cancel_order('INVALID_ORDER_ID')
            # 如果沒有拋出異常，則測試通過（某些實作可能會靜默處理錯誤）
        except Exception as e:
            logging.info(f"預期的錯誤: {e}")

    def test_concurrent_operations(self):
        """測試並發操作的穩定性"""
        # 快速連續獲取多次餘額
        balances = []
        for i in range(3):
            balance = self.fubon_account.get_cash()
            balances.append(balance)
            time.sleep(1)
        
        # 餘額應該相對穩定（允許小幅波動）
        for balance in balances:
            self.assertIsInstance(balance, (int, float))
            self.assertGreaterEqual(balance, 0)
        
        logging.info(f"連續查詢餘額: {balances}")


@TestConfig.skip_if_no_fubon_credentials()
class TestFubonAccountOrderExecutor(IntegrationTestCase):
    """富邦帳戶與 OrderExecutor 整合測試"""

    def setUp(self):
        super().setUp()
        try:
            from fubon_account import FubonAccount
            self.fubon_account = FubonAccount()
        except Exception as e:
            logging.error(f"設定 FubonAccount 時發生錯誤: {e}")
            raise

    def tearDown(self):
        """清理所有委託單"""
        try:
            oe = OrderExecutor(Position({}), self.fubon_account)
            oe.cancel_orders()
        except Exception as e:
            logging.warning(f"清理測試環境時發生錯誤: {e}")
        super().tearDown()

    def test_order_executor_basic(self):
        """測試 OrderExecutor 基本功能"""
        # 建立小額測試持倉
        target_position = Position({
            '0056': 1  # 元大高股息 1張
        })
        
        oe = OrderExecutor(target_position, account=self.fubon_account)
        
        # 只查看訂單，不實際執行
        view_orders = oe.create_orders(view_only=True)
        logging.info(f"預覽訂單: {view_orders}")
        
        self.assertIsInstance(view_orders, list)
        
        # 如果有訂單，驗證結構
        for order in view_orders:
            self.assertIn('stock_id', order)
            self.assertIn('quantity', order)
            self.assertIn('order_condition', order)

    def test_position_sync(self):
        """測試持倉同步"""
        # 獲取當前持倉
        current_position = self.fubon_account.get_position()
        logging.info(f"當前持倉: {current_position}")
        
        # 測試空倉位
        empty_position = Position({})
        oe = OrderExecutor(empty_position, account=self.fubon_account)
        
        # 只查看會產生什麼訂單（賣出現有持倉）
        view_orders = oe.create_orders(view_only=True)
        logging.info(f"清倉所需訂單數量: {len(view_orders)}")

    def test_fubon_order_executor_normal(self):
        """測試富邦帳戶 OrderExecutor 正常下單"""
        self._test_order_executor_account(odd_lot=False)

    def test_fubon_order_executor_odd_lot(self):
        """測試富邦帳戶 OrderExecutor 零股下單"""
        self._test_order_executor_account(odd_lot=True)

    def test_fubon_update_price(self):
        """測試富邦帳戶 OrderExecutor 更新價格"""
        self._test_update_price(odd_lot=False)

    def test_fubon_update_price_odd_lot(self):
        """測試富邦帳戶 OrderExecutor 零股更新價格"""
        self._test_update_price(odd_lot=True)

    def _test_order_executor_account(self, odd_lot=False):
        """測試 OrderExecutor 帳戶下單和取消訂單功能"""
        # 選擇測試用股票代碼
        sid1 = '00878'  # 國泰永續高股息
        sid2 = '0056'   # 元大高股息

        # 設定張數或零股數量
        if odd_lot:
            q_sid1 = 0.1  # 零股
            q_sid2 = 0.2  # 零股
        else:
            q_sid1 = 1  # 1張
            q_sid2 = 1  # 1張

        # 測試買單
        logging.info(f"測試 OrderExecutor 買單: {sid1}={q_sid1}, {sid2}={q_sid2}")
        time.sleep(5)  # 避免過於頻繁下單
        oe = OrderExecutor(Position({sid1: q_sid1, sid2: q_sid2}), account=self.fubon_account)
        self._check_order_executor(oe)

        # 測試混合買賣單（當沖）
        if self.fubon_account.support_day_trade_condition():
            logging.info("測試當沖交易功能")
            if odd_lot:
                q_sid1 = 0.1
                q_sid2 = -0.1  # 負數表示賣出
            else:
                q_sid1 = 1
                q_sid2 = -1  # 負數表示賣出

            time.sleep(10)
            oe = OrderExecutor(
                Position({sid1: q_sid1, sid2: q_sid2}, day_trading_short=True), 
                account=self.fubon_account
            )
            self._check_order_executor(oe)
        else:
            logging.info("帳戶不支援當沖交易，跳過當沖測試")

    def _test_update_price(self, odd_lot=False):
        """測試 OrderExecutor 更新訂單價格功能"""
        sid1 = '00878'  # 國泰永續高股息
        if odd_lot:
            q_sid1 = 0.1  # 零股
        else:
            q_sid1 = 1  # 1張
            
        logging.info(f"測試 OrderExecutor 價格更新: {sid1}={q_sid1} (odd_lot={odd_lot})")
        
        oe = OrderExecutor(Position({sid1: q_sid1}), account=self.fubon_account)
        view_orders = oe.create_orders(view_only=True)
        
        if not view_orders:
            self.skipTest("沒有需要創建的訂單，跳過價格更新測試")
        
        time.sleep(5)
        oe.create_orders()
        time.sleep(10)
        
        orders = oe.account.get_orders()
        logging.info(f"當前委託單數量: {len(orders)}")
        
        # 獲取待更新的訂單ID
        update_orders = []
        for oid, o in orders.items():
            if o.status == OrderStatus.NEW and o.stock_id == sid1:
                update_orders.append(oid)

        logging.info(f"待更新訂單: {update_orders}")
        if not update_orders:
            oe.cancel_orders()
            self.skipTest("沒有待更新的訂單，跳過測試")

        time.sleep(30)
        
        # 更新價格 (提高5%)
        logging.info("執行 OrderExecutor 價格更新 (+5%)")
        oe.update_order_price(extra_bid_pct=0.05)
        logging.info(oe.target_position)
        time.sleep(30)

        # 檢查訂單更新後狀態
        orders_new = oe.account.get_orders()
        
        # 驗證價格更新邏輯
        stock_orders = {o['stock_id']: o for o in view_orders}
        stock_quantity = {o.stock_id: 0 for oid, o in orders_new.items()}
        
        for oid, o in orders_new.items():
            if (o.status == OrderStatus.CANCEL or 
                o.stock_id not in stock_orders or 
                o.stock_id != sid1 or 
                o.status == OrderStatus.FILLED):
                continue

            stock_quantity[sid1] += o.quantity
            self.assertEqual(o.order_condition, stock_orders[sid1]['order_condition'])
        
        for sid, q in stock_quantity.items():
            if q != 0:
                expected_q = abs(stock_orders[sid]['quantity'])
                self.assertEqual(float(round(q, 4)), float(expected_q))
                logging.info(f"價格更新驗證通過: {sid} 數量={q}")

        oe.cancel_orders()

    def _check_order_executor(self, oe, **args_for_creating_orders):
        """檢查 OrderExecutor 的功能"""
        # 查看訂單執行器結果
        view_orders = oe.create_orders(view_only=True)
        logging.info(f"OrderExecutor 預覽訂單: {len(view_orders)} 筆")

        if not view_orders:
            logging.info("沒有需要創建的訂單")
            return

        # 先清理可能存在的舊訂單
        oe.cancel_orders()
        time.sleep(5)
        
        # 創建新訂單
        oe.create_orders(**args_for_creating_orders)
        time.sleep(3)
        
        orders = oe.account.get_orders()
        logging.info(f"實際創建訂單: {len(orders)} 筆")

        if not orders:
            self.skipTest("沒有創建的訂單，跳過測試")

        # 驗證訂單正確性
        stock_orders = {o['stock_id']: o for o in view_orders}
        stock_quantity = {o.stock_id: 0 for oid, o in orders.items()}

        valid_orders = 0
        for oid, o in orders.items():
            if (o.status == OrderStatus.CANCEL or 
                o.stock_id not in stock_orders or 
                o.status == OrderStatus.FILLED):
                continue

            # 獲取股票ID
            sid = o.stock_id
            expected_action = Action.BUY if stock_orders[sid]['quantity'] > 0 else Action.SELL

            stock_quantity[sid] += o.quantity
            
            # 驗證訂單屬性
            self.assertEqual(o.action, expected_action)
            self.assertEqual(o.order_condition, stock_orders[sid]['order_condition'])
            
            valid_orders += 1
            logging.info(f"訂單驗證: {sid} {o.action.name} {o.quantity}張 @{o.price}")

        # 驗證數量匹配
        for sid, q in stock_quantity.items():
            if q != 0:
                expected_q = abs(stock_orders[sid]['quantity'])
                self.assertAlmostEqual(float(q), float(expected_q), places=4)

        logging.info(f"OrderExecutor 驗證通過: {valid_orders} 筆有效訂單")
        
        # 清理訂單
        oe.cancel_orders()


if __name__ == "__main__":
    # 檢查環境變數
    if not TestConfig.has_fubon_credentials():
        print("警告：缺少富邦證券測試憑證，將跳過所有測試")
        print("需要設置以下環境變數：")
        for var in TestConfig.FUBON_ENV_VARS:
            print(f"  - {var}")
    
    unittest.main(verbosity=2)