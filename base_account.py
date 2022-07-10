from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd
import numpy as np
import datetime
import numbers
import os
from finlab.online.enums import *

@dataclass
class Order():

  order_id: str
  stock_id: str
  action: Action
  price: numbers.Number
  quantity: numbers.Number
  status: OrderStatus
  order_condition: OrderCondition
  time: datetime.datetime
  org_order: Any = None

  @classmethod
  def from_shioaji(cls, trade):
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

    if trade.order.first_sell == 'true' and order_condition == OrderCondition.CASH:
      order_condition = OrderCondition.DAY_TRADING_SHORT

    return cls(**{
     'order_id': trade.status.id,
     'stock_id': trade.contract.code,
     'action': action,
     'price': trade.order.price if trade.status.modified_price == 0 else trade.status.modified_price,
     'quantity': trade.order.quantity,
     'status': status,
     'order_condition': order_condition,
     'time': trade.status.order_datetime,
      'org_order': trade
    })

  @classmethod
  def from_fugle(cls, order):

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

    return cls(**{
      'order_id': order['ord_no'],
      'stock_id': order['stock_no'],
      'action': Action.BUY if order['buy_sell'] == 'B' else Action.SELL,
      'price': order.get('od_price', order['avg_price']),
      'quantity': order['org_qty'] - order['mat_qty'] - order['cel_qty'],
      'status': status,
      'order_condition': order_condition,
      'time': datetime.datetime.strptime(order['ord_date'] + order['ord_time'], '%Y%m%d%H%M%S%f'),
      'org_order': order
    })

@dataclass
class Stock():

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
    return {a:getattr(self, a) for a in Stock.attrs}

  @classmethod
  def from_shioaji(cls, snapshot):
    d = snapshot
    return cls(stock_id=d.code, open=d.open, high=d.high, low=d.low, close=d.close,
        bid_price=d.buy_price, ask_price=d.sell_price, bid_volume=d.buy_volume, ask_volume=d.sell_volume)

  @classmethod
  def from_fugle(cls, json_response):
    r = json_response
    bids = r['data']['quote']['order']['bids']
    asks = r['data']['quote']['order']['asks']
    return cls(
      stock_id=r['data']['info']['symbolId'],
      high=r['data']['quote']['priceHigh']['price'],
      low=r['data']['quote']['priceLow']['price'],
      close=r['data']['quote']['trade']['price'],
      open=r['data']['quote']['priceOpen']['price'],
      bid_price=bids[0]['price'] if bids else np.nan,
      ask_price=asks[0]['price'] if asks else np.nan,
      bid_volume=bids[0]['volume'] if bids else np.nan,
      ask_volume=asks[0]['volume'] if asks else np.nan,
    )


class Account(ABC):

  @abstractmethod
  def create_order(self, action, stock_id, quantity, price=None, force=False, wait_for_best_price=False):
    pass

  @abstractmethod
  def update_order(self, order_id, price=None, quantity=None):
    pass

  @abstractmethod
  def cancel_order(self, order_id):
    pass

  @abstractmethod
  def get_orders(self):
    pass

  @abstractmethod
  def get_stocks(self, stock_ids):
    pass

  @abstractmethod
  def get_position(self):
    pass

  @abstractmethod
  def get_total_balance():
    pass

