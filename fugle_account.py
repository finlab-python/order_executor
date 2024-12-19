from configparser import ConfigParser
from fugle_trade.sdk import SDK
from fugle_trade.order import OrderObject
from fugle_trade.constant import Action as fugleAction
from fugle_trade.constant import (APCode, Trade, PriceFlag, BSFlag, Action)
from fugle_trade.util import setup_keyring, set_password

from finlab.online.base_account import Account, Stock, Order
from finlab.online.enums import *
from finlab.markets.tw import TWMarket
from finlab.online.order_executor import Position
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

trades = {}
threads = {}
callbacks = {}

class FugleAccount(Account):

    required_module = 'fugle_trade'
    module_version = '1.2.0'

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
        
        if 'FUGLE_ACCOUNT_PASSWORD' in os.environ and 'FUGLE_CERT_PASSWORD' in os.environ:

            setup_keyring(config['User']['Account'])
            set_password("fugle_trade_sdk:account", config['User']['Account'], os.environ['FUGLE_ACCOUNT_PASSWORD'])
            set_password("fugle_trade_sdk:cert", config['User']['Account'], os.environ['FUGLE_CERT_PASSWORD'])

        sdk = SDK(config)
        sdk.login()
        self.sdk = sdk
        self.market_api_key = market_api_key
        self.user_account = config['User']['Account']

        global trades, threads
        trades[self.user_account] = {}

        # 註冊接收委託回報的 callback
        @self.sdk.on('order')
        def on_order(order):

            try:
                order_id = self.get_org_order_id(order)
                global trades, callbacks
                trades[self.user_account][order_id] = create_finlab_order(order)
                if self.user_account + order_id in callbacks:
                    finish = callbacks[self.user_account + order_id](trades[self.user_account][order_id])
                    if finish:
                        del callbacks[self.user_account + order_id]
            except Exception as e:
                import traceback
                traceback.print_exc()
                logging.warning(f"on_order: Cannot process order {order}: {e}")

        if self.user_account not in threads:
            self.thread = Thread(target=lambda: self.sdk.connect_websocket())
            self.thread.daemon = True
            self.thread.start()

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
        
        order_id = self.get_org_order_id(ret)
        return order_id

    def update_order(self, order_id, price=None):

        global trades, callbacks

        if isinstance(price, int):
            price = float(price)

        if order_id not in trades[self.user_account] or trades[self.user_account][order_id].org_order.get('kind', '') == 'ACK':
            self.get_orders()

        if order_id not in trades[self.user_account]:
            logging.warning(
                f"update_order: Order id {order_id} not found, cannot update the price.")

        if price is not None:
            try:
                if trades[self.user_account][order_id].org_order['ap_code'] == '5':
                    fugle_order = trades[self.user_account][order_id].org_order
                    action = Action.BUY if fugle_order['buy_sell'] == 'B' else Action.SELL
                    stock_id = fugle_order['stock_no']
                    user_cancel_orders = fugle_order['cel_qty']
                    # q = fugle_order['org_qty_share'] - \
                    #     fugle_order['mat_qty_share'] - \
                    #     fugle_order['cel_qty_share']

                    self.cancel_order(order_id)

                    def callback(order):
                        if order.status == OrderStatus.CANCEL:
                            all_canceled_orders = float(trades[self.user_account][order_id].org_order['cel_qty'])
                            quantity = int((all_canceled_orders - user_cancel_orders))
                            self.create_order(
                                action=action, stock_id=stock_id, quantity=quantity, price=price, odd_lot=True)
                            return True
                        return False
                            
                    callbacks[self.user_account + order_id] = callback
                else:
                    self.sdk.modify_price(
                        trades[self.user_account][order_id].org_order, price)
            except ValueError as ve:
                logging.warning(
                    f"update_order: Cannot update price of order {order_id}: {ve}")


    def cancel_order(self, order_id):

        global trades
        if not order_id in trades[self.user_account] or trades[self.user_account][order_id].org_order.get('kind', '') == 'ACK':
            trades[self.user_account] = self.get_orders()

        try:
            self.sdk.cancel_order(trades[self.user_account][order_id].org_order)
        except Exception as e:
            logging.warning(
                f"cancel_order: Cannot cancel order {order_id}: {e}")
            

    def get_org_order_id(self, org_order):
        order_id = org_order['ord_no']
        if order_id == '':
            order_id = org_order['pre_ord_no']
        return order_id


    def get_orders(self):

        global trades
        success = False
        fetch_count = 0

        while not success:
            try:
                orders = self.sdk.get_order_results()
                success = True
            except:
                logging.warning("get_orders: Cannot get orders, sleep for 1 minute")
                fetch_count += 1
                time.sleep(60)
                if fetch_count > 5:
                    logging.error("get_orders: Cannot get orders, try 5 times, raise error")
                    raise Exception("Cannot get orders")

        ret = {}
        for o in orders:
            order_id = self.get_org_order_id(o)
            ret[order_id] = create_finlab_order(o)
        trades[self.user_account] = ret

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
        bank_balance = self.get_cash()

        # get settlements
        settlements = self.get_settlement()

        # get position balance
        account_balance = sum(int(inv['value_mkt'])
                              for inv in self.sdk.get_inventories())
        return bank_balance + settlements + account_balance
    
    def get_cash(self):
        return self.sdk.get_balance()['available_balance']
    
    def get_settlement(self):
        tw_now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        settlements = self.sdk.get_settlements()
        settlements = sum(int(settlement['price']) for settlement in settlements if datetime.datetime.strptime(
            settlement['c_date'] + ' 10:00', '%Y%m%d %H:%M') > tw_now)
        return settlements

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

    def get_market(self):
        return TWMarket()


def create_finlab_order(order):
    """將 fugle package 的委託單轉換成 finlab 格式"""


    # deepcopy order
    org_order = order
    order = copy.deepcopy(order)

    order['org_qty'] = float(order['org_qty'])
    order['mat_qty'] = float(order['mat_qty'])
    order['cel_qty'] = float(order['cel_qty'])

    status = OrderStatus.NEW
    if order['org_qty'] == order['mat_qty']:
        status = OrderStatus.FILLED
    elif order['mat_qty'] == 0 and order['cel_qty'] == 0 and order.get('celable', '1') == '1':
        status = OrderStatus.NEW
    elif order['org_qty'] > order['mat_qty'] + order['cel_qty'] and order.get('celable', '1') == '1' and order['mat_qty'] > 0:
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

    if 'ord_date' in order:
        order_time = datetime.datetime.strptime(order['ord_date'] + order['ord_time'], '%Y%m%d%H%M%S%f')
    else:
        order_time = datetime.datetime.strptime(order['ret_date'] + order['ret_time'], '%Y%m%d%H%M%S%f')

    return Order(**{
        'order_id': order_id,
        'stock_id': order['stock_no'],
        'action': Action.BUY if order['buy_sell'] == 'B' else Action.SELL,
        'price': order.get('od_price', 0),
        'quantity': order['org_qty'] - order['cel_qty'],
        'filled_quantity': filled_quantity,
        'status': status,
        'order_condition': order_condition,
        'time': order_time,#datetime.datetime.strptime(order['ord_date'] + order['ord_time'], '%Y%m%d%H%M%S%f'),
        'org_order': org_order
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

