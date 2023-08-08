import sys, os
sys.path.append(os.getcwd())

from base_account import Action
from order_executor import OrderExecutor, Position
from enums import OrderCondition, OrderStatus
import unittest
import time
from finlab import data
from finlab.backtest import sim

def check_order_executor(self, oe, **args_for_creating_orders):
  # check order executor results
  view_orders = oe.create_orders(view_only=True)

  oe.cancel_orders()
  time.sleep(11)
  oe.create_orders(**args_for_creating_orders)
  orders = oe.account.get_orders()

  stock_orders = {o['stock_id']: o for o in view_orders}
  stock_quantity = {o.stock_id: 0 for oid, o in orders.items()}


  for oid, o in orders.items():
    if o.status == OrderStatus.CANCEL\
        or o.stock_id not in stock_orders\
        or o.status == OrderStatus.FILLED:
        continue

    # get stock id
    sid = o.stock_id

    # check order condition and action
    expect_action = Action.BUY if stock_orders[sid]['quantity'] > 0 else Action.SELL

    stock_quantity[sid] += o.quantity
    self.assertEqual(o.action, expect_action)
    self.assertEqual(o.order_condition, stock_orders[sid]['order_condition'])

  for sid, q in stock_quantity.items():
    if q != 0:
      self.assertEqual(round(q, 4), abs(stock_orders[sid]['quantity']))

  oe.cancel_orders()


def test_account(self, fa, odd_lot=False):


  sid1 = '4183'
  sid2 = '1101'

  if odd_lot:
    q2330 = 2.1
    q1101 = 1.1
  else:
    q2330 = 2
    q1101 = 1

  time.sleep(11)
  oe = OrderExecutor(Position({sid1: q2330, sid2: q1101}), account=fa)
  check_order_executor(self, oe)

  if odd_lot:
    q2330 = 2.1
    q1101 = -1.1
  else:
    q2330 = 2
    q1101 = -1

  time.sleep(11)
  oe = OrderExecutor(Position({sid1: q2330, sid2: q1101}, day_trading_short=True), account=fa)
  check_order_executor(self, oe)

  time.sleep(11)
  oe = OrderExecutor(Position({sid1: q2330, sid2: q1101}, day_trading_short=True), account=fa)
  check_order_executor(self, oe, market_order=True)

def test_update_price(self, fa, odd_lot=False):
  sid1 = '6016'
  if odd_lot:
    q6016 = 0.1
  else:
    q6016 = 2
  oe = OrderExecutor(Position({sid1: q6016}), account=fa)
  view_orders = oe.create_orders(view_only=True)
  time.sleep(11)
  oe.create_orders()
  orders = oe.account.get_orders()
  
  # get first order ids
  oids = []
  for oid, o in orders.items():
    if o.status == OrderStatus.NEW:
        oids.append(oid)

  time.sleep(11)
  oe.update_order_price(extra_bid_pct=0.05)

  # check first order is canceled
  orders_new = oe.account.get_orders()
  for oid in oids:
      expect_action = OrderStatus.CANCEL
      self.assertEqual(orders_new[oid].status, expect_action)

  # check second order condition
  stock_orders = {o['stock_id']: o for o in view_orders}
  stock_quantity = {o.stock_id: 0 for oid, o in orders_new.items()}
  for oid, o in orders_new.items():
    if o.status == OrderStatus.CANCEL\
        or o.stock_id not in stock_orders\
        or o.status == OrderStatus.FILLED:
        continue

    stock_quantity[sid1] += o.quantity
    self.assertEqual(o.order_condition, stock_orders[sid1]['order_condition'])
  for sid, q in stock_quantity.items():
    if q != 0:
      self.assertEqual(round(q, 4), abs(stock_orders[sid]['quantity']))
      
  oe.cancel_orders()

class TestSinopacAccount(unittest.TestCase):

    def test_sinopac_account(self):
      from sinopac_account import SinopacAccount
      acc = SinopacAccount()
      test_account(self, acc, odd_lot=False)
      test_account(self, acc, odd_lot=True)
      test_update_price(self, acc, odd_lot=True)

    def test_fugle_account(self):
      from fugle_account import FugleAccount
      acc = FugleAccount()
      test_account(self, acc, odd_lot=False)
      test_account(self, acc, odd_lot=True)
      test_update_price(self, acc, odd_lot=True)

    def test_position(self):

      # position add
      pos = Position({"2330": 1}) + Position({"2330": 1, "1101": 1})
      for o in pos.position:
        if o['stock_id'] == "2330":
          assert o['quantity'] == 2
        if o['stock_id'] == "1101":
          assert o['quantity'] == 1


      # position sub
      pos = Position({"2330": 2}) - Position({"2330": 1, "1101": 1})
      for o in pos.position:
        if o['stock_id'] == "2330":
          assert o['quantity'] == 1
        if o['stock_id'] == "1101":
          assert o['quantity'] == -1

      # position fall_back_cash

      pos = Position({"2330": 2}, day_trading_long=True)
      pos.fall_back_cash()
      assert pos.position[0]['stock_id'] == '2330'
      assert pos.position[0]['quantity'] == 2
      assert pos.position[0]['order_condition'] == OrderCondition.CASH

class CalculatePriceWithExtraBidTest(unittest.TestCase):
    def test_calculate_price_with_extra_bid(self):
        from order_executor import calculate_price_with_extra_bid
        test_data = {
            'test_1': {'price': 5.2, 'extra_bid_pct': 0.06, 'action': Action.BUY, 'expected_result': 5.51},
            'test_2': {'price': 7.4, 'extra_bid_pct': 0.02, 'action': Action.SELL, 'expected_result': 7.26},
            'test_3': {'price': 25.65, 'extra_bid_pct': 0.1, 'action': Action.BUY, 'expected_result': 28.20},
            'test_4': {'price': 11.05, 'extra_bid_pct': 0.1, 'action': Action.SELL, 'expected_result': 9.95},
            'test_5': {'price': 87.0, 'extra_bid_pct': 0.04, 'action': Action.BUY, 'expected_result': 90.4},
            'test_6': {'price': 73.0, 'extra_bid_pct': 0.06, 'action': Action.SELL, 'expected_result': 68.7},
            'test_7': {'price': 234.0, 'extra_bid_pct': 0.08, 'action': Action.BUY, 'expected_result': 252.5},
            'test_8': {'price': 234.0, 'extra_bid_pct': 0.08, 'action': Action.SELL, 'expected_result': 215.5},
            'test_9': {'price': 650.0, 'extra_bid_pct': 0.05, 'action': Action.BUY, 'expected_result': 682},
            'test_10': {'price': 756.0, 'extra_bid_pct': 0.055, 'action': Action.SELL, 'expected_result': 715},
            'test_11': {'price': 1990.0, 'extra_bid_pct': 0.035, 'action': Action.BUY, 'expected_result': 2055},
            'test_12': {'price': 1455.0, 'extra_bid_pct': 0.088, 'action': Action.SELL, 'expected_result': 1330},
        }

        for test_name, test_case in test_data.items():
            price = test_case['price']
            extra_bid_pct = test_case['extra_bid_pct']
            action = test_case['action']
            expected_result = test_case['expected_result']

            with self.subTest(test_name=test_name):
                result = calculate_price_with_extra_bid(price, extra_bid_pct, action)
                self.assertEqual(result, expected_result)

    def test_extra_bid_and_up_down_limit(self):
      from order_executor import calculate_price_with_extra_bid
      action = Action.BUY
      last_close = 68
      now_price = 73
      extra_bid_pct = 0.08
      up_down_limit = calculate_price_with_extra_bid(last_close, 0.1, action)
      price = calculate_price_with_extra_bid(now_price, extra_bid_pct, action)
      if (action == Action.BUY and price > up_down_limit) or (action == Action.SELL and price < up_down_limit):
        price = up_down_limit
      self.assertEqual(price, 74.8)

def check_action_and_position(report):
  report.actions.index = report.actions.index.map(lambda x:x[:4])
  position = Position.from_report(report, 50000, odd_lot=True).position
  check_sl_tp = report.actions.isin(['sl_', 'tp_','sl', 'tp'])
  for p in position:
    assert p['stock_id'] not in check_sl_tp[check_sl_tp].index

class TestPositionFromReport(unittest.TestCase):
    def test_strategy1(self):
      close = data.get("price:收盤價")
      vol = data.get("price:成交股數")
      vol_ma = vol.average(10)
      rev = data.get('monthly_revenue:當月營收')
      rev_year_growth = data.get('monthly_revenue:去年同月增減(%)')
      rev_month_growth = data.get('monthly_revenue:上月比較增減(%)')
      cond1 = (close == close.rolling(250).max())
      cond2 = ~(rev_year_growth < -10).sustain(3) 
      cond3 = ~(rev_year_growth > 60).sustain(12,8)
      cond4 = ((rev.rolling(12).min())/(rev) < 0.8).sustain(3)
      cond5 = (rev_month_growth > -40).sustain(3)
      cond6 = vol_ma > 200*1000
      buy = cond1 & cond2  & cond3 & cond4 & cond5 & cond6
      buy = vol_ma*buy
      buy = buy[buy>0]
      buy = buy.is_smallest(5)
      report = sim(buy, resample="M", upload=False, position_limit=1/3, fee_ratio=1.425/1000/3, stop_loss=0.08, trade_at_price='open', name='藏獒')
      check_action_and_position(report)

    def test_strategy2(self):
      close = data.get('price:收盤價')
      vol = data.get('price:成交股數')
      rev = data.get('monthly_revenue:當月營收')
      rev_yoy_growth = data.get('monthly_revenue:去年同月增減(%)')
      rev_ma = rev.average(2)
      condition1 = rev_ma == rev_ma.rolling(12, min_periods=6).max()
      condition2 = (close == close.rolling(200).max()).sustain(5,2)
      condition3 = vol.average(5) > 500*1000
      conditions = condition1 & condition2 & condition3
      position= rev_yoy_growth*conditions
      position = position[position>0].is_largest(10).reindex(rev.index_str_to_date().index, method='ffill')
      report = sim(position, upload=False, stop_loss=0.2, take_profit=0.8, position_limit=0.25, fee_ratio=1.425/1000*0.3, name="營收股價雙渦輪")
      check_action_and_position(report)
