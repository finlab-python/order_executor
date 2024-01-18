from configparser import ConfigParser
from fugle_trade.sdk import SDK
from fugle_trade.order import OrderObject
from fugle_trade.constant import Action as fugleAction
from fugle_trade.constant import (APCode, Trade, PriceFlag, BSFlag, Action)

from finlab.online.base_account import Account, Stock, Order
from finlab.online.enums import *
from finlab.online.order_executor import calculate_price_with_extra_bid, Position
from finlab import data

from threading import Thread
from decimal import Decimal
import numpy as np
import requests
import datetime
import logging
import math
import copy
import time
import os


class FugleAccount(Account):

    required_module = 'fugle_trade'
    module_version = '0.4.0'

    def __init__(self, config_path='./config.ini.example', market_api_key=None):

        self.check_version()
        self.market = 'tw_stock'

        self.market_api_key = market_api_key

        if 'FUGLE_CONFIG_PATH' in os.environ:
            config_path = os.environ['FUGLE_CONFIG_PATH']

        if 'FUGLE_MARKET_API_KEY' in os.environ:
            market_api_key = os.environ['FUGLE_MARKET_API_KEY']

        self.timestamp_for_get_position = datetime.datetime(2021, 1, 1)

        # 讀取設定檔
        config = ConfigParser()
        config.read(config_path)
        # 將設定檔內容寫至 SDK 中，並確認是否已設定密碼
        if not os.path.isfile(config_path):
            raise Exception('無法找到 config 檔案')

        sdk = SDK(config)
        sdk.login()
        self.sdk = sdk

        self.market_api_key = market_api_key

        self.trades = {}
        self.thread = None

    def create_order(self, action, stock_id, quantity, price=None, odd_lot=False, best_price_limit=False, market_order=False, order_cond=OrderCondition.CASH):

        if quantity <= 0:
            raise ValueError("quantity should be larger than zero")

        fugle_action = fugleAction.Buy if action == Action.BUY else fugleAction.Sell

        price_flag = PriceFlag.Limit if price else PriceFlag.Flat

        if market_order:
            price = None
            if action == Action.BUY:
                price_flag = PriceFlag.LimitUp
            elif action == Action.SELL:
                price_flag = PriceFlag.LimitDown

        elif best_price_limit:
            price = None
            if action == Action.BUY:
                price_flag = PriceFlag.LimitDown
            elif action == Action.SELL:
                price_flag = PriceFlag.LimitUp


        order_cond = {
            OrderCondition.CASH: Trade.Cash,
            OrderCondition.MARGIN_TRADING: Trade.Margin,
            OrderCondition.SHORT_SELLING: Trade.Short,
            # OrderCondition.DAY_TRADING_LONG: Trade.DayTrading,
            OrderCondition.DAY_TRADING_SHORT: Trade.DayTradingSell,
        }[order_cond]

        ap_code = APCode.IntradayOdd if odd_lot else APCode.Common
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        if datetime.time(13, 40) < datetime.time(now.hour, now.minute) and datetime.time(now.hour, now.minute) < datetime.time(14, 30) and odd_lot:
            ap_code = APCode.Odd
        if datetime.time(14, 00) < datetime.time(now.hour, now.minute) and datetime.time(now.hour, now.minute) < datetime.time(14, 30) and not odd_lot:
            ap_code = APCode.AfterMarket
            price_flag = PriceFlag.Limit

        params = dict(
            buy_sell=fugle_action,
            stock_no=stock_id,
            quantity=quantity,
            ap_code=ap_code,
            price_flag=price_flag,
            trade=order_cond,
            price=price
        )

        order = OrderObject(**params)

        try:
            ret = self.sdk.place_order(order)
        except Exception as e:
            logging.warning(
                f"create_order: Cannot create order of {params}: {e}")
            return

        ord_no = ret['ord_no']
        if ord_no == '':
            ord_no = ret['pre_ord_no']
        self.trades[ord_no] = ret
        return ord_no

    def update_order(self, order_id, price=None):

        if isinstance(price, int):
            price = float(price)

        if order_id not in self.trades:
            self.get_orders()

        if order_id not in self.trades:
            logging.warning(
                f"update_order: Order id {order_id} not found, cannot update the price.")

        if price is not None:
            try:
                if self.trades[order_id].org_order['ap_code'] == '5':
                    fugle_order = self.trades[order_id].org_order
                    action = Action.BUY if fugle_order['buy_sell'] == 'B' else Action.SELL
                    stock_id = fugle_order['stock_no']
                    q = fugle_order['org_qty_share'] - \
                        fugle_order['mat_qty_share'] - \
                        fugle_order['cel_qty_share']

                    self.cancel_order(order_id)
                    self.create_order(
                        action=action, stock_id=stock_id, quantity=q, price=price, odd_lot=True)
                else:
                    self.sdk.modify_price(
                        self.trades[order_id].org_order, price)
            except ValueError as ve:
                logging.warning(
                    f"update_order: Cannot update price of order {order_id}: {ve}")


    def cancel_order(self, order_id):
        if not order_id in self.trades:
            self.trades = self.get_orders()

        try:
            self.sdk.cancel_order(self.trades[order_id].org_order)
        except Exception as e:
            logging.warning(
                f"cancel_order: Cannot cancel order {order_id}: {e}")

    def get_orders(self):
        orders = self.sdk.get_order_results()
        ret = {}
        for o in orders:
            order_id = o['ord_no']
            if order_id == '':
                order_id = o['pre_ord_no']

            ret[order_id] = create_finlab_order(o)
        self.trades = ret
        return copy.deepcopy(ret)

    def get_stocks(self, stock_ids):
        ret = {}
        for s in stock_ids:
            try:
                res = requests.get(
                    f'https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{s}',headers={'X-API-KEY': self.market_api_key})
                json_response = res.json()
                ret[s] = to_finlab_stock(json_response)

                if math.isnan(ret[s].close):
                    ret[s].close = json_response['previousClose']

            except Exception as e:
                logging.warn(f"Fugle API: cannot get stock {s}")
                logging.warn(e)

        return ret

    def get_position(self):
        order_condition = {
            '0': OrderCondition.CASH,
            '3': OrderCondition.MARGIN_TRADING,
            '4': OrderCondition.SHORT_SELLING,
            '9': OrderCondition.DAY_TRADING_LONG,
            'A': OrderCondition.DAY_TRADING_SHORT,
        }

        now = datetime.datetime.now()

        total_seconds = (now - self.timestamp_for_get_position).total_seconds()

        if total_seconds < 10:
            time.sleep(10)

        inv = self.sdk.get_inventories()
        self.timestamp_for_get_position = now

        ret = []
        for i in inv:

            # removed: position of stk_dats is not completed
            # total_qty = sum([int(d['qty']) for d in i['stk_dats']]) / 1000
            total_qty = Decimal(int(i['qty_l']) +
                         int(i['qty_bm']) - int(i['qty_sm'])) / 1000

            o = order_condition[i['trade']]

            if total_qty != 0:
                ret.append({
                    'stock_id': i['stk_no'],
                    'quantity': total_qty if o != OrderCondition.SHORT_SELLING else -total_qty,
                    'order_condition': order_condition[i['trade']]
                })

        return Position.from_list(ret)

    def get_total_balance(self):
        # get bank balance
        bank_balance = self.sdk.get_balance()['available_balance']

        # get settlements
        tw_now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        settlements = self.sdk.get_settlements()
        settlements = sum(int(settlement['price']) for settlement in settlements if datetime.datetime.strptime(
            settlement['c_date'] + ' 10:00', '%Y%m%d %H:%M') > tw_now)

        # get position balance
        account_balance = sum(int(inv['value_mkt'])
                              for inv in self.sdk.get_inventories())
        return bank_balance + settlements + account_balance

    def support_day_trade_condition(self):
        return True

    def on_trades(self, func):

        order_condition = {
            '0': OrderCondition.CASH,
            '3': OrderCondition.MARGIN_TRADING,
            '4': OrderCondition.SHORT_SELLING,
            '9': OrderCondition.DAY_TRADING_LONG,
            'A': OrderCondition.DAY_TRADING_SHORT,
        }

        @self.acc.sdk.on('dealt')
        def on_dealt(data):
            if isinstance(data, dict):
                time = (datetime.datetime.strptime(f"{str((datetime.datetime.utcnow()+datetime.timedelta(hours=8)).date())} {data['mat_time']}", "%Y-%m-%d %H%M%S%f")-datetime.timedelta(
                    hours=8)).replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8))).isoformat()

                o = Order(order_id=data['ord_no'], stock_id=data['stock_no'],
                          action='BUY' if data['buy_sell'] == 'B' else 'SELL', price=data['mat_price'],
                          quantity=data['mat_qty'], filled_quantity=data['mat_qty'],
                          status='FILLED', order_condition=order_condition[data['trade']],
                          time=time, org_order=None)

                func(o)
        self.threading = Thread(target=lambda: self.sdk.connect_websocket())

    def sep_odd_lot_order(self):
        return True

    def get_price_info(self):
        ref = data.get('reference_price')
        return ref.set_index('stock_id').to_dict(orient='index')


def create_finlab_order(order):
    """將 fugle package 的委託單轉換成 finlab 格式"""

    status = OrderStatus.NEW
    if order['org_qty'] == order['mat_qty']:
        status = OrderStatus.FILLED
    elif order['mat_qty'] == 0 and order['celable'] == '1':
        status = OrderStatus.NEW
    elif order['org_qty'] > order['mat_qty'] + order['cel_qty'] and order['celable'] == '1' and order['mat_qty'] > 0:
        status = OrderStatus.PARTIALLY_FILLED
    elif order['cel_qty'] > 0 or order['err_code'] != '00000000' or order['celable'] == '2':
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

    return Order(**{
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


def to_finlab_stock(json_response):
    """將 fugle 股價行情轉換成 finlab 格式"""
    r = json_response

    if 'statusCode' in r:
        raise Exception('Cannot parse fugle quote data' + str(r))

    if 'bids' in r:
        bids = r['bids']
        asks = r['asks']
    else:
        bids = []
        asks = []

    has_volume = 'lastTrade' in r
    return Stock(
        stock_id=r['symbol'],
        high=r['highPrice'] if has_volume else np.nan,
        low=r['lowPrice'] if has_volume else np.nan,
        close=r['closePrice'] if has_volume else np.nan,
        open=r['openPrice'] if has_volume else np.nan,
        bid_price=bids[0]['price'] if bids else np.nan,
        ask_price=asks[0]['price'] if asks else np.nan,
        bid_volume=bids[0]['size'] if bids else 0,
        ask_volume=asks[0]['size'] if asks else 0,
    )

