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
        self.position.append({'stock_id': s, 'quantity': a, 'order_condition': long_order_condition if a > 0 else short_order_condition})

  @classmethod
  def from_dict(cls, position):
    ret = cls({})
    ret.position = position
    return ret

  @classmethod
  def from_weight(cls, weights, fund, price=None, odd_lot=False, board_lot_size=1000, allocation=greedy_allocation):

    if price is None:
        price = data.get('price:收盤價').iloc[-1]

    if isinstance(price, dict):
        price = pd.Series(price)

    if isinstance(weights, dict):
        weights = pd.Series(weights)

    if odd_lot:
        allocation = greedy_allocation(weights, price, fund)[0]
        for s, q in allocation.items():
            allocation[s] = round(q) / board_lot_size
    else:
        allocation = greedy_allocation(weights, price*board_lot_size, fund)[0]

    return cls(allocation)


  @classmethod
  def from_report(cls, report, fund, **kwargs):
    weights = report.current_trades.next_weights
    return cls.from_weight(weights, fund, **kwargs)

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
      ret += [{'stock_id': sid, 'quantity': round(qty, 3), 'order_condition': oc} for sid, qty in ps.items()]

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
      self, target_position, account):

    if isinstance(target_position, dict):
      target_position = Position(target_position)

    self.account = account
    self.target_position = target_position

  def show_alerting_stocks(self):

    present_position = self.account.get_position()
    new_orders = (self.target_position - present_position).position

    stock_ids = [o['stock_id'] for o in new_orders]
    stocks = self.account.get_stocks(stock_ids)
    quantity = {o['stock_id']: o['quantity'] for o in new_orders}

    res = requests.get('https://www.sinotrade.com.tw/Stock/Stock_3_8_3')
    dfs = pd.read_html(res.text)
    credit_sids = dfs[0][dfs[0]['股票代碼'].isin(stock_ids)]['股票代碼']

    res = requests.get('https://www.sinotrade.com.tw/Stock/Stock_3_8_1')
    dfs = pd.read_html(res.text)
    credit_sids = pd.concat([credit_sids, dfs[0][dfs[0]['股票代碼'].isin(stock_ids)]['股票代碼'].astype(str)])
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

    present_position = self.account.get_position()
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

      quantity = abs(o['quantity'])
      board_lot_quantity = int(abs(quantity // 1))
      odd_lot_quantity = int(abs(round(1000 * (quantity % 1))))

      if self.account.sep_odd_lot_order():
          if odd_lot_quantity != 0:
              self.account.create_order(action=action,
                                    stock_id=o['stock_id'],
                                    quantity=odd_lot_quantity,
                                    price=price, market_order=market_order,
                                    order_cond=o['order_condition'],
                                    odd_lot=True,
                                    best_price_limit=best_price_limit)

          if board_lot_quantity != 0:
              self.account.create_order(action=action,
                                    stock_id=o['stock_id'],
                                    quantity=board_lot_quantity,
                                    price=price, market_order=market_order,
                                    order_cond=o['order_condition'],
                                    best_price_limit=best_price_limit)
      else:
          self.account.create_order(action=action,
                                stock_id=o['stock_id'],
                                quantity=quantity,
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
