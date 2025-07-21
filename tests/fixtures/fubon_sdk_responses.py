"""
富邦 SDK 標準回應格式（基於官方文件）
"""
from fubon_neo.constant import BSAction, MarketType, PriceType, OrderType, TimeInForce

class FubonSDKResponses:
    """富邦 SDK 標準回應格式"""
    
    @staticmethod
    def place_order_success():
        """下單成功回應"""
        return {
            'is_success': True,
            'message': None,
            'data': {
                'function_type': 0,
                'date': '2023/10/12',
                'seq_no': '00000000007',
                'branch_no': '6460',
                'account': '26',
                'order_no': 'bA676',
                'asset_type': 0,
                'market': 'TAIEX',
                'market_type': MarketType.Common,
                'stock_no': '2881',
                'buy_sell': BSAction.Buy,
                'price_type': PriceType.Limit,
                'price': 66.0,
                'quantity': 1000,
                'time_in_force': TimeInForce.ROD,
                'order_type': OrderType.Stock,
                'is_pre_order': False,
                'status': 10,  # 委託成功
                'after_price_type': PriceType.Limit,
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
        }
    
    @staticmethod
    def place_order_filled():
        """下單完全成交回應"""
        response = FubonSDKResponses.place_order_success()
        response['data']['status'] = 50  # 完全成交
        response['data']['filled_qty'] = 1000
        response['data']['filled_money'] = 66000
        return response
    
    @staticmethod
    def place_order_partially_filled():
        """下單部分成交回應"""
        response = FubonSDKResponses.place_order_success()
        response['data']['status'] = 40  # 部分成交，剩餘取消
        response['data']['filled_qty'] = 500
        response['data']['filled_money'] = 33000
        response['data']['after_qty'] = 500
        return response
    
    @staticmethod
    def place_order_cancelled():
        """下單取消回應"""
        response = FubonSDKResponses.place_order_success()
        response['data']['status'] = 30  # 未成交刪單成功
        response['data']['function_type'] = 30
        return response
    
    @staticmethod
    def place_order_failed():
        """下單失敗回應"""
        return {
            'is_success': False,
            'message': '委託失敗：餘額不足',
            'data': None
        }
    
    @staticmethod
    def bank_remain_success():
        """銀行餘額查詢成功回應"""
        return {
            'is_success': True,
            'message': None,
            'data': {
                'branch_no': '6460',
                'account': '26',
                'currency': 'TWD',
                'balance': 666666,
                'available_balance': 123456
            }
        }
    
    @staticmethod
    def bank_remain_failed():
        """銀行餘額查詢失敗回應"""
        return {
            'is_success': False,
            'message': '查詢失敗',
            'data': None
        }
    
    @staticmethod
    def unrealized_pnl_success():
        """未實現損益查詢成功回應"""
        return {
            'is_success': True,
            'message': None,
            'data': [
                {
                    'date': '2021/08/09',
                    'account': '26',
                    'branch_no': '6460',
                    'stock_no': '2303',
                    'buy_sell': BSAction.Buy,
                    'order_type': OrderType.Margin,
                    'cost_price': 50.0,
                    'tradable_qty': 1000,
                    'today_qty': 1000,
                    'unrealized_profit': 48650,
                    'unrealized_loss': 0
                },
                {
                    'date': '2021/08/09',
                    'account': '26',
                    'branch_no': '6460',
                    'stock_no': '2330',
                    'buy_sell': BSAction.Buy,
                    'order_type': OrderType.Stock,
                    'cost_price': 580.0,
                    'tradable_qty': 2000,
                    'today_qty': 2000,
                    'unrealized_profit': 0,
                    'unrealized_loss': -5000
                }
            ]
        }
    
    @staticmethod
    def unrealized_pnl_empty():
        """未實現損益查詢空回應"""
        return {
            'is_success': True,
            'message': None,
            'data': []
        }
    
    @staticmethod
    def get_orders_success():
        """委託單查詢成功回應"""
        return {
            'is_success': True,
            'message': None,
            'data': [
                FubonSDKResponses.place_order_success()['data'],
                {
                    'function_type': 0,
                    'date': '2023/10/12',
                    'seq_no': '00000000008',
                    'branch_no': '6460',
                    'account': '26',
                    'order_no': 'bA677',
                    'asset_type': 0,
                    'market': 'TAIEX',
                    'market_type': MarketType.IntradayOdd,
                    'stock_no': '0056',
                    'buy_sell': BSAction.Sell,
                    'price_type': PriceType.Limit,
                    'price': 32.5,
                    'quantity': 100,
                    'time_in_force': TimeInForce.ROD,
                    'order_type': OrderType.Stock,
                    'is_pre_order': False,
                    'status': 50,  # 完全成交
                    'after_price_type': PriceType.Limit,
                    'after_price': 32.5,
                    'unit': 1,
                    'after_qty': 100,
                    'filled_qty': 100,
                    'filled_money': 3250,
                    'before_qty': 0,
                    'before_price': 0.0,
                    'user_def': 'From_Test',
                    'last_time': '14:06:30.100',
                    'details': None,
                    'error_message': None
                }
            ]
        }
    
    @staticmethod
    def stock_quote_success():
        """股票報價查詢成功回應"""
        return {
            'symbol': '2330',
            'openPrice': 580.0,
            'highPrice': 585.0,
            'lowPrice': 578.0,
            'closePrice': 582.0,
            'lastPrice': 582.0,
            'bids': [
                {'price': 581.0, 'size': 100},
                {'price': 580.0, 'size': 200}
            ],
            'asks': [
                {'price': 582.0, 'size': 150},
                {'price': 583.0, 'size': 250}
            ]
        }
    
    @staticmethod
    def settlement_query_success():
        """交割查詢成功回應"""
        return {
            'is_success': True,
            'message': None,
            'data': {
                'details': [
                    {
                        'settlement_date': '2023/10/15',
                        'total_settlement_amount': 66000
                    },
                    {
                        'settlement_date': '2023/10/16',
                        'total_settlement_amount': -33000
                    }
                ]
            }
        }
    
    @staticmethod
    def settlement_query_empty():
        """交割查詢空回應"""
        return {
            'is_success': True,
            'message': None,
            'data': {
                'details': []
            }
        }

# 狀態碼映射
STATUS_CODES = {
    'PRE_ORDER': 0,      # 預約單
    'PENDING': 4,        # 系統將委託送往後台
    'TIMEOUT': 9,        # 連線逾時
    'NEW': 10,           # 委託成功
    'CANCELLED': 30,     # 未成交刪單成功
    'PARTIALLY_FILLED': 40,  # 部分成交，剩餘取消
    'FILLED': 50,        # 完全成交
    'FAILED': 90         # 失敗
}

# 時間格式範例
TIME_FORMATS = [
    '14:05:12.085',   # HH:MM:SS.fff
    '14:05:12',       # HH:MM:SS
    '09:30:00.000',   # 開盤時間
    '13:30:00'        # 收盤時間
]