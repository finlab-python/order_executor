"""
富邦測試用數據
"""
from datetime import datetime
from finlab.online.enums import Action, OrderCondition, OrderStatus

class FubonTestData:
    """富邦測試數據類"""
    
    # 測試用價格
    PRICES = {
        '2330': {'current': 582.0, 'high': 585.0, 'low': 578.0, 'open': 580.0},
        '2881': {'current': 66.0, 'high': 67.0, 'low': 65.5, 'open': 66.5},
        '0050': {'current': 135.0, 'high': 136.0, 'low': 134.0, 'open': 135.5},
        '0056': {'current': 32.5, 'high': 33.0, 'low': 32.0, 'open': 32.8},
        '00878': {'current': 20.5, 'high': 21.0, 'low': 20.2, 'open': 20.8},
        '9999': {'current': 10.0, 'high': 10.5, 'low': 9.5, 'open': 10.0}
    }
    
    # 測試用數量（張）
    QUANTITIES = {
        'SMALL': 1,
        'MEDIUM': 10,
        'LARGE': 100,
        'ODD_LOT_SMALL': 100,   # 零股 100 股
        'ODD_LOT_MEDIUM': 500,  # 零股 500 股
        'ODD_LOT_LARGE': 999    # 零股 999 股
    }
    
    # 測試用帳戶資訊
    ACCOUNT_INFO = {
        'account': '26',
        'branch_no': '6460',
        'national_id': 'A123456789',
        'available_balance': 123456,
        'total_balance': 666666
    }
    
    # 測試用委託單 ID
    ORDER_IDS = [
        '00000000007',
        '00000000008', 
        '00000000009',
        'bA676',
        'bA677',
        'test_order_001'
    ]
    
    # 測試用時間
    TEST_DATES = {
        'TRADE_DATE': '2023/10/12',
        'SETTLEMENT_DATE': '2023/10/15',
        'ORDER_TIME': '14:05:12.085',
        'MARKET_CLOSE': '13:30:00.000'
    }
    
    @classmethod
    def get_test_order_data(cls, action=Action.BUY, stock_id='2330', quantity=1, 
                           price=None, order_condition=OrderCondition.CASH):
        """獲取測試用委託單數據"""
        if price is None:
            price = cls.PRICES[stock_id]['current']
            
        return {
            'action': action,
            'stock_id': stock_id,
            'quantity': quantity,
            'price': price,
            'order_condition': order_condition
        }
    
    @classmethod
    def get_test_position_data(cls):
        """獲取測試用持倉數據"""
        return [
            {
                'stock_id': '2330',
                'quantity': 2.0,  # 2張
                'order_condition': OrderCondition.CASH
            },
            {
                'stock_id': '2881', 
                'quantity': 1.0,  # 1張
                'order_condition': OrderCondition.MARGIN_TRADING
            },
            {
                'stock_id': '0056',
                'quantity': -1.0,  # 融券 1張
                'order_condition': OrderCondition.SHORT_SELLING
            }
        ]
    
    @classmethod
    def get_test_stock_quotes(cls):
        """獲取測試用股票報價"""
        return {
            stock_id: {
                'stock_id': stock_id,
                'open': prices['open'],
                'high': prices['high'],
                'low': prices['low'],
                'close': prices['current'],
                'bid_price': prices['current'] - 0.5,
                'ask_price': prices['current'] + 0.5,
                'bid_volume': 100,
                'ask_volume': 150
            }
            for stock_id, prices in cls.PRICES.items()
        }
    
    @classmethod
    def get_error_scenarios(cls):
        """獲取錯誤情境測試數據"""
        return {
            'INVALID_STOCK_ID': {
                'stock_id': 'INVALID',
                'error_message': '無效的股票代碼'
            },
            'INSUFFICIENT_BALANCE': {
                'quantity': 1000,  # 超大數量
                'error_message': '餘額不足'
            },
            'INVALID_PRICE': {
                'price': -1.0,  # 負價格
                'error_message': '無效的價格'
            },
            'MARKET_CLOSED': {
                'time': '15:00:00',  # 收盤後
                'error_message': '市場已關閉'
            }
        }
    
    @classmethod
    def get_edge_cases(cls):
        """獲取邊緣案例測試數據"""
        return {
            'ZERO_QUANTITY': {
                'quantity': 0,
                'expected_error': ValueError
            },
            'NEGATIVE_QUANTITY': {
                'quantity': -1,
                'expected_error': ValueError
            },
            'EMPTY_STOCK_ID': {
                'stock_id': '',
                'expected_error': ValueError
            },
            'NONE_PRICE': {
                'price': None,
                'market_order': True
            },
            'ODD_LOT_DECIMAL': {
                'quantity': 0.1,  # 零股 100 股
                'odd_lot': True
            }
        }

# 常用的測試組合
COMMON_TEST_SCENARIOS = {
    'BUY_STOCK_NORMAL': {
        'action': Action.BUY,
        'stock_id': '2330',
        'quantity': 1,
        'price': 580.0,
        'order_cond': OrderCondition.CASH
    },
    'SELL_STOCK_NORMAL': {
        'action': Action.SELL,
        'stock_id': '2330',
        'quantity': 1,
        'price': 582.0,
        'order_cond': OrderCondition.CASH
    },
    'BUY_ODD_LOT': {
        'action': Action.BUY,
        'stock_id': '0056',
        'quantity': 100,  # 零股
        'price': 32.5,
        'odd_lot': True
    },
    'MARGIN_TRADING': {
        'action': Action.BUY,
        'stock_id': '2881',
        'quantity': 10,
        'price': 66.0,
        'order_cond': OrderCondition.MARGIN_TRADING
    },
    'SHORT_SELLING': {
        'action': Action.SELL,
        'stock_id': '2330',
        'quantity': 5,
        'price': 580.0,
        'order_cond': OrderCondition.SHORT_SELLING
    },
    'MARKET_ORDER': {
        'action': Action.BUY,
        'stock_id': '0050',
        'quantity': 2,
        'market_order': True
    }
}