from finlab.online.utils import greedy_allocation
from finlab.online.enums import *
from finlab import data
import pandas as pd
import requests
import datetime
import time


class Position():

  def __init__(self, stocks, margin_trading=False, short_selling=False, day_trading_long=False, day_trading_short=False):
    assert margin_trading + day_trading_long <= 1
    assert short_selling + day_trading_short <= 1

    long_order_condition = OrderCondition.CASH
    short_order_condition = OrderCondition.CASH

    if margin_trading:
      long_order_condition = OrderCondition.MARGIN_TRADING
    elif day_trading_long:
      long_order_condition = OrderCondition.DAY_TRADING_LONG

    if short_selling:
      short_order_condition = OrderCondition.SHORT_SELLING
    elif day_trading_short:
      short_order_condition = OrderCondition.DAY_TRADING_SHORT

    self.position = []
    for s, a in stocks.items():
      if a != 0:
        self.position.append({'stock_id': s, 'quantity': int(a), 'order_condition': long_order_condition if a > 0 else short_order_condition})

  @classmethod
  def from_dict(cls, position):
    ret = cls({})
    ret.position = position
    return ret

  @classmethod
  def from_report(cls, report, fund, allocation=greedy_allocation, **kwargs):
    weights = report.current_trades.next_weights
    price = data.get('price:收盤價').iloc[-1]
    stock_quantity, available_funds = allocation(weights, price*1000, fund)
    return cls(stock_quantity, **kwargs)

  def __add__(self, position):
    return self.for_each_trading_condition(self.position, position.position, "+")

  def __sub__(self, position):
    return self.for_each_trading_condition(self.position, position.position, "-")

  def for_each_trading_condition(self, p1, p2, operator):
    ret = []
    for oc in [ OrderCondition.CASH,
          OrderCondition.MARGIN_TRADING,
          OrderCondition.SHORT_SELLING,
          OrderCondition.DAY_TRADING_LONG,
          OrderCondition.DAY_TRADING_SHORT]:
      qty1 = {sobj['stock_id']: sobj['quantity'] for sobj in p1 if sobj['order_condition'] == oc}
      qty2 = {sobj['stock_id']: sobj['quantity'] for sobj in p2 if sobj['order_condition'] == oc}

      ps = self.op(qty1, qty2, operator)
      ret += [{'stock_id': sid, 'quantity': round(qty), 'order_condition': oc} for sid, qty in ps.items()]

    return Position.from_dict(ret)

  @staticmethod
  def op(position1, position2, operator):
    position1 = pd.Series(position1, dtype="float").astype(float)
    position2 = pd.Series(position2, dtype="float").astype(float)
    union_index = position1.index.union(position2.index)
    position1 = position1.reindex(union_index)
    position1.fillna(0, inplace=True)

    position2 = position2.reindex(union_index)
    position2.fillna(0, inplace=True)

    if operator == "-":
      ret = position1 - position2
    elif operator == "+":
      ret = position1 + position2

    ret = ret[ret != 0]

    return ret.to_dict()

  def fall_back_cash(self):
    pos = []
    for p in self.position:
      pos.append({
        'stock_id': p['stock_id'],
        'quantity': p['quantity'],
        'order_condition': OrderCondition.CASH if p['order_condition'] in [OrderCondition.DAY_TRADING_LONG, OrderCondition.DAY_TRADING_SHORT] else p['order_condition']
      })
    self.position = pos

  def __repr__(self):
    return str(self.position)

class OrderExecutor():

  def __init__(
      self, target_position, account=None):

    if isinstance(target_position, dict):
      target_position = Position(target_position)

    self.account = account

    # if not account.support_day_trade_condition():
    #   target_position.fall_back_cash()

    self.target_position = target_position

  @classmethod
  def from_report(
      cls, report, money, account, **kwargs):

    report_position = report.position.iloc[-1]
    report_position = report_position[report_position != 0].to_dict()

    return cls.from_weights(
      report_position, money, **kwargs)

  @classmethod
  def from_weights(
      cls, weights, money, account, **kwargs):

    stocks = account.get_stocks(list(weights.keys()))
    stock_price = {sid: s.close * 1000 for sid, s in stocks.items()}

    allocation = greedy_allocation(weights, stock_price, money)
    return cls(Position(allocation[0], **kwargs), account)

  def show_alerting_stocks(self):

    new_orders = self._calculate_new_orders()

    stock_ids = [o['stock_id'] for o in new_orders]
    stocks = self.account.get_stocks(stock_ids)
    quantity = {o['stock_id']: o['quantity'] for o in new_orders}

    res = requests.get('https://www.sinotrade.com.tw/Stock/Stock_3_8_3')
    dfs = pd.read_html(res.text)
    credit_sids = dfs[0][dfs[0]['股票代碼'].isin(stock_ids)]['股票代碼']

    res = requests.get('https://www.sinotrade.com.tw/Stock/Stock_3_8_1')
    dfs = pd.read_html(res.text)
    credit_sids = credit_sids.append(dfs[0][dfs[0]['股票代碼'].isin(stock_ids)]['股票代碼'].astype(str))
    credit_sids.name = None

    for sid in list(credit_sids.values):
      total_amount = quantity[sid]*stocks[sid].close*1000
      if quantity[sid] > 0:
        print(f"買入 {sid} {quantity[sid]:>5} 張 - 總價約 {total_amount:>15.2f}")
      else:
        print(f"賣出 {sid} {quantity[sid]:>5} 張 - 總價約 {total_amount:>15.2f}")

  def cancel_orders(self):
    orders = self.account.get_orders()
    for oid, o in orders.items():
      if o.status == OrderStatus.NEW or o.status == OrderStatus.PARTIALLY_FILLED:
        self.account.cancel_order(oid)

  def create_orders(self, market_order=False, best_price_limit=False, view_only=False):

    present_position = Position.from_dict(self.account.get_position())
    orders = (self.target_position - present_position).position

    if view_only:
      return orders

    self.cancel_orders()
    stocks = self.account.get_stocks(list({o['stock_id'] for o in orders}))

    # make orders
    for o in orders:

      if o['quantity'] == 0:
        continue

      action = Action.BUY if o['quantity'] > 0 else Action.SELL
      price = stocks[o['stock_id']].close
      if best_price_limit:
        limit = 'LOWEST' if action == Action.BUY else 'HIGHEST'
        print('execute', action, o['stock_id'], 'X', abs(o['quantity']), '@', limit, o['order_condition'])
      else:
        print('execute', action, o['stock_id'], 'X', abs(o['quantity']), '@', price, o['order_condition'])
      self.account.create_order(action=action,
                                stock_id=o['stock_id'],
                                quantity=abs(o['quantity']),
                                price=price, market_order=market_order,
                                order_cond=o['order_condition'],
                                best_price_limit=best_price_limit)

  def update_order_price(self):
    orders = self.account.get_orders()
    sids = set([o.stock_id for i, o in orders.items()])
    stocks = self.account.get_stocks(sids)

    for i, o in orders.items():
      if o.status == OrderStatus.NEW or o.status == OrderStatus.PARTIALLY_FILLED:
        self.account.update_order(i, price=stocks[o.stock_id].close)

  def schedule(self, time_period=10):

    now = datetime.datetime.now()

    # market open time
    am0900 = now.replace(hour=8, minute=59, second=0, microsecond=0)

    # market close time
    pm1430 = now.replace(hour=14, minute=29, second=0, microsecond=0)

    # order timings
    internal_timings = pd.date_range(am0900, pm1430, freq=str(time_period) + 'T')

    prev_time = datetime.datetime.now()

    first_limit_order = True

    while True:
      prev_time = now
      now = datetime.datetime.now()

      # place limit orders during 9:00 ~ 14:30
      if ((now > internal_timings) & (internal_timings > prev_time)).any():
        if first_limit_order:
          self.create_orders()
          first_limit_order = False
        else:
          self.update_orders()

      time.sleep(20)
