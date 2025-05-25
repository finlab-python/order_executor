"""
Schwab 帳戶操作模組
"""

import logging
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Union

from finlab.markets.us import USMarket
from finlab.online.base_account import Account, Order, Stock
from finlab.online.enums import Action, OrderCondition, OrderStatus
from finlab.online.order_executor import Position
from schwab.auth import client_from_token_file


logger = logging.getLogger(__name__)

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
            logger.error(f'無法初始化 Schwab 客戶端: {e}')
            raise

        self.account_hash = self.client.get_account_numbers().json()[0]['hashValue']
        self.trades = {}

    def create_order(
        self,
        action: Action,
        stock_id: str,
        quantity: float,
        price: Optional[float] = None,
        market_order: bool = False,
        best_price_limit: bool = False,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """創建訂單

        Args:
            action (Action): 動作（買入或賣出）
            stock_id (str): 股票代碼
            quantity (float): 數量
            price (Optional[float]): 價格，默認為 None
            market_order (bool): 是否為市價單，默認為 False
            best_price_limit (bool): 是否為最佳限價單，默認為 False

        Raises:
            ValueError: 當股票代碼不在價格資訊中時
            ValueError: 當數量小於等於 0 時
        
        Returns:
            str: 訂單 ID，如果創建失敗則返回空字串

        Note:
            pass in `*args` and `**kwargs` for future compatibility, but currently not used.
        """

        try:
            # 驗證股票代碼
            if not stock_id or not stock_id.strip():
                raise ValueError('股票代碼不能為空')
            
            pinfo = self.get_price_info([stock_id])
            limitup = float(pinfo[stock_id]['漲停價'])
            limitdn = float(pinfo[stock_id]['跌停價'])

            if stock_id not in pinfo:
                raise ValueError(f'股票 {stock_id} 不在價格資訊中')

            if quantity <= 0:
                raise ValueError(f'數量必須為正數，得到 {quantity}')

            action_str = 'BUY' if action == Action.BUY else 'SELL'

            order = {
                'session': 'NORMAL',
                'duration': 'DAY',
                'orderLegCollection': [
                    {
                        'instruction': action_str,
                        'instrument': {'assetType': 'EQUITY', 'symbol': stock_id},
                        'quantity': quantity,
                    }
                ],
                'orderStrategyType': 'SINGLE',
            }

            if market_order:
                order['orderType'] = 'MARKET'
            elif best_price_limit:
                order['orderType'] = 'LIMIT'
                if action == Action.BUY:
                    order['price'] = format_price(limitdn)
                elif action == Action.SELL:
                    order['price'] = format_price(limitup)
            else:
                if price is None:
                    raise ValueError("限價單必須提供價格 (price 不能為 None)")
                order['orderType'] = 'LIMIT'
                order['price'] = format_price(price)

            trade_response = self.client.place_order(self.account_hash, order)
            if trade_response.status_code == 201:
                location_url = trade_response.headers.get('location')
                if not location_url:
                    raise Exception('API回應中缺少location header')
                
                order_id = location_url.split('/')[-1]
                if not order_id:
                    raise Exception('無法從location URL中提取訂單ID')
                
                logger.info(f'成功創建訂單 {order_id}, {order}')
                return str(order_id)
            else:
                # 🔧 關鍵修正：失敗時拋出異常而非返回空字串
                error_msg = f'下單失敗: {trade_response.status_code}: {trade_response.text}'
                logger.error(error_msg)
                raise Exception(error_msg)

        except Exception as e:
            logger.error(f'創建訂單時發生錯誤: {e}')
            raise

    def get_price_info(self, stock_ids: Optional[List[str]] = None) -> Dict[str, Dict[str, float]]:
        """取得股票的價格資訊

        Args:
            stock_ids (Optional[List[str]]): 股票代碼列表

        Returns:
            Dict[str, Dict[str, float]]: 股票價格資訊字典

        Note:
            美股無漲跌停限制，因此漲跌停價使用 current price * 1.5 和 current price * 0.5 代替，若是要立刻買賣，可以使用 market_order
        """
        if not stock_ids:
            logger.warning('API: 股票代碼為空，無法取得價格資訊')
            return {}

        try:
            quote_response = self.client.get_quotes(
                stock_ids, fields=self.client.Quote.Fields.QUOTE
            )
            if quote_response.status_code != 200:
                logger.error(
                    f'API: 獲取報價失敗: {quote_response.status_code}: {quote_response.text}'
                )
                return {}

            quote_json = quote_response.json()

            ref = {}
            for s in stock_ids:
                try:
                    quote = quote_json[s]['quote']
                    current_price = quote['closePrice']
                    ref[s] = {
                        '收盤價': current_price,
                        '漲停價': current_price * 1.5,
                        '跌停價': current_price * 0.5,
                    }
                except Exception as e:
                    logger.warning(f'API: 無法獲取股票 {s} 的資訊: {e}')
            return ref

        except Exception as e:
            logger.error(f'API: 獲取價格資訊時發生錯誤: {e}')
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
            
        """
        try:
            order = self.get_orders()[order_id]
            action = order.action
            stock_id = order.stock_id
            quantity = order.quantity - order.filled_quantity

            self.cancel_order(order_id)
            self.create_order(
                action=action, stock_id=stock_id, quantity=quantity, price=price,
            )
        except Exception as e:
            logger.error(f'更新訂單 {order_id} 時發生錯誤: {e}')
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
                logger.info(f'API: 成功取消訂單 {order_id}')
            else:
                logger.warning(
                    f'API: 無法取消訂單 {order_id}: {response.status_code}: {response.text}'
                )
        except Exception as e:
            logger.error(f'API: 取消訂單 {order_id} 時發生錯誤: {e}')

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
                logger.error(
                    f'API: 獲取持倉失敗: {position_response.status_code}: {position_response.text}'
                )
                return Position.from_list([])

            position = position_response.json()[0]['securitiesAccount']['positions']

            # TODO: 確認是否需要處理其他類型的資產
            return Position.from_list(
                # 計算 quantity，需要考慮 longQuantity 和 shortQuantity
                [
                    {
                        'stock_id': p['instrument']['symbol'],
                        'quantity': (float(p['longQuantity']) - float(p['shortQuantity'])),
                        'order_condition': OrderCondition.SHORT_SELLING if p['shortQuantity'] > 0 else OrderCondition.CASH,
                    }
                    for p in position
                ]
            )
        except Exception as e:
            logger.error(f'API: 獲取持倉時發生錯誤: {e}')
            return Position.from_list([])

    def get_orders(self) -> Dict[int, Order]:
        """獲取所有未完成的訂單

        Returns:
            Dict[int, Order]: 訂單ID到訂單對象的映射
        """
        try:
            orders_response = self.client.get_orders_for_all_linked_accounts()
            if orders_response.status_code != 200:
                logger.error(
                    f'API: 獲取訂單失敗: {orders_response.status_code}: {orders_response.text}'
                )
                return {}

            orders = orders_response.json()

            active_statuses = [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED]
            return {
                t['orderId']: trade_to_order(t)
                for t in orders
                if map_trade_status(t['status']) in active_statuses
            }
        except Exception as e:
            logger.error(f'API: 獲取訂單時發生錯誤: {e}')
            return {}

    def get_stocks(self, stock_ids: List[str]) -> Dict[str, Stock]:
        """獲取股票資訊

        Args:
            stock_ids (List[str]): 股票代碼列表

        Returns:
            Dict[str, Stock]: 股票代碼到股票資訊的映射
        """
        if not stock_ids:
            logger.warning('API: 股票代碼為空，無法取得股票資訊')
            return {}
        try:
            quote_response = self.client.get_quotes(
                stock_ids, fields=self.client.Quote.Fields.QUOTE
            )
            if quote_response.status_code != 200:
                logger.error(
                    f'API: 獲取股票資訊失敗: {quote_response.status_code}: {quote_response.text}'
                )
                return {}

            json_response = quote_response.json()

            ret = {}
            for s in stock_ids:
                try:
                    ret[s] = quote_to_stock(json_response[s])
                except Exception as e:
                    logger.warning(f'API: 無法獲取股票 {s} 的資訊: {e}')

            return ret
        except Exception as e:
            logger.error(f'API: 獲取股票資訊時發生錯誤: {e}')
            return {}

    def get_total_balance(self) -> float:
        """獲取總資產餘額

        Returns:
            float: 總資產餘額
        """
        try:
            balance_response = self.client.get_accounts()
            if balance_response.status_code != 200:
                logger.error(
                    f'API: 獲取總資產餘額失敗: {balance_response.status_code}: {balance_response.text}'
                )
                return 0

            return float(
                balance_response.json()[0]['aggregatedBalance']['currentLiquidationValue']
            )
        except Exception as e:
            logger.error(f'API: 獲取總資產餘額時發生錯誤: {e}')
            return 0

    def get_cash(self) -> float:
        """獲取現金餘額

        Returns:
            float: 現金餘額
        """
        try:
            cash_response = self.client.get_accounts()
            if cash_response.status_code != 200:
                logger.error(
                    f'API: 獲取現金餘額失敗: {cash_response.status_code}: {cash_response.text}'
                )
                return 0

            return float(
                cash_response.json()[0]['securitiesAccount']['currentBalances']['cashBalance']
            )
        except Exception as e:
            logger.error(f'API: 獲取現金餘額時發生錯誤: {e}')
            return 0

    def get_settlement(self) -> int:
        """獲取結算交割資料
        Raises:
            NotImplementedError: 此功能尚未實作
        """
        raise NotImplementedError("Schwab 帳戶的結算交割功能尚未實作")

    def sep_odd_lot_order(self) -> bool:
        """檢查是否分離零股訂單

        Returns:
            bool: 始終返回 False
        """
        return False

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
        Order: FinLab 格式的委託單
    """
    action = map_action(trade['orderLegCollection'][0]['instruction'])
    status = map_trade_status(trade['status'])
    order_condition = map_order_condition(
        trade['orderLegCollection'][0]['instruction']
    )
    quantity = float(trade['quantity'])
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
        close=quote['lastPrice'],
        bid_price=quote['bidPrice'],
        ask_price=quote['askPrice'],
        bid_volume=quote['bidSize'],
        ask_volume=quote['askSize'],
    )


def format_price(price: Union[float, int, str]) -> str:
    """
    將價格格式化為字串，根據價格大小限制小數位數。

    Args:
        price (float | int | str): 價格

    Returns:
        str: 格式化後的價格字串

    Raises:
        ValueError: 當價格無法轉換為 Decimal 時
    
    Note:
        Schwab 的規定：價格大於 1 美元時，小數點後最多只能有 2 位；價格小於 1 美元時，小數點後最多只能有 4 位。
    """
    try:
        price_decimal = Decimal(str(price))
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError(f"無法將價格 {price} 轉換為 Decimal 格式")
    
    if price_decimal >= 1:
        formatted_price = price_decimal.quantize(Decimal('0.01'), rounding='ROUND_DOWN')
    else:
        formatted_price = price_decimal.quantize(Decimal('0.0001'), rounding='ROUND_DOWN')
    
    return str(formatted_price)
