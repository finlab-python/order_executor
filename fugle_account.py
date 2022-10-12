from configparser import ConfigParser
from fugle_trade.sdk import SDK
from fugle_trade.order import OrderObject
from fugle_trade.constant import Action as fugleAction
from fugle_trade.constant import (APCode, Trade, PriceFlag, BSFlag, Action)

from finlab.online.base_account import Account, Stock, Order, Position
from finlab.online.enums import *
import requests
import datetime
import logging
import time
import os


class FugleAccount(Account):

    def __init__(self, config_path='./config.ini.example', market_api_key=None):

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

    def create_order(self, action, stock_id, quantity, price=None, odd_lot=False, best_price_limit=False, market_order=False, order_cond=OrderCondition.CASH):

        if quantity <= 0:
            raise ValueError("quantity should be larger than zero")

        if best_price_limit and market_order:
            raise ValueError(
                "The flags best_price_limit and  market_order should not both be True")

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
            OrderCondition.DAY_TRADING_LONG: Trade.DayTrading,
            OrderCondition.DAY_TRADING_SHORT: Trade.DayTradingSell,
        }[order_cond]

        ap_code = APCode.IntradayOdd if odd_lot else APCode.Common

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
        ret = self.sdk.place_order(order)

        ord_no = ret['ord_no']
        if ord_no == '':
            ord_no = ret['pre_ord_no']
        self.trades[ord_no] = ret
        return ord_no

    def update_order(self, order_id, price=None, quantity=None):

        if isinstance(price, int):
            price = float(price)

        if order_id not in self.trades:
            self.get_orders()

        if order_id not in self.trades:
            logging.warning(
                f"update_order: Order id {order_id} not found, cannot update the price.")

        if price is not None:
            try:
                self.sdk.modify_price(self.trades[order_id].org_order, price)
            except ValueError as ve:
                logging.warning(f"update_order: Cannot update price: {ve}")

        if quantity is not None:
            raise NotImplementedError("Cannot change order quantity")

    def cancel_order(self, order_id):
        if not order_id in self.trades:
            self.trades = self.get_orders()

        self.sdk.cancel_order(self.trades[order_id].org_order)

    def get_orders(self):
        orders = self.sdk.get_order_results()
        ret = {}
        for o in orders:
            order_id = o['ord_no']
            if order_id == '':
                order_id = o['pre_ord_no']

            ret[order_id] = Order.from_fugle(o)
        self.trades = ret
        return ret

    def get_stocks(self, stock_ids):
        ret = {}
        for s in stock_ids:
            try:
                res = requests.get(
                    f'https://api.fugle.tw/realtime/v0.3/intraday/quote?symbolId={s}&apiToken={self.market_api_key}')
                json_response = res.json()
                ret[s] = Stock.from_fugle(json_response)
            except Exception as e:
                logging.warn(f"** Fugle API: cannot get stock {s}")
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
            total_qty = sum([int(d['qty']) for d in i['stk_dats']]) / 1000
            ret.append({
                'stock_id': i['stk_no'],
                'quantity': total_qty,
                'order_condition': order_condition[i['trade']]
            })

        return Position.from_dict(ret)

    def get_total_balance():
        raise NotImplementedError("Total balance not implemented")

    def support_day_trade_condition(self):
        return True
