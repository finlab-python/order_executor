import sys, os
sys.path.append(os.getcwd())

from base_account import Action
from order_executor import OrderExecutor, Position
from enums import OrderCondition, OrderStatus
import unittest
import time

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

  time.sleep(20)
  oe = OrderExecutor(Position({sid1: q2330, sid2: q1101}), account=fa)
  check_order_executor(self, oe)

  if odd_lot:
    q2330 = 2.1
    q1101 = -1.1
  else:
    q2330 = 2
    q1101 = -1

  time.sleep(20)
  oe = OrderExecutor(Position({sid1: q2330, sid2: q1101}, day_trading_short=True), account=fa)
  check_order_executor(self, oe)

  time.sleep(20)
  oe = OrderExecutor(Position({sid1: q2330, sid2: q1101}, day_trading_short=True), account=fa)
  check_order_executor(self, oe, market_order=True)


class TestSinopacAccount(unittest.TestCase):

    def test_sinopac_account(self):
      from sinopac_account import SinopacAccount
      acc = SinopacAccount()
      test_account(self, acc, odd_lot=True)

    def test_fugle_account(self):
      from fugle_account import FugleAccount
      acc = FugleAccount()
      test_account(self, acc, odd_lot=True)

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
        from fugle_account import calculate_price_with_extra_bid, Action
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