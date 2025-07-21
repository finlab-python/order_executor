"""
富邦帳戶單元測試

測試 FubonAccount 的核心邏輯，使用 mock 來隔離外部依賴
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from decimal import Decimal

# 導入測試基礎設施
from tests.utils.test_base import MockTestCase, AccountTestMixin
from tests.fixtures.fubon_mocks import FubonSDKMock, FubonAccountMockHelper
from tests.fixtures.fubon_test_data import FubonTestData, COMMON_TEST_SCENARIOS
from tests.utils.mock_helpers import MockBuilder

# 導入被測試的模組
from finlab.online.enums import Action, OrderCondition, OrderStatus
from finlab.online.order_executor import Position
from finlab.online.base_account import Order, Stock
from fubon_neo.constant import BSAction, MarketType, PriceType, OrderType, TimeInForce


class TestFubonAccountUnit(MockTestCase, AccountTestMixin):
    """富邦帳戶單元測試類"""

    def setUp(self):
        super().setUp()
        self.sdk_mock = FubonSDKMock()
        
    def test_init_success(self):
        """測試帳戶初始化成功"""
        with FubonAccountMockHelper.patch_environment():
            with FubonAccountMockHelper.patch_fubon_sdk() as mock_sdk_class:
                mock_sdk_class.return_value = self.sdk_mock.get_sdk()
                
                from fubon_account import FubonAccount
                account = FubonAccount()
                
                # 驗證 SDK 被正確初始化
                mock_sdk_class.assert_called_once()
                self.sdk_mock.sdk.login.assert_called_once()
                self.sdk_mock.sdk.init_realtime.assert_called_once()
                
                # 驗證帳戶屬性
                self.assertIsNotNone(account.sdk)
                self.assertIsNotNone(account.target_account)

    def test_init_missing_credentials(self):
        """測試缺少憑證時初始化失敗"""
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(ValueError) as context:
                from fubon_account import FubonAccount
                FubonAccount()
            
            self.assertIn("缺少必要的登錄信息", str(context.exception))

    def test_init_login_failure(self):
        """測試登入失敗"""
        with FubonAccountMockHelper.patch_environment():
            with FubonAccountMockHelper.patch_fubon_sdk() as mock_sdk_class:
                sdk_mock = self.sdk_mock.get_sdk()
                sdk_mock.login.side_effect = Exception("登入失敗")
                mock_sdk_class.return_value = sdk_mock
                
                with self.assertRaises(Exception) as context:
                    from fubon_account import FubonAccount
                    FubonAccount()
                
                self.assertIn("無法登入富邦證券", str(context.exception))


class TestFubonAccountDataParsing(MockTestCase):
    """測試數據解析相關方法"""

    def setUp(self):
        super().setUp()
        self.account = FubonAccountMockHelper.create_mock_account_with_sdk()

    def test_parse_order_status_all_codes(self):
        """測試所有狀態碼的解析"""
        test_cases = [
            (10, OrderStatus.NEW),     # 委託成功
            (30, OrderStatus.CANCEL),  # 刪單成功
            (50, OrderStatus.FILLED),  # 完全成交
            (90, OrderStatus.CANCEL),  # 失敗
            (999, OrderStatus.NEW)     # 未知狀態碼，默認為 NEW
        ]
        
        for status_code, expected_status in test_cases:
            with self.subTest(status_code=status_code):
                mock_order = Mock()
                mock_order.status = status_code
                mock_order.filled_qty = 0
                mock_order.after_qty = 1000
                
                result = self.account._parse_order_status(mock_order)
                self.assertEqual(result, expected_status)

    def test_parse_order_status_partial_fill_detection(self):
        """測試部分成交的檢測邏輯"""
        mock_order = Mock()
        mock_order.status = 10  # 委託成功
        mock_order.filled_qty = 500  # 已成交 500
        mock_order.after_qty = 1000   # 總委託 1000
        
        result = self.account._parse_order_status(mock_order)
        self.assertEqual(result, OrderStatus.PARTIALLY_FILLED)

    def test_parse_quantities(self):
        """測試數量解析"""
        mock_order = Mock()
        mock_order.after_qty = 2000   # 委託數量（股）
        mock_order.filled_qty = 1000  # 成交數量（股）
        
        quantity, filled_quantity = self.account._parse_quantities(mock_order)
        
        # 應該轉換為張
        self.assertEqual(quantity, 2.0)    # 2000 / 1000 = 2 張
        self.assertEqual(filled_quantity, 1.0)  # 1000 / 1000 = 1 張

    def test_parse_order_time_standard_format(self):
        """測試標準時間格式解析"""
        mock_order = Mock()
        mock_order.date = '2023/10/12'
        mock_order.last_time = '14:05:12.085'
        
        result = self.account._parse_order_time(mock_order)
        
        expected = datetime(2023, 10, 12, 14, 5, 12, 85000)
        self.assertEqual(result, expected)

    def test_parse_order_time_without_microseconds(self):
        """測試無毫秒的時間格式解析"""
        mock_order = Mock()
        mock_order.date = '2023/10/12'
        mock_order.last_time = '14:05:12'
        
        result = self.account._parse_order_time(mock_order)
        
        expected = datetime(2023, 10, 12, 14, 5, 12, 0)
        self.assertEqual(result, expected)

    def test_parse_date_formats(self):
        """測試不同日期格式解析"""
        test_cases = [
            ('2023/10/12', (2023, 10, 12)),
            ('10/12', (datetime.now().year, 10, 12)),
            ('20231012', (2023, 10, 12))
        ]
        
        for date_str, expected in test_cases:
            with self.subTest(date_str=date_str):
                result = self.account._parse_date(date_str)
                self.assertEqual(result, expected)

    def test_parse_time_formats(self):
        """測試不同時間格式解析"""
        test_cases = [
            ('14:05:12.085', (14, 5, 12, 85000)),
            ('14:05:12.0', (14, 5, 12, 0)),
            ('14:05:12', (14, 5, 12, 0)),
            ('09:30:00.000', (9, 30, 0, 0))
        ]
        
        for time_str, expected in test_cases:
            with self.subTest(time_str=time_str):
                result = self.account._parse_time(time_str)
                self.assertEqual(result, expected)

    def test_map_order_action(self):
        """測試買賣別映射"""
        test_cases = [
            (BSAction.Buy, Action.BUY),
            (BSAction.Sell, Action.SELL)
        ]
        
        for bs_action, expected_action in test_cases:
            with self.subTest(bs_action=bs_action):
                mock_order = Mock()
                mock_order.buy_sell = bs_action
                
                result = self.account._map_order_action(mock_order)
                self.assertEqual(result, expected_action)

    def test_map_order_action_string_format(self):
        """測試字串格式的買賣別映射"""
        test_cases = [
            ('B', Action.BUY),
            ('BUY', Action.BUY),
            ('S', Action.SELL),
            ('SELL', Action.SELL)
        ]
        
        for buy_sell_str, expected_action in test_cases:
            with self.subTest(buy_sell_str=buy_sell_str):
                mock_order = Mock()
                mock_order.buy_sell = buy_sell_str
                
                result = self.account._map_order_action(mock_order)
                self.assertEqual(result, expected_action)

    def test_map_order_action_invalid(self):
        """測試無效買賣別的處理"""
        mock_order = Mock()
        mock_order.buy_sell = 'INVALID'
        
        with self.assertRaises(ValueError):
            self.account._map_order_action(mock_order)

    def test_map_order_condition(self):
        """測試委託條件映射"""
        test_cases = [
            (OrderType.Stock, OrderCondition.CASH),
            (OrderType.Margin, OrderCondition.MARGIN_TRADING),
            (OrderType.Short, OrderCondition.SHORT_SELLING),
            (OrderType.DayTrade, OrderCondition.DAY_TRADING_SHORT)
        ]
        
        for order_type, expected_condition in test_cases:
            with self.subTest(order_type=order_type):
                mock_order = Mock()
                mock_order.order_type = order_type
                
                result = self.account._map_order_condition(mock_order)
                self.assertEqual(result, expected_condition)

    def test_map_order_condition_string_format(self):
        """測試字串格式的委託條件映射"""
        test_cases = [
            ('現股', OrderCondition.CASH),
            ('STOCK', OrderCondition.CASH),
            ('融資', OrderCondition.MARGIN_TRADING),
            ('MARGIN', OrderCondition.MARGIN_TRADING),
            ('融券', OrderCondition.SHORT_SELLING),
            ('SHORT', OrderCondition.SHORT_SELLING),
            ('當沖', OrderCondition.DAY_TRADING_SHORT),
            ('DAYTRADE', OrderCondition.DAY_TRADING_SHORT)
        ]
        
        for order_type_str, expected_condition in test_cases:
            with self.subTest(order_type_str=order_type_str):
                mock_order = Mock()
                mock_order.order_type = order_type_str
                
                result = self.account._map_order_condition(mock_order)
                self.assertEqual(result, expected_condition)


class TestFubonAccountStockDataExtraction(MockTestCase, AccountTestMixin):
    """測試股票數據提取相關方法"""

    def setUp(self):
        super().setUp()
        self.account = FubonAccountMockHelper.create_mock_account_with_sdk()

    def test_extract_price_data_from_dict(self):
        """測試從字典格式提取價格數據"""
        quote_dict = {
            'symbol': '2330',
            'openPrice': 580.0,
            'highPrice': 585.0,
            'lowPrice': 578.0,
            'closePrice': 582.0
        }
        
        stock_id, price_data = self.account._extract_price_data(quote_dict, '2330')
        
        self.assertEqual(stock_id, '2330')
        self.assertEqual(price_data['open'], 580.0)
        self.assertEqual(price_data['high'], 585.0)
        self.assertEqual(price_data['low'], 578.0)
        self.assertEqual(price_data['close'], 582.0)

    def test_extract_price_data_from_object(self):
        """測試從物件格式提取價格數據"""
        quote_obj = Mock()
        quote_obj.symbol = '2881'
        quote_obj.open_price = 66.0
        quote_obj.high_price = 67.0
        quote_obj.low_price = 65.5
        quote_obj.close_price = 66.5
        
        stock_id, price_data = self.account._extract_price_data(quote_obj, '2881')
        
        self.assertEqual(stock_id, '2881')
        self.assertEqual(price_data['open'], 66.0)
        self.assertEqual(price_data['high'], 67.0)
        self.assertEqual(price_data['low'], 65.5)
        self.assertEqual(price_data['close'], 66.5)

    def test_extract_bid_ask_data_from_dict(self):
        """測試從字典格式提取委買委賣數據"""
        quote_dict = {
            'bids': [{'price': 581.0, 'size': 100}],
            'asks': [{'price': 582.0, 'size': 150}]
        }
        
        bid_ask_data = self.account._extract_bid_ask_data(quote_dict)
        
        self.assertEqual(bid_ask_data['bid_price'], 581.0)
        self.assertEqual(bid_ask_data['bid_volume'], 100)
        self.assertEqual(bid_ask_data['ask_price'], 582.0)
        self.assertEqual(bid_ask_data['ask_volume'], 150)

    def test_extract_bid_ask_data_empty(self):
        """測試空的委買委賣數據處理"""
        quote_dict = {
            'bids': [],
            'asks': []
        }
        
        bid_ask_data = self.account._extract_bid_ask_data(quote_dict)
        
        self.assertEqual(bid_ask_data['bid_price'], 0)
        self.assertEqual(bid_ask_data['bid_volume'], 0)
        self.assertEqual(bid_ask_data['ask_price'], 0)
        self.assertEqual(bid_ask_data['ask_volume'], 0)

    def test_create_finlab_stock_success(self):
        """測試成功創建 finlab Stock 物件"""
        quote = {
            'symbol': '2330',
            'openPrice': 580.0,
            'highPrice': 585.0,
            'lowPrice': 578.0,
            'closePrice': 582.0,
            'bids': [{'price': 581.0, 'size': 100}],
            'asks': [{'price': 582.0, 'size': 150}]
        }
        
        stock = self.account._create_finlab_stock(quote, '2330')
        
        self.assert_stock_structure(stock)
        self.assertEqual(stock.stock_id, '2330')
        self.assertEqual(stock.open, 580.0)
        self.assertEqual(stock.high, 585.0)
        self.assertEqual(stock.low, 578.0)
        self.assertEqual(stock.close, 582.0)
        self.assertEqual(stock.bid_price, 581.0)
        self.assertEqual(stock.ask_price, 582.0)

    def test_create_finlab_stock_error_handling(self):
        """測試創建 Stock 物件時的錯誤處理"""
        # 模擬無效的 quote 數據
        invalid_quote = "invalid_data"
        
        stock = self.account._create_finlab_stock(invalid_quote, '2330')
        
        # 應該返回空的 Stock 物件
        self.assert_stock_structure(stock)
        self.assertEqual(stock.stock_id, '2330')
        self.assertEqual(stock.open, 0)
        self.assertEqual(stock.close, 0)


class TestFubonAccountErrorHandling(MockTestCase):
    """測試錯誤處理"""

    def setUp(self):
        super().setUp()
        self.account = FubonAccountMockHelper.create_mock_account_with_sdk()

    def test_handle_exceptions_decorator(self):
        """測試 handle_exceptions 裝飾器"""
        from fubon_account import handle_exceptions
        
        @handle_exceptions(default_return="default_value", log_prefix="test: ")
        def test_function():
            raise Exception("測試異常")
        
        # 應該返回默認值而不是拋出異常
        result = test_function()
        self.assertEqual(result, "default_value")

    def test_get_cash_exception_handling(self):
        """測試 get_cash 方法的異常處理"""
        # 設置 SDK 拋出異常
        self.account.sdk.accounting.bank_remain.side_effect = Exception("API 錯誤")
        
        # 應該返回 0 而不是拋出異常
        cash = self.account.get_cash()
        self.assertEqual(cash, 0)

    def test_get_orders_exception_handling(self):
        """測試 get_orders 方法的異常處理"""
        # 設置 SDK 拋出異常
        self.account.sdk.stock.get_order_results.side_effect = Exception("API 錯誤")
        
        # 應該返回空字典而不是拋出異常
        orders = self.account.get_orders()
        self.assertEqual(orders, {})


class TestFubonAccountCreateFinlabOrder(MockTestCase, AccountTestMixin):
    """測試創建 finlab Order 物件"""

    def setUp(self):
        super().setUp()
        self.account = FubonAccountMockHelper.create_mock_account_with_sdk()

    def test_create_finlab_order_complete(self):
        """測試創建完整的 finlab Order 物件"""
        mock_order = MockBuilder.order_result(
            seq_no='00000000007',
            stock_no='2330',
            buy_sell=BSAction.Buy,
            price=580.0,
            after_qty=2000,
            filled_qty=1000,
            status=40,  # 部分成交
            order_type=OrderType.Stock,
            date='2023/10/12',
            last_time='14:05:12.085'
        )
        
        order = self.account._create_finlab_order(mock_order)
        
        # 驗證 Order 結構
        self.assert_order_structure(order)
        
        # 驗證具體值
        self.assertEqual(order.order_id, '00000000007')
        self.assertEqual(order.stock_id, '2330')
        self.assertEqual(order.action, Action.BUY)
        self.assertEqual(order.price, 580.0)
        self.assertEqual(order.quantity, 2.0)  # 2000 / 1000 = 2 張
        self.assertEqual(order.filled_quantity, 1.0)  # 1000 / 1000 = 1 張
        self.assertEqual(order.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(order.order_condition, OrderCondition.CASH)
        
        # 驗證時間
        expected_time = datetime(2023, 10, 12, 14, 5, 12, 85000)
        self.assertEqual(order.time, expected_time)


if __name__ == '__main__':
    unittest.main()