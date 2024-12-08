"""
Schwab 帳戶操作模組
"""

import logging
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

from finlab.markets.us import USMarket
from finlab.online.base_account import Account, Order, Stock
from finlab.online.enums import Action, OrderCondition, OrderStatus
from finlab.online.order_executor import Position
from schwab.auth import client_from_token_file

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class SchwabAccount(Account):
    """Schwab 帳戶操作類

    繼承自 Account 類，提供 Schwab 特定的帳戶操作功能。

    Attributes:
        api_key (str): Schwab API 金鑰
        app_secret (str): Schwab 應用程式密鑰
        token_path (str): Schwab 令牌文件路徑
        client: Schwab 客戶端實例
        account_hash (str): 帳戶哈希值
        trades (dict): 交易記錄

    """

    required_module = 'schwab-py'
    module_version = '1.4.0'

    def __init__(
        self,
        token_path: Optional[str] = None,
        api_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        asyncio: bool = False,
        enforce_enums: bool = True,
    ):
        """初始化 SchwabAccount 實例

        Args:
            token_path (Optional[str]): 令牌文件路徑
            api_key (Optional[str]): API 金鑰
            app_secret (Optional[str]): 應用程式密鑰
            asyncio (bool): 是否使用非同步 IO
            enforce_enums (bool): 是否強制使用枚舉

        Raises:
            ValueError: 當必要的參數缺失時
        """
        self.api_key = api_key or os.environ['SCHWAB_API_KEY']
        self.app_secret = app_secret or os.environ['SCHWAB_SECRET']
        self.token_path = token_path or os.environ['SCHWAB_TOKEN_PATH']

        if not all([self.api_key, self.app_secret, self.token_path]):
            raise ValueError('API 金鑰、應用程式密鑰和令牌路徑都必須提供')

        try:
            self.client = client_from_token_file(
                api_key=self.api_key,
                app_secret=self.app_secret,
                token_path=self.token_path,
            )
        except Exception as e:
            logging.error(f'無法初始化 Schwab 客戶端: {e}')
            raise

        self.account_hash = self.client.get_account_numbers().json()[0]['hashValue']
        self.trades = {}

    def create_order(
        self,
        action: Action,
        stock_id: str,
        quantity: int,
        price: Optional[float] = None,
        odd_lot: bool = True,
        market_order: bool = False,
        best_price_limit: bool = False,
        order_cond: OrderCondition = OrderCondition.CASH,
    ) -> None:
        """創建訂單

        Args:
            action (Action): 動作（買入或賣出）
            stock_id (str): 股票代碼
            quantity (int): 數量
            price (Optional[float]): 價格，默認為 None
            odd_lot (bool): 是否為零股，默認為 True
            market_order (bool): 是否為市價單，默認為 False
            best_price_limit (bool): 是否為最佳限價單，默認為 False
            order_cond (OrderCondition): 訂單條件，默認為 OrderCondition.CASH

        Raises:
            ValueError: 當股票代碼不在價格資訊中時
            ValueError: 當數量小於等於 0 時

        """
        try:
            pinfo = self.get_price_info([stock_id])

            if stock_id not in pinfo:
                raise ValueError(f'股票 {stock_id} 不在價格資訊中')

            if quantity <= 0:
                raise ValueError(f'數量必須為正數，得到 {quantity}')

            action_str = 'BUY' if action == Action.BUY else 'SELL'

            order = {
                'session': 'NORMAL',
                'duration': 'DAY',
                'orderType': 'MARKET' if market_order or best_price_limit else 'LIMIT',
                'orderLegCollection': [
                    {
                        'instruction': action_str,
                        'instrument': {'assetType': 'EQUITY', 'symbol': stock_id},
                        'quantity': quantity,
                    }
                ],
                'orderStrategyType': 'SINGLE',
            }

            if not (market_order or best_price_limit):
                order['price'] = price

            trade_response = self.client.place_order(self.account_hash, order)
            if trade_response.status_code == 201:
                logging.info(f'API: 成功創建訂單, {order}')
            else:
                logging.warning(
                    f'API: 無法創建訂單: {trade_response.status_code}: {trade_response.text}'
                )

        except Exception as e:
            logging.error(f'API: 創建訂單時發生錯誤: {e}')
            raise

    def get_price_info(self, stock_ids: Optional[List[str]] = None) -> Dict[str, Dict[str, float]]:
        """取得股票的價格資訊

        Args:
            stock_ids (Optional[List[str]]): 股票代碼列表

        Returns:
            Dict[str, Dict[str, float]]: 股票價格資訊字典

        Note:
            美股無漲跌停限制，因此漲跌停價使用 52WeekHigh 和 52WeekLow 代替，若是要立刻買賣，可以使用 market_order 或 best_price_limit
        """
        if stock_ids is None:
            return {}

        try:
            quote_response = self.client.get_quotes(
                stock_ids, fields=self.client.Quote.Fields.QUOTE
            )
            if quote_response.status_code != 200:
                logging.error(
                    f'API: 獲取報價失敗: {quote_response.status_code}: {quote_response.text}'
                )
                return {}

            quote_json = quote_response.json()

            ref = {}
            for s in stock_ids:
                try:
                    quote = quote_json[s]['quote']
                    ref[s] = {
                        '收盤價': quote['closePrice'],
                        '漲停價': quote['52WeekHigh'],
                        '跌停價': quote['52WeekLow'],
                    }
                except Exception as e:
                    logging.warning(f'API: 無法獲取股票 {s} 的資訊: {e}')
            return ref

        except Exception as e:
            logging.error(f'API: 獲取價格資訊時發生錯誤: {e}')
            return {}

    def update_order(self, order_id: int, price: float) -> None:
        """更新現有訂單的價格

        通過取消當前訂單並創建一個具有更新價格的新訂單。

        Args:
            order_id (int): 要更新的訂單ID
            price (float): 訂單的新價格

        Raises:
            ValueError: 如果訂單無法更新

        Note:
            美股為零股，finlab order's quantity 單位 1 張，所以 quantity 要乘以 1000
        """
        try:
            order = self.get_orders()[order_id]
            action = order.action
            stock_id = order.stock_id
            quantity = order.quantity - order.filled_quantity
            quantity *= 1000

            self.cancel_order(order_id)
            self.create_order(
                action=action, stock_id=stock_id, quantity=quantity, price=price, odd_lot=True
            )
        except Exception as e:
            logging.error(f'更新訂單 {order_id} 時發生錯誤: {e}')
            raise ValueError(f'無法更新訂單 {order_id}') from e

    def cancel_order(self, order_id: int) -> None:
        """取消訂單

        Args:
            order_id (int): 要取消的訂單ID
        """
        if order_id not in self.trades:
            self.trades = self.get_orders()

        try:
            response = self.client.cancel_order(order_id, self.account_hash)
            if response.status_code == 200:
                logging.info(f'API: 成功取消訂單 {order_id}')
            else:
                logging.warning(
                    f'API: 無法取消訂單 {order_id}: {response.status_code}: {response.text}'
                )
        except Exception as e:
            logging.error(f'API: 取消訂單 {order_id} 時發生錯誤: {e}')

    def get_position(self) -> Position:
        """獲取當前持倉

        Returns:
            Position: 當前持倉資訊
        """
        try:
            position_response = self.client.get_accounts(
                fields=self.client.Account.Fields.POSITIONS
            )
            if position_response.status_code != 200:
                logging.error(
                    f'API: 獲取持倉失敗: {position_response.status_code}: {position_response.text}'
                )
                return Position.from_list([])

            position = position_response.json()[0]['securitiesAccount']['positions']

            return Position.from_list(
                # 計算 quantity，需要考慮 longQuantity 和 shortQuantity
                [
                    {
                        'stock_id': p['instrument']['symbol'],
                        'quantity': (float(p['longQuantity']) - float(p['shortQuantity'])) / 1000,
                        'order_condition': OrderCondition.SHORT_SELLING if p['shortQuantity'] > 0 else OrderCondition.CASH,
                    }
                    for p in position
                ]
            )
        except Exception as e:
            logging.error(f'API: 獲取持倉時發生錯誤: {e}')
            return Position.from_list([])

    def get_orders(self) -> Dict[int, Order]:
        """獲取所有未完成的訂單

        Returns:
            Dict[int, Order]: 訂單ID到訂單對象的映射
        """
        try:
            orders_response = self.client.get_orders_for_all_linked_accounts()
            if orders_response.status_code != 200:
                logging.error(
                    f'API: 獲取訂單失敗: {orders_response.status_code}: {orders_response.text}'
                )
                return {}

            orders = orders_response.json()

            return {
                t['orderId']: trade_to_order(t)
                for t in orders
                if map_trade_status(t['status']) == OrderStatus.NEW
            }
        except Exception as e:
            logging.error(f'API: 獲取訂單時發生錯誤: {e}')
            return {}

    def get_stocks(self, stock_ids: List[str]) -> Dict[str, Stock]:
        """獲取股票資訊

        Args:
            stock_ids (List[str]): 股票代碼列表

        Returns:
            Dict[str, Stock]: 股票代碼到股票資訊的映射
        """
        try:
            quote_response = self.client.get_quotes(
                stock_ids, fields=self.client.Quote.Fields.QUOTE
            )
            if quote_response.status_code != 200:
                logging.error(
                    f'API: 獲取股票資訊失敗: {quote_response.status_code}: {quote_response.text}'
                )
                return {}

            json_response = quote_response.json()

            ret = {}
            for s in stock_ids:
                try:
                    ret[s] = quote_to_stock(json_response[s])
                except Exception as e:
                    logging.warning(f'API: 無法獲取股票 {s} 的資訊: {e}')

            return ret
        except Exception as e:
            logging.error(f'API: 獲取股票資訊時發生錯誤: {e}')
            return {}

    def get_total_balance(self) -> float:
        """獲取總資產餘額

        Returns:
            float: 總資產餘額
        """
        try:
            balance_response = self.client.get_accounts()
            if balance_response.status_code != 200:
                logging.error(
                    f'API: 獲取總資產餘額失敗: {balance_response.status_code}: {balance_response.text}'
                )
                return 0

            return float(
                balance_response.json()[0]['aggregatedBalance']['currentLiquidationValue']
            )
        except Exception as e:
            logging.error(f'API: 獲取總資產餘額時發生錯誤: {e}')
            return 0

    def get_cash(self) -> float:
        """獲取現金餘額

        Returns:
            float: 現金餘額
        """
        try:
            cash_response = self.client.get_accounts()
            if cash_response.status_code != 200:
                logging.error(
                    f'API: 獲取現金餘額失敗: {cash_response.status_code}: {cash_response.text}'
                )
                return 0

            return float(
                cash_response.json()[0]['securitiesAccount']['currentBalances']['cashBalance']
            )
        except Exception as e:
            logging.error(f'API: 獲取現金餘額時發生錯誤: {e}')
            return 0

    def get_settlement(self) -> int:
        """獲取結算交割資料

        Returns:
            int: 始終返回 0，因為此功能暫不支援
        """
        return 0

    def sep_odd_lot_order(self) -> bool:
        """檢查是否分離零股訂單

        Returns:
            bool: 始終返回 True
        """
        return True

    def get_market(self) -> USMarket:
        """獲取市場資訊

        Returns:
            USMarket: 美國市場資訊實例
        """
        return USMarket()


def map_trade_status(status: str) -> OrderStatus:
    """將 Schwab 的委託單狀態轉換成 FinLab 的委託單狀態

    Args:
        status (str): Schwab 的委託單狀態

    Returns:
        OrderStatus: FinLab 的委託單狀態
    """
    status_map = {
        'AWAITING_PARENT_ORDER': OrderStatus.NEW,
        'AWAITING_CONDITION': OrderStatus.NEW,
        'AWAITING_STOP_CONDITION': OrderStatus.NEW,
        'AWAITING_MANUAL_REVIEW': OrderStatus.NEW,
        'ACCEPTED': OrderStatus.NEW,
        'AWAITING_UR_OUT': OrderStatus.NEW,
        'PENDING_ACTIVATION': OrderStatus.NEW,
        'QUEUED': OrderStatus.NEW,
        'WORKING': OrderStatus.NEW,
        'REJECTED': OrderStatus.CANCEL,
        'PENDING_CANCEL': OrderStatus.NEW,
        'CANCELED': OrderStatus.CANCEL,
        'PENDING_REPLACE': OrderStatus.NEW,
        'REPLACED': OrderStatus.CANCEL,
        'FILLED': OrderStatus.FILLED,
        'EXPIRED': OrderStatus.CANCEL,
        'NEW': OrderStatus.NEW,
        'AWAITING_RELEASE_TIME': OrderStatus.NEW,
        'PENDING_ACKNOWLEDGEMENT': OrderStatus.NEW,
        'PENDING_RECALL': OrderStatus.NEW,
        'UNKNOWN': OrderStatus.NEW,
    }
    if status not in status_map:
        raise ValueError(f'無效的狀態: {status}')
    return status_map[status]


def map_order_condition(action: str) -> OrderCondition:
    """將 Schwab 的訂單條件轉換成 FinLab 的訂單條件

    Args:
        action (str): Schwab 的訂單動作

    Returns:
        OrderCondition: FinLab 的訂單條件
    """
    condition_map = {
        'BUY': OrderCondition.CASH,  # EQUITY (Stocks and ETFs)
        'SELL': OrderCondition.CASH,  # EQUITY (Stocks and ETFs)
        'BUY_TO_COVER': OrderCondition.CASH,  # EQUITY (Stocks and ETFs)
        'SELL_SHORT': OrderCondition.SHORT_SELLING,  # EQUITY (Stocks and ETFs)
        'BUY_TO_OPEN': OrderCondition.CASH,  # Option
        'BUY_TO_CLOSE': OrderCondition.CASH,  # Option
        'SELL_TO_OPEN': OrderCondition.CASH,  # Option
        'SELL_TO_CLOSE': OrderCondition.CASH,  # Option
    }
    if action not in condition_map:
        raise ValueError(f'無效的操作: {action}')
    return condition_map[action]


def map_action(action: str) -> Action:
    """將 Schwab 的買賣方向轉換成 FinLab 的買賣方向

    Args:
        action (str): Schwab 的買賣方向

    Returns:
        Action: FinLab 的買賣方向
    """
    action_map = {
        'BUY': Action.BUY,  # EQUITY (Stocks and ETFs)
        'SELL': Action.SELL,  # EQUITY (Stocks and ETFs)
        'BUY_TO_COVER': Action.BUY,  # EQUITY (Stocks and ETFs)
        'SELL_SHORT': Action.SELL,  # EQUITY (Stocks and ETFs)
        'BUY_TO_OPEN': Action.BUY,  # Option
        'BUY_TO_CLOSE': Action.BUY,  # Option
        'SELL_TO_OPEN': Action.SELL,  # Option
        'SELL_TO_CLOSE': Action.SELL,  # Option
    }
    if action not in action_map:
        raise ValueError(f'無效的操作: {action}')
    return action_map[action]


def trade_to_order(trade: Dict[str, Any]) -> Order:
    """將 Schwab 的委託單轉換成 FinLab 格式

    Args:
        trade (Dict[str, Any]): Schwab 的委託單物件

    Returns:
        Order: FinLab 格式的委託單, finlab 的 quantity 是 1 張, 所以 Schwab 的 quantity 要除以 1000
    """
    action = map_action(trade['orderLegCollection'][0]['instruction'])
    status = map_trade_status(trade['status'])
    order_condition = map_order_condition(
        trade['orderLegCollection'][0]['instruction']
    )
    quantity = float(trade['quantity']) / 1000
    filled_quantity = float(trade['filledQuantity'])

    return Order(
        order_id=trade['orderId'],
        stock_id=trade['orderLegCollection'][0]['instrument']['symbol'],
        action=action,
        price=trade['price'] if trade['orderType'] == "LIMIT" else None,
        quantity=quantity,
        filled_quantity=filled_quantity,
        status=status,
        order_condition=order_condition,
        time=trade['enteredTime'],
        org_order=trade,
    )


def quote_to_stock(json_response: Dict[str, Any]) -> Stock:
    """將 Schwab 股價行情轉換成 FinLab 格式

    Args:
        json_response (Dict[str, Any]): Schwab 的股價行情物件

    Returns:
        Stock: FinLab 格式的股價行情
    """
    quote = json_response['quote']
    return Stock(
        stock_id=json_response['symbol'],
        open=quote['openPrice'],
        high=quote['highPrice'],
        low=quote['lowPrice'],
        close=quote['closePrice'],
        bid_price=quote['bidPrice'],
        ask_price=quote['askPrice'],
        bid_volume=quote['bidSize'],
        ask_volume=quote['askSize'],
    )