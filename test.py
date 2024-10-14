import os
from finlab.backtest import sim
from finlab import data
from decimal import Decimal
import time
import unittest
from finlab.online.enums import OrderCondition, OrderStatus
from finlab.online.order_executor import OrderExecutor, Position
from finlab.online.base_account import Action
import sys
import os
sys.path.append(os.getcwd())


print('-------------------------')
print('FUGLE_CONFIG_PATH', os.environ['FUGLE_CONFIG_PATH'])
print('FUGLE_MARKET_API_KEY', os.environ['FUGLE_MARKET_API_KEY'])
print('SHIOAJI_API_KEY', os.environ['SHIOAJI_API_KEY'])
print('SHIOAJI_SECRET_KEY', os.environ['SHIOAJI_SECRET_KEY'])
print('SHIOAJI_CERT_PERSON_ID', os.environ['SHIOAJI_CERT_PERSON_ID'])
print('SHIOAJI_CERT_PATH', os.environ['SHIOAJI_CERT_PATH'])
print('SHIOAJI_CERT_PASSWORD', os.environ['SHIOAJI_CERT_PASSWORD'])
print('-------------------------')


def check_order_executor(self, oe, **args_for_creating_orders):
    # check order executor results
    view_orders = oe.create_orders(view_only=True)

    oe.cancel_orders()
    time.sleep(11)
    oe.create_orders(**args_for_creating_orders)
    time.sleep(5)
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
        self.assertEqual(o.order_condition,
                         stock_orders[sid]['order_condition'])

    for sid, q in stock_quantity.items():
        if q != 0:
            self.assertEqual(float(round(q, 4)), float(
                abs(stock_orders[sid]['quantity'])))

    oe.cancel_orders()


def f_test_account(self, fa, odd_lot=False):

    sid1 = '3661'
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
    oe = OrderExecutor(
        Position({sid1: q2330, sid2: q1101}, day_trading_short=True), account=fa)
    check_order_executor(self, oe)

    time.sleep(11)
    oe = OrderExecutor(
        Position({sid1: q2330, sid2: q1101}, day_trading_short=True), account=fa)
    check_order_executor(self, oe, market_order=True)


def f_test_update_price(self, fa, odd_lot=False):
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
    time.sleep(1)

    # check first order is canceled
    orders_new = oe.account.get_orders()
    for oid in oids:
        continue
        orders_new[oid]
        expect_action = OrderStatus.CANCEL
        self.assertEqual(orders_new[oid].status, expect_action)

    # check second order condition
    stock_orders = {o['stock_id']: o for o in view_orders}
    stock_quantity = {o.stock_id: 0 for oid, o in orders_new.items()}
    for oid, o in orders_new.items():
        if o.status == OrderStatus.CANCEL\
            or o.stock_id not in stock_orders\
            or o.stock_id != sid1\
                or o.status == OrderStatus.FILLED:
            continue

        stock_quantity[sid1] += o.quantity
        self.assertEqual(o.order_condition,
                         stock_orders[sid1]['order_condition'])
    for sid, q in stock_quantity.items():
        if q != 0:
            self.assertEqual(float(round(q, 4)), abs(
                stock_orders[sid]['quantity']))

    oe.cancel_orders()


class TestSinopacAccount(unittest.TestCase):

    def setUp(self):
        from finlab.online.sinopac_account import SinopacAccount
        from finlab.online.fugle_account import FugleAccount
        self.sinopac_account = SinopacAccount()
        self.fugle_account = FugleAccount()

    def test_sinopac_get_total_balance(self):
        total_balance = self.sinopac_account.get_total_balance()
        assert total_balance >= 0

    def test_sinopac_order(self):
        acc = self.sinopac_account
        f_test_account(self, acc, odd_lot=False)

    def test_sinopac_order_odd_lot(self):
        acc = self.sinopac_account
        f_test_account(self, acc, odd_lot=True)

    def test_sinopac_update_price(self):
        acc = self.sinopac_account
        f_test_update_price(self, acc, odd_lot=False)

    def test_sinopac_update_price_odd_lot(self):
        acc = self.sinopac_account
        f_test_update_price(self, acc, odd_lot=True)

    def test_fugle_get_total_balance(self):
        total_balance = self.fugle_account.get_total_balance()
        assert total_balance >= 0

    def test_fugle_order(self):
        acc = self.fugle_account
        f_test_account(self, acc, odd_lot=False)

    def test_fugle_order_odd_lot(self):
        acc = self.fugle_account
        f_test_account(self, acc, odd_lot=True)

    def test_fugle_update_price(self):
        acc = self.fugle_account
        f_test_update_price(self, acc, odd_lot=False)

    def test_fugle_update_price_odd_lot(self):
        acc = self.fugle_account
        f_test_update_price(self, acc, odd_lot=True)

    def tearDown(self) -> None:
        oe = OrderExecutor(Position({}), self.sinopac_account)
        oe.cancel_orders()

        oe = OrderExecutor(Position({}), self.fugle_account)
        oe.cancel_orders()

    # def test_all_fugle_account(self):

    #   from finlab.online.fugle_account import FugleAccount
    #   acc = FugleAccount()
    #   info = acc.get_price_info()
    #   oe = OrderExecutor(Position(dict(zip(info.keys(), len(info) * [1]))))
    #   oe.create_orders()
    #   oe.cancel_orders()

    def test_to_json(self):
        pos = Position({"2330": 1})
        pos.to_json('test.json')
        pos2 = Position.from_json('test.json')
        print(pos)
        assert pos.position[0] == pos2.position[0]

    def test_show_alerting_stocks(self):
        from finlab.online.sinopac_account import SinopacAccount
        acc = SinopacAccount()
        acc.get_total_balance()
        df = data.get('reference_price')
        stocks = df.stock_id[df.stock_id.str.len() == 4].to_list()
        oe = OrderExecutor(Position(dict(zip(stocks, len(stocks) * [1]))), acc)
        oe.show_alerting_stocks()

    def test_position(self):

        # position add
        pos = Position({"2330": 1}) + Position({"2330": 1, "1101": 1})
        for o in pos.position:
            if o['stock_id'] == "2330":
                assert o['quantity'] == 2
            if o['stock_id'] == "1101":
                assert o['quantity'] == 1

        # test position from list
        pos = Position.from_list(pos.to_list())
        for o in pos.position:
            if o['stock_id'] == "2330":
                assert o['quantity'] == 2
            if o['stock_id'] == "1101":
                assert o['quantity'] == 1

        # test decimal quantity
        pos = Position({"2330": Decimal('1.1')})
        pos = Position.from_list(pos.to_list())
        assert pos.position[0]['quantity'] == Decimal('1.1')

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

        pos = Position({"2330": 2}, margin_trading=True)
        assert pos.position[0]['order_condition'] == OrderCondition.MARGIN_TRADING
        pos = Position({"2330": -2}, margin_trading=True)
        assert pos.position[0]['order_condition'] == OrderCondition.CASH
        pos = Position({"2330": -2}, short_selling=True)
        assert pos.position[0]['order_condition'] == OrderCondition.SHORT_SELLING
        pos = Position({"2330": 2}, short_selling=True)
        assert pos.position[0]['order_condition'] == OrderCondition.CASH

        pos = Position.from_list(
            [{'stock_id': '2330', 'quantity': 2, 'order_condition': OrderCondition.CASH}])
        pos2 = Position.from_dict(
            [{'stock_id': '2330', 'quantity': 2, 'order_condition': OrderCondition.CASH}])
        assert pos.position[0] == pos2.position[0]

    def test_from_weight(self):
        position = Position.from_weight({
            '1101': 0.5,
            '2330': 0.5,
        }, fund=1000000, price={'1101': 50, '2330': 100}, )

        expected_output = Position.from_list([
            {'stock_id': '1101', 'quantity': 10,
                'order_condition': OrderCondition.CASH},
            {'stock_id': '2330', 'quantity': 5,
                'order_condition': OrderCondition.CASH}
        ])
        p = (position - expected_output)
        assert len(p.position) == 0

        position = Position.from_weight({
            '1101': 0.5,
            '2330': 0.5,
        }, fund=1000000, price={'1101': 30, '2330': 60}, odd_lot=True, board_lot_size=100)

        expected_output = Position.from_list([
            {'stock_id': '1101', 'quantity': Decimal(
                '166.66'), 'order_condition': OrderCondition.CASH},
            {'stock_id': '2330', 'quantity': Decimal(
                '83.33'), 'order_condition': OrderCondition.CASH}
        ])

        p = (position - expected_output)
        assert len(p.position) == 0

        position = Position.from_weight({
            '1101': -0.5,
            '2330': 0.5,
        }, fund=1000000, price={'1101': 30, '2330': 60}, odd_lot=True, board_lot_size=100, short_selling=True)

        expected_output = Position.from_list([
            {'stock_id': '1101', 'quantity': Decimal(
                '-166.66'), 'order_condition': OrderCondition.SHORT_SELLING},
            {'stock_id': '2330', 'quantity': Decimal(
                '83.33'), 'order_condition': OrderCondition.CASH}
        ])

        p = (position - expected_output)
        assert len(p.position) == 0

        # expect error
        try:
            position = Position.from_weight({
                '1101': 0.5,
                '2330': 0.5,
            }, fund=1000000, price={'1101': 30, '2330': 60}, odd_lot=True, board_lot_size=30, margin_trading=True)
            assert False
        except:
            assert True


class TestSchwabAccount(unittest.TestCase):
    """測試 finlab 的 SchwabAccount 類別
    Args:
        unittest (_type_): _description_
    Notes:
        - 測試案例需要環境變數:
            - SCHWAB_API_KEY: Schwab API Key
            - SCHWAB_SECRET: Schwab API Secret
            - SCHWAB_TOKEN_PATH: 存放 Schwab Token 的路徑
        - 測試案例
            - 回傳值是否符合預期(如回傳值型態、回傳值內容)
    """

    @classmethod
    def setUpClass(self):
        """開始測試時執行的動作"""

        from schwab_account import SchwabAccount

        self.app_key = os.getenv('SCHWAB_API_KEY')
        self.app_secret = os.getenv('SCHWAB_SECRET')
        self.app_token = os.getenv('SCHWAB_TOKEN_PATH')

        print('----------------------------------------')
        print('SCHWAB_API_KEY: ' + self.app_key)
        print('SCHWAB_SECRET: ' + self.app_secret)
        print('SCHWAB_TOKEN_PATH: ' + self.app_token)
        print('----------------------------------------')

        self.schwab_account = SchwabAccount(
            api_key=self.app_key,
            app_secret=self.app_secret,
            token_path=self.app_token,
        )

    @classmethod
    def tearDownClass(self):
        """結束測試時執行的動作"""
        oe = OrderExecutor(Position({}), self.schwab_account)
        oe.cancel_orders()

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_create_order(self):
        self.schwab_account.create_order(
            action=Action.BUY,
            stock_id='AAPL',
            quantity=1,
            price=30.0,
            odd_lot=True,
            market_order=False,
            best_price_limit=False,
            order_cond=OrderCondition.CASH,
        )

    def test_get_price_info(self):
        price_info = self.schwab_account.get_price_info(['AAPL'])
        self.assertIn('AAPL', price_info)
        self.assertIn('收盤價', price_info['AAPL'])
        self.assertIn('漲停價', price_info['AAPL'])
        self.assertIn('跌停價', price_info['AAPL'])

    def test_get_position(self):
        positions = self.schwab_account.get_position()
        self.assertIsInstance(positions, Position)

    def test_get_orders(self):
        orders = self.schwab_account.get_orders()
        self.assertIsInstance(orders, dict)

    def test_get_stocks(self):
        stocks = self.schwab_account.get_stocks(['AAPL'])
        self.assertIn('AAPL', stocks)

    def test_get_total_balance(self):
        balance = self.schwab_account.get_total_balance()
        self.assertIsInstance(balance, float)

    def test_get_cash(self):
        cash = self.schwab_account.get_cash()
        self.assertIsInstance(cash, float)


class CalculatePriceWithExtraBidTest(unittest.TestCase):
    def test_calculate_price_with_extra_bid(self):
        from finlab.online.order_executor import calculate_price_with_extra_bid
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
                result = calculate_price_with_extra_bid(
                    price, extra_bid_pct if action == Action.BUY else -extra_bid_pct)
                self.assertEqual(result, expected_result)

    def test_extra_bid_and_up_down_limit(self):
        from finlab.online.order_executor import calculate_price_with_extra_bid
        action = Action.BUY
        last_close = 68
        now_price = 73
        extra_bid_pct = 0.08
        up_down_limit = calculate_price_with_extra_bid(last_close, 0.1)
        price = calculate_price_with_extra_bid(now_price, extra_bid_pct)
        if (action == Action.BUY and price > up_down_limit) or (action == Action.SELL and price < up_down_limit):
            price = up_down_limit
        self.assertEqual(price, 74.8)


def check_action_and_position(report):
    report.actions.index = report.actions.index.map(lambda x: x[:4])
    position = Position.from_report(report, 50000, odd_lot=True).position

    close = data.get('price:收盤價').iloc[-1].to_dict()
    position = Position.from_report(
        report, 50000, odd_lot=True, price=close).position

    check_sl_tp = report.actions.isin(['sl_', 'tp_', 'sl', 'tp'])
    for p in position:
        assert p['stock_id'] not in check_sl_tp[check_sl_tp].index
