"""
富邦 SDK Mock 物件
"""
from unittest.mock import Mock, MagicMock, patch
from tests.fixtures.fubon_sdk_responses import FubonSDKResponses
from tests.utils.mock_helpers import create_mock_result, MockBuilder

class FubonSDKMock:
    """富邦 SDK Mock 類"""
    
    def __init__(self):
        self.sdk = Mock()
        self.setup_sdk_structure()
        self.setup_default_behaviors()
    
    def setup_sdk_structure(self):
        """設置 SDK 基本結構"""
        # 基本方法
        self.sdk.login = Mock()
        self.sdk.logout = Mock()
        self.sdk.init_realtime = Mock()
        
        # Stock API
        self.sdk.stock = Mock()
        self.sdk.stock.place_order = Mock()
        self.sdk.stock.cancel_order = Mock()
        self.sdk.stock.modify_price = Mock()
        self.sdk.stock.modify_quantity = Mock()
        self.sdk.stock.get_order_results = Mock()
        self.sdk.stock.make_modify_price_obj = Mock()
        self.sdk.stock.make_modify_quantity_obj = Mock()
        
        # Accounting API
        self.sdk.accounting = Mock()
        self.sdk.accounting.bank_remain = Mock()
        self.sdk.accounting.unrealized_gains_and_loses = Mock()
        self.sdk.accounting.query_settlement = Mock()
        
        # MarketData API
        self.sdk.marketdata = Mock()
        self.sdk.marketdata.rest_client = Mock()
        self.sdk.marketdata.rest_client.stock = Mock()
        self.sdk.marketdata.rest_client.stock.intraday = Mock()
        self.sdk.marketdata.rest_client.stock.intraday.quote = Mock()
    
    def setup_default_behaviors(self):
        """設置默認行為"""
        # 登入成功
        account_mock = Mock()
        account_mock.account = "26"
        account_mock.branch_no = "6460"
        
        login_result = Mock()
        login_result.data = [account_mock]
        login_result.is_success = True
        
        self.sdk.login.return_value = login_result
        
        # 初始化行情成功
        self.sdk.init_realtime.return_value = None
        
        # 默認 API 回應
        self.setup_stock_api_defaults()
        self.setup_accounting_api_defaults()
        self.setup_marketdata_api_defaults()
    
    def setup_stock_api_defaults(self):
        """設置 Stock API 默認回應"""
        # place_order 成功
        place_order_data = MockBuilder.order_result()
        self.sdk.stock.place_order.return_value = create_mock_result(
            is_success=True,
            data=place_order_data
        )
        
        # get_order_results 成功
        orders_data = [
            MockBuilder.order_result(seq_no='00000000007'),
            MockBuilder.order_result(seq_no='00000000008', stock_no='0056')
        ]
        self.sdk.stock.get_order_results.return_value = create_mock_result(
            is_success=True,
            data=orders_data
        )
        
        # cancel_order 成功
        self.sdk.stock.cancel_order.return_value = create_mock_result(is_success=True)
        
        # modify_price 成功
        self.sdk.stock.modify_price.return_value = create_mock_result(is_success=True)
        
        # modify_quantity 成功
        self.sdk.stock.modify_quantity.return_value = create_mock_result(is_success=True)
        
        # make_modify_*_obj 方法
        self.sdk.stock.make_modify_price_obj.return_value = Mock()
        self.sdk.stock.make_modify_quantity_obj.return_value = Mock()
    
    def setup_accounting_api_defaults(self):
        """設置 Accounting API 默認回應"""
        # bank_remain 成功
        balance_data = MockBuilder.bank_remain()
        self.sdk.accounting.bank_remain.return_value = create_mock_result(
            is_success=True,
            data=balance_data
        )
        
        # unrealized_gains_and_loses 成功
        unrealized_data = [
            MockBuilder.unrealized_data(stock_no='2330', today_qty=2000),
            MockBuilder.unrealized_data(stock_no='2881', today_qty=1000, order_type='Margin')
        ]
        self.sdk.accounting.unrealized_gains_and_loses.return_value = create_mock_result(
            is_success=True,
            data=unrealized_data
        )
        
        # query_settlement 成功
        settlement_data = Mock()
        settlement_data.details = [
            Mock(settlement_date='2023/10/15', total_settlement_amount=66000),
            Mock(settlement_date='2023/10/16', total_settlement_amount=-33000)
        ]
        self.sdk.accounting.query_settlement.return_value = create_mock_result(
            is_success=True,
            data=settlement_data
        )
    
    def setup_marketdata_api_defaults(self):
        """設置 MarketData API 默認回應"""
        # stock quote 成功
        quote_data = {
            'symbol': '2330',
            'openPrice': 580.0,
            'highPrice': 585.0,
            'lowPrice': 578.0,
            'closePrice': 582.0,
            'lastPrice': 582.0,
            'bids': [{'price': 581.0, 'size': 100}],
            'asks': [{'price': 582.0, 'size': 150}]
        }
        self.sdk.marketdata.rest_client.stock.intraday.quote.return_value = quote_data
    
    def get_sdk(self):
        """獲取配置好的 SDK mock"""
        return self.sdk
    
    def set_place_order_failure(self, error_message="下單失敗"):
        """設置下單失敗情境"""
        self.sdk.stock.place_order.return_value = create_mock_result(
            is_success=False,
            message=error_message
        )
    
    def set_bank_remain_failure(self, error_message="查詢餘額失敗"):
        """設置餘額查詢失敗情境"""
        self.sdk.accounting.bank_remain.return_value = create_mock_result(
            is_success=False,
            message=error_message
        )
    
    def set_empty_positions(self):
        """設置空持倉情境"""
        self.sdk.accounting.unrealized_gains_and_loses.return_value = create_mock_result(
            is_success=True,
            data=[]
        )
    
    def set_no_orders(self):
        """設置無委託單情境"""
        self.sdk.stock.get_order_results.return_value = create_mock_result(
            is_success=True,
            data=[]
        )
    
    def set_quote_failure(self):
        """設置報價查詢失敗情境"""
        self.sdk.marketdata.rest_client.stock.intraday.quote.return_value = None
    
    def set_login_failure(self, error_message="登入失敗"):
        """設置登入失敗情境"""
        self.sdk.login.side_effect = Exception(error_message)

class FubonAccountMockHelper:
    """富邦帳戶 Mock 輔助類"""
    
    @staticmethod
    def create_mock_account_with_sdk(sdk_mock=None):
        """創建帶有 mock SDK 的帳戶實例"""
        if sdk_mock is None:
            sdk_mock = FubonSDKMock().get_sdk()
        
        with patch('fubon_account.FubonSDK') as mock_sdk_class:
            mock_sdk_class.return_value = sdk_mock
            
            # Mock 環境變數
            with patch.dict('os.environ', {
                'FUBON_NATIONAL_ID': 'A123456789',
                'FUBON_ACCOUNT_PASS': 'test_password',
                'FUBON_CERT_PATH': '/test/path/cert.pfx'
            }):
                from fubon_account import FubonAccount
                account = FubonAccount()
                account.sdk = sdk_mock  # 確保 SDK 是我們的 mock
                return account
    
    @staticmethod
    def patch_fubon_sdk():
        """返回可用於裝飾器的 FubonSDK patch"""
        return patch('fubon_account.FubonSDK')
    
    @staticmethod
    def patch_environment():
        """返回可用於裝飾器的環境變數 patch"""
        return patch.dict('os.environ', {
            'FUBON_NATIONAL_ID': 'A123456789',
            'FUBON_ACCOUNT_PASS': 'test_password',
            'FUBON_CERT_PATH': '/test/path/cert.pfx',
            'FUBON_CERT_PASS': 'cert_password',
            'FUBON_ACCOUNT': 'test_account'
        })