import logging
import os
from decimal import Decimal
from typing import Dict, List, Optional

from finlab.market_info import USAllMarketInfo
from finlab.online.base_account import Account, Order, Stock
from finlab.online.enums import Action, OrderCondition, OrderStatus
from finlab.online.order_executor import Position
from schwab.auth import client_from_token_file


class SchwabAccount(Account):
    """帳戶操作摘要

    Args:
        Account (Account 類型): 帳戶實例

    Notes:
        每個帳戶每分鐘預期的訂單相關請求數量。輸入範圍為每分鐘 0-120 個請求。
        包括發送新訂單、替換現有訂單和取消訂單。schwab 的後台系統會自動節流限制。

    Examples:
        ```py
        import os
        from finlab.online.schwab_account import SchwabAccount

        os.environ['SCHWAB_API_KEY'] = 'API_KEY'
        os.environ['SCHWAB_SECRET'] = 'SECRET'
        os.environ['SCHWAB_TOKEN_PATH'] = 'TOKEN_PATH'

        acc = SchwabAccount()
        ```
    """

    required_module = 'schwab-py'
    module_version = '1.4.0'

    def __init__(
        self, token_path=None, api_key=None, app_secret=None, asyncio=False, enforce_enums=True
    ):
        api_key = api_key or os.environ.get('SCHWAB_API_KEY')
        app_secret = app_secret or os.environ.get('SCHWAB_SECRET_KEY')
        token_path = token_path or os.environ.get('SCHWAB_TOKEN_PATH')

        self.client = client_from_token_file(
            token_path=token_path,
            api_key=api_key,
            app_secret=app_secret,
        )
        self.account_hash = self.client.get_account_numbers().json()[0].get('hashValue')
        self.trades = {}

    def create_order(
        self,
        action,
        stock_id,
        quantity,
        price=None,
        odd_lot=True,
        market_order=False,
        best_price_limit=False,
        order_cond=OrderCondition.CASH,
    ):
        """創建訂單

        Args:
            action (Action): 動作（買入或賣出）
            stock_id (str): 股票代碼
            quantity (int): 數量
            price (float, optional): 價格，默認為 None
            odd_lot (bool, optional): 是否為零股，默認為 True
            market_order (bool, optional): 是否為市價單，默認為 False
            best_price_limit (bool, optional): 是否為最佳限價單，默認為 False
            order_cond (OrderCondition, optional): 訂單條件，默認為 OrderCondition.CASH

        Raises:
            Exception: 當股票代碼不在價格資訊中時
            Exception: 當數量小於等於 0 時

        Return:
            Pass

        Notes:
            使用 market_order 或 best_price_limit 任一為 True 時，使用市價單
            設定為全時段下單，盤前、盤中、盤後皆可下單
            符合目前台股的下單周期，只下當天有效單

        Examples:
            ```py
            acc.create_order(
                action=Action.BUY,
                stock_id='AAPL',
                quantity=1,
                price=25,
                odd_lot=True,
                market_order=False,
                best_price_limit=False,
                order_cond=OrderCondition.CASH,
            )
            ```

        """
        pinfo = self.get_price_info([stock_id])

        if stock_id not in pinfo:
            raise Exception(f'stock {stock_id} not in price info')

        if quantity <= 0:
            raise Exception(f'quantity must be positive, got {quantity}')

        if action == Action.BUY:
            action = 'BUY'
        elif action == Action.SELL:
            action = 'SELL'

        # 假如 market_order or best_price_limit 任一為 True, 則使用市價單
        if market_order or best_price_limit:
            order = {
                'session': 'NORMAL',  # 美股 Normal Order 美東時間 09:30～16:00
                'duration': 'DAY',  # 只下當天有效單
                'orderType': 'MARKET',
                'orderLegCollection': [
                    {
                        'instruction': action,
                        'instrument': {'assetType': 'EQUITY', 'symbol': stock_id},
                        'quantity': quantity,
                    }
                ],
                'orderStrategyType': 'SINGLE',
            }
        else:
            order = {
                'session': 'NORMAL',  # 美股 Normal Order 美東時間 09:30～16:00
                'duration': 'DAY',  # 只下當天有效單
                'orderType': 'LIMIT',  # 統一為限價單
                'price': price,
                'orderLegCollection': [
                    {
                        'instruction': action,
                        'instrument': {'assetType': 'EQUITY', 'symbol': stock_id},
                        'quantity': quantity,
                    }
                ],
                'orderStrategyType': 'SINGLE',
            }

        # Empty response body if an order was successfully placed/created.
        try:
            trade = self.client.place_order(self.account_hash, order)
            if trade.text == '':
                print(f'API: create order, {order}')
            else:
                logging.warning(f'API: cannot create order: {trade.text}')
        except Exception as e:
            logging.warning(f'API: cannot create order: {e}')

    def get_price_info(self, stock_ids: Optional[List[str]] = None) -> Dict[str, Dict[str, float]]:
        """取得股票的價格資訊

        Args:
            stock_ids (Optional[List[str]]): ["AAPL", "GOOG", "MSFT"]

        Return:
            Dict[str, Dict[str, float]]: {"AAPL": {"收盤價": 123.45, "漲停價": 123.45, "跌停價": 123.45}, ...}

        Notes:
            由於美股無漲跌停價，因此漲跌停價使用 52 週最高最低價代替

        Examples:
            ```py
            acc.get_price_info(["AAPL", "GOOG", "MSFT"])
            ```

        """
        if stock_ids is None:
            return {}

        json_response = self.client.get_quotes(
            stock_ids, fields=self.client.Quote.Fields.QUOTE
        ).json()

        ref = {}
        for s in stock_ids:
            try:
                ref[s] = {
                    '收盤價': json_response.get(s).get('quote').get('closePrice'),
                    '漲停價': json_response.get(s).get('quote').get('52WeekHigh'),
                    '跌停價': json_response.get(s).get('quote').get('52WeekLow'),
                }
            except Exception as e:
                logging.warn(f'API: cannot get stock {s}: {e}')
        return ref

    def update_order(self, order_id, price):
        """更新現有訂單的價格，通過取消當前訂單並創建一個具有更新價格的新訂單。

        Args:
            order_id (int): 要更新的訂單ID。
            price (float): 訂單的新價格。

        Raises:
            ValueError: 如果訂單無法更新。

        Return:
            Pass

        Notes:
            Pass

        Examples:
            ```py
            acc.update_order(123456, 100)
            ```
        """
        order = self.get_orders()[order_id]

        try:
            action = order.action
            stock_id = order.stock_id
            q = order.quantity - order.filled_quantity
            q *= 1000

            self.cancel_order(order_id)
            self.create_order(
                action=action, stock_id=stock_id, quantity=q, price=price, odd_lot=True
            )
        except ValueError as ve:
            logging.warning(f'update_order: Cannot update price of order {order_id}: {ve}')

    def cancel_order(self, order_id):
        if order_id not in self.trades:
            self.trades = self.get_orders()

        try:
            self.client.cancel_order(order_id, self.account_hash)
        except Exception as e:
            logging.warning(f'API: cannot cancel order {order_id}: {e}')

    def get_position(self):
        position = (
            self.client.get_accounts(fields=self.client.Account.Fields.POSITIONS)
            .json()[0]
            .get('securitiesAccount')
            .get('positions')
        )
        order_conditions = OrderCondition.CASH

        return Position.from_list(
            [
                {
                    'stock_id': p.get('instrument').get('symbol'),
                    'quantity': Decimal(p.get('longQuantity')) / 1000,
                    'order_condition': order_conditions,
                }
                for p in position
            ]
        )

    def get_orders(self):
        orders = self.client.get_orders_for_all_linked_accounts().json()

        return {
            t['orderId']: trade_to_order(t)
            for t in orders
            if map_trade_status(t['status']) == OrderStatus.NEW
        }

    def get_stocks(self, stock_ids):
        json_response = self.client.get_quotes(
            stock_ids, fields=self.client.Quote.Fields.QUOTE
        ).json()

        ret = {}
        for s in stock_ids:
            try:
                ret[s] = quote_to_stock(json_response[s])
            except Exception as e:
                logging.warn(f'API: cannot get stock {s}: {e}')

        return ret

    def get_total_balance(self):
        return Decimal(
            self.client.get_accounts()
            .json()[0]
            .get('aggregatedBalance')
            .get('currentLiquidationValue')
        )

    def get_cash(self):
        return Decimal(
            self.client.get_accounts()
            .json()[0]
            .get('securitiesAccount')
            .get('currentBalances')
            .get('cashBalance')
        )

    def get_settlement(self):
        """結算交割資料
        Args:
            Pass

        Return:
            0

        Notes:
            美股即時帳戶權益資訊，包含現金、股票、期貨、選擇權等資訊，此功能暫時不支援，因此回傳空值

        Examples:
            ```py
            acc.get_settlement()
            ```
        """
        return 0

    def sep_odd_lot_order(self):
        return True

    def get_market(self):
        return USAllMarketInfo()


def map_trade_status(status):
    """將 schwab 的委託單狀態轉換成 finlab 的委託單狀態

    Args:
        status (str): schwab 的委託單狀態

    Return:
        OrderStatus: finlab 的委託單狀態

    Notes:
        目前只是簡單對應，實際應該要根據 schwab 的委託單狀態來，還要再重新確認過
        TODO 確認美股的委託單狀態的定義邏輯
    """
    return {
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
    }[status]


def map_order_condition(action):
    """將 schwab 的訂單條件轉換成 finlab 的訂單條件
    函數目前回傳固定的訂單條件值 `OrderCondition.CASH`。

    Args:

    Return:
        OrderCondition: 映射的訂單條件，目前設置為 `OrderCondition.CASH`。

    Notes:
        目前為了簡化，固定回傳 `OrderCondition.CASH`
        Schwab 的訂單條件 在 finlab 中沒有對應的概念，因此固定回傳 `OrderCondition.CASH`
        訂單之現股//融資//融券 在 instruction 中有定義，因此不需要在 order_condition 中定義
    """
    return {
        'BUY': OrderCondition.CASH,
        'SELL': OrderCondition.CASH,
        'BUY_TO_COVER': OrderCondition.CASH,
        'SELL_SHORT': OrderCondition.SHORT_SELLING,
        'BUY_TO_OPEN': OrderCondition.CASH,
        'BUY_TO_CLOSE': OrderCondition.CASH,
        'SELL_TO_OPEN': OrderCondition.CASH,
        'SELL_TO_CLOSE': OrderCondition.CASH,
    }[action]


def map_action(action):
    """將 schwab 的買賣方向轉換成 finlab 的買賣方向

    Args:
        action (str): schwab 的買賣方向

    Return:
        Action: finlab 的買賣方向

    Notes:
        Pass
    """
    return {
        'BUY': Action.BUY,
        'SELL': Action.SELL,
        'BUY_TO_COVER': Action.BUY,
        'SELL_SHORT': Action.SELL,
        'BUY_TO_OPEN': Action.BUY,
        'BUY_TO_CLOSE': Action.BUY,
        'SELL_TO_OPEN': Action.SELL,
        'SELL_TO_CLOSE': Action.SELL,
    }[action]


def trade_to_order(trade):
    """將 schwab 的委託單轉換成 finlab 格式

    Args:
        trade (Any): schwab 的委託單物件

    Return:
        Order: finlab 格式的委託單

    Notes:
        美股為零股，但為了整合 finlab 的介面，因此 quantity 會除以 1000
    """
    action = map_action(trade.get('orderLegCollection')[0].get('instruction'))
    status = map_trade_status(trade.get('status'))
    order_condition = map_order_condition(trade.get('orderLegCollection')[0].get('instruction'))
    quantity = Decimal(trade.get('quantity')) / 1000
    filled_quantity = Decimal(trade.get('filledQuantity'))

    return Order(
        **{
            'order_id': trade.get('orderId'),
            'stock_id': trade.get('orderLegCollection')[0].get('instrument').get('symbol'),
            'action': action,
            'price': trade.get('price'),
            'quantity': quantity,
            'filled_quantity': filled_quantity,
            'status': status,
            'order_condition': order_condition,
            'time': trade.get('enteredTime'),
            'org_order': trade,
        }
    )


def quote_to_stock(json_response):
    """將 schwab 股價行情轉換成 finlab 格式

    Args:
        json_response (Any): schwab 的股價行情物件

    Return:
        Stock: finlab 格式的股價行情

    Notes:
        Pass
    """
    r = json_response
    return Stock(
        stock_id=r.get('symbol'),
        open=r.get('quote')['openPrice'],
        high=r.get('quote')['highPrice'],
        low=r.get('quote')['lowPrice'],
        close=r.get('quote')['closePrice'],
        bid_price=r.get('quote')['bidPrice'],
        ask_price=r.get('quote')['askPrice'],
        bid_volume=r.get('quote')['bidSize'],
        ask_volume=r.get('quote')['askSize'],
    )
