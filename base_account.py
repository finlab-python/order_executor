from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd
import numpy as np
import datetime
import numbers
import os
from finlab.online.enums import *
from finlab.online.order_executor import Position


@dataclass
class Order():

    """
    Order status

    委託單的狀態

    Attributes:
        order_id (str): 委託單的 id，與券商 API 所提供的 id 一致
        stock_id (str): 股票代號 ex: '2330'
        action (Action): 買賣方向，通常為 'BUY' 或是 'SELL'
        price (numbers.Number): 股票買賣的價格(限價單)
        quantity (numbers.Number): 委託股票的總數量（張數），允許小數點
        filled_quantity (numbers.Number): 以成交股票的數量（張數），允許小數點
        status (OrderStatus): 委託狀態，可以設定為：'NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCEL'
        time (datetime.datetime): 委託時間
        org_order (Any = None): 券商所提供的委託物件格式
    """

    order_id: str
    stock_id: str
    action: Action
    price: numbers.Number
    quantity: numbers.Number
    filled_quantity: numbers.Number
    status: OrderStatus
    order_condition: OrderCondition
    time: datetime.datetime
    org_order: Any = None

    @classmethod
    def from_shioaji(cls, trade):
        """將 shioaji package 的委託單轉換成 finlab 格式"""
        if trade.order.action == 'Buy':
            action = Action.BUY
        elif trade.order.action == 'Sell':
            action = Action.SELL
        else:
            raise Exception('trader order action should be "Buy" or "Sell"')

        status = {
            'PendingSubmit': OrderStatus.NEW,
            'PreSubmitted': OrderStatus.NEW,
            'Submitted': OrderStatus.NEW,
            'Failed': OrderStatus.CANCEL,
            'Cancelled': OrderStatus.CANCEL,
            'Filled': OrderStatus.FILLED,
            'Filling': OrderStatus.PARTIALLY_FILLED,
            'PartFilled': OrderStatus.PARTIALLY_FILLED,
        }[trade.status.status]

        order_condition = {
            'Cash': OrderCondition.CASH,
            'MarginTrading': OrderCondition.MARGIN_TRADING,
            'ShortSelling': OrderCondition.SHORT_SELLING,
        }[trade.order.order_cond]

        # calculate quantity
        # calculate filled quantity
        quantity = trade.order.quantity
        filled_quantity = trade.status.deal_quantity

        if trade.order.order_lot == 'IntradayOdd':
            quantity /= 1000

        # calculate order condition
        if trade.order.first_sell == 'true' and order_condition == OrderCondition.CASH:
            order_condition = OrderCondition.DAY_TRADING_SHORT

        return cls(**{
            'order_id': trade.status.id,
            'stock_id': trade.contract.code,
            'action': action,
            'price': trade.order.price if trade.status.modified_price == 0 else trade.status.modified_price,
            'quantity': quantity,
            'filled_quantity': filled_quantity,
            'status': status,
            'order_condition': order_condition,
            'time': trade.status.order_datetime,
            'org_order': trade
        })

    @classmethod
    def from_fugle(cls, order):
        """將 fugle package 的委託單轉換成 finlab 格式"""

        status = OrderStatus.NEW
        if order['mat_qty'] + order['cel_qty'] > 0:
            status = OrderStatus.PARTIALLY_FILLED
        if order['org_qty'] - order['mat_qty'] - order['cel_qty'] == 0:
            status = OrderStatus.FILLED
        if order['cel_qty'] == order['org_qty'] or order['err_code'] != '00000000':
            status = OrderStatus.CANCEL

        order_condition = {
            '0': OrderCondition.CASH,
            '3': OrderCondition.MARGIN_TRADING,
            '4': OrderCondition.SHORT_SELLING,
            '9': OrderCondition.DAY_TRADING_LONG,
            'A': OrderCondition.DAY_TRADING_SHORT,
        }[order['trade']]

        filled_quantity = order['mat_qty']

        order_id = order['ord_no']
        if order_id == '':
            order_id = order['pre_ord_no']

        return cls(**{
            'order_id': order_id,
            'stock_id': order['stock_no'],
            'action': Action.BUY if order['buy_sell'] == 'B' else Action.SELL,
            'price': order.get('od_price', order['avg_price']),
            'quantity': order['org_qty'],
            'filled_quantity': filled_quantity,
            'status': status,
            'order_condition': order_condition,
            'time': datetime.datetime.strptime(order['ord_date'] + order['ord_time'], '%Y%m%d%H%M%S%f'),
            'org_order': order
        })


@dataclass
class Stock():

    """
    Stock

    即時股票資料

    Attributes:
        stock_id (str): 股票代號
        open (numbers.Number): 開盤價
        high (numbers.Number): 最高價
        low (numbers.Number): 最低價
        close (numbers.Number): 收盤價
        bid_price (numbers.Number): 買方第一檔價格
        bid_volume (numbers.Number): 買方第一檔量
        ask_price (numbers.Number): 賣方第一檔價格
        ask_volume (numbers.Number: 賣方第一檔量
    """

    stock_id: str
    open: numbers.Number
    high: numbers.Number
    low: numbers.Number
    close: numbers.Number
    bid_price: numbers.Number
    bid_volume: numbers.Number
    ask_price: numbers.Number
    ask_volume: numbers.Number

    def to_dict(self):
        return {a: getattr(self, a) for a in Stock.attrs}

    @classmethod
    def from_shioaji(cls, snapshot):
        """將 shioaji 股價行情轉換成 finlab 格式"""
        d = snapshot
        return cls(stock_id=d.code, open=d.open, high=d.high, low=d.low, close=d.close,
                   bid_price=d.buy_price, ask_price=d.sell_price, bid_volume=d.buy_volume, ask_volume=d.sell_volume)

    @classmethod
    def from_fugle(cls, json_response):
        """將 fugle 股價行情轉換成 finlab 格式"""
        r = json_response

        if 'data' not in r:
            raise Exception('Cannot parse fugle quote data' + str(r))

        bids = r['data']['quote']['order']['bids']
        asks = r['data']['quote']['order']['asks']
        has_volume = 'trade' in r['data']['quote']
        return cls(
            stock_id=r['data']['info']['symbolId'],
            high=r['data']['quote']['priceHigh']['price'] if has_volume else 0,
            low=r['data']['quote']['priceLow']['price'] if has_volume else 0,
            close=r['data']['quote']['trade']['price'] if has_volume else 0,
            open=r['data']['quote']['priceOpen']['price'] if has_volume else 0,
            bid_price=bids[0]['price'] if bids else np.nan,
            ask_price=asks[0]['price'] if asks else np.nan,
            bid_volume=bids[0]['volume'] if bids else np.nan,
            ask_volume=asks[0]['volume'] if asks else np.nan,
        )


class Account(ABC):
    """股票帳戶的 abstract class
    可以繼承此 Account，來實做券商的帳戶買賣動作，目前已經實做 SinopacAccount (永豐證券) 以及 FugleAccount (玉山富果)，來進行交易。可以用以下方式建構物件並用來交易：

    永豐證券
    ```py
    import os
    from finlab.online.sinopac_account import SinopacAccount

    os.environ['SHIOAJI_ACCOUNT']= '永豐證券帳號'
    os.environ['SHIOAJI_PASSWORD']= '永豐證券密碼'
    os.environ['SHIOAJI_CERT_PATH']= '永豐證券憑證路徑'
    os.environ['SHIOAJI_CERT_PASSWORD'] = '永豐證券憑證密碼' # 預設與身份證同

    acc = SinopacAccount()
    ```
    玉山富果:
    ```py
    from finlab.online.fugle_account import FugleAccount
    import os
    os.environ['FUGLE_CONFIG_PATH'] = '玉山富果交易設定檔(config.ini.example)路徑'
    os.environ['FUGLE_MARKET_API_KEY'] = '玉山富果的行情API Token'

    acc = FugleAccount()
    ```

    """

    @abstractmethod
    def create_order(self, action, stock_id, quantity, price=None, force=False, wait_for_best_price=False):
        """產生新的委託單

        Attributes:
            action (Action): 買賣方向，通常為 'BUY' 或是 'SELL'
            stock_id (str): 股票代號 ex: '2330'
            quantity (numbers.Number): 委託股票的總數量（張數），允許小數點
            price (numbers.Number, optional): 股票買賣的價格(限價單)
            force (bool): 是否用最差之價格（長跌停）強制成交?
              當成交量足夠時，可以比較快成交，然而當成交量低時，容易有大的滑價
            wait_for_best_price (bool): 是否用最佳之價格（長跌停），無限時間等待？當今天要出場時，可以開啟等漲停價來購買，當今天要買入時，可以掛跌停價等待買入時機。
        """
        pass

    @abstractmethod
    def update_order(self, order_id, price=None, quantity=None):
        """產生新的委託單

        Attributes:
            order_id (str): 券商所提供的委託單 ID
            price (numbers.Number, optional): 更新的限價
            quantity (numbers.Number, optional): 更新的待成交量
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id):
        """刪除委託單

        Attributes:
            order_id (str): 券商所提供的委託單 ID
        """
        pass

    @abstractmethod
    def get_orders(self):
        """拿到現在所有委託單
        """
        pass

    @abstractmethod
    def get_stocks(self, stock_ids):
        """拿到現在股票報價
        Attributes:
            stock_ids (`list` of `str`): 一次拿取所有股票的報價，ex: ['1101', '2330']
        """
        pass

    @abstractmethod
    def get_position(self):
        """拿到當前帳戶的股票部位"""
        pass

    @abstractmethod
    def get_total_balance():
        """拿到當前帳戶的股票部位淨值"""
        pass

    def sep_odd_lot_order(self):
        return True

    def get_price(self, stock_ids):

        s = self.get_stocks(stock_ids)

        price = {pname: s[pname].close for pname in s}

        for sid, p in price.items():
            if p == 0:
                bid_price = s[sid].bid_price if s[sid].bid_price != 0 else s[sid].ask_price
                ask_price = s[sid].ask_price if s[sid].ask_price != 0 else s[sid].bid_price
                price[sid] = (bid_price + ask_price)/2

            if price[sid] == 0:
                raise Exception(
                    f"Stock {sid} has no price to reference. Use latest close of previous trading day")

        return price
