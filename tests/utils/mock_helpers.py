"""
Mock 輔助函數
"""
from unittest.mock import Mock, MagicMock
from datetime import datetime

def create_mock_result(is_success=True, data=None, message=None):
    """創建標準的 Result mock 物件"""
    result = Mock()
    result.is_success = is_success
    result.data = data
    result.message = message
    return result

def create_mock_sdk():
    """創建 FubonSDK mock 物件"""
    sdk = Mock()
    
    # 設置基本結構
    sdk.stock = Mock()
    sdk.accounting = Mock()
    sdk.marketdata = Mock()
    sdk.marketdata.rest_client = Mock()
    sdk.marketdata.rest_client.stock = Mock()
    sdk.marketdata.rest_client.stock.intraday = Mock()
    
    # 設置常用方法
    sdk.login = Mock()
    sdk.logout = Mock()
    sdk.init_realtime = Mock()
    
    return sdk

def create_mock_account_list():
    """創建 mock 帳戶列表"""
    account = Mock()
    account.account = "test_account"
    account.branch_no = "6460"
    
    accounts_result = Mock()
    accounts_result.data = [account]
    accounts_result.is_success = True
    
    return accounts_result, account

def create_mock_datetime(year=2023, month=10, day=12, hour=14, minute=5, second=12, microsecond=85000):
    """創建標準的測試時間"""
    return datetime(year, month, day, hour, minute, second, microsecond)

class MockBuilder:
    """Mock 物件建構器"""
    
    @staticmethod
    def order_result(**kwargs):
        """建構 OrderResult mock"""
        defaults = {
            'function_type': 0,
            'date': '2023/10/12',
            'seq_no': '00000000007',
            'branch_no': '6460',
            'account': '26',
            'order_no': 'bA676',
            'asset_type': 0,
            'market': 'TAIEX',
            'market_type': 'Common',
            'stock_no': '2881',
            'buy_sell': 'Buy',
            'price_type': 'Limit',
            'price': 66.0,
            'quantity': 1000,
            'time_in_force': 'ROD',
            'order_type': 'Stock',
            'is_pre_order': False,
            'status': 10,
            'after_price_type': 'Limit',
            'after_price': 66.0,
            'unit': 1000,
            'after_qty': 1000,
            'filled_qty': 0,
            'filled_money': 0,
            'before_qty': 0,
            'before_price': 0.0,
            'user_def': 'From_Py',
            'last_time': '14:05:12.085',
            'details': None,
            'error_message': None
        }
        defaults.update(kwargs)
        
        mock_order = Mock()
        for key, value in defaults.items():
            setattr(mock_order, key, value)
        
        return mock_order
    
    @staticmethod 
    def bank_remain(**kwargs):
        """建構 BankRemain mock"""
        defaults = {
            'branch_no': '6460',
            'account': '26',
            'currency': 'TWD',
            'balance': 666666,
            'available_balance': 123456
        }
        defaults.update(kwargs)
        
        mock_balance = Mock()
        for key, value in defaults.items():
            setattr(mock_balance, key, value)
            
        return mock_balance
    
    @staticmethod
    def unrealized_data(**kwargs):
        """建構 UnrealizedData mock"""
        defaults = {
            'date': '2021/08/09',
            'account': '26',
            'branch_no': '6460', 
            'stock_no': '2303',
            'buy_sell': 'Buy',
            'order_type': 'Margin',
            'cost_price': 50.0,
            'tradable_qty': 1000,
            'today_qty': 1000,
            'unrealized_profit': 48650,
            'unrealized_loss': 0
        }
        defaults.update(kwargs)
        
        mock_data = Mock()
        for key, value in defaults.items():
            setattr(mock_data, key, value)
            
        return mock_data