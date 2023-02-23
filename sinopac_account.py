from abc import ABC, abstractmethod
import pandas as pd
import shioaji as sj
import datetime
import numbers
import time
import os
import re

from finlab.online.base_account import Account, Stock, Order, Position
from finlab.online.enums import *

pattern = re.compile(r'(?<!^)(?=[A-Z])')


class SinopacAccount(Account):
    def __init__(self, api_key=None, secret_key=None, account=None, certificate_password=None, certificate_path=None):

        api_key = api_key or os.environ.get('SHIOAJI_API_KEY')
        secret_key = secret_key or os.environ.get('SHIOAJI_SECRET_KEY')
        certificate_password = certificate_password or os.environ.get(
            'SHIOAJI_CERT_PASSWORD')

        self.api = sj.Shioaji()
        self.accounts = self.api.login(api_key, secret_key)

        self.trades = {}

        if certificate_path:
            self.api.activate_ca(
                ca_path=certificate_path,
                ca_passwd=certificate_password,
                person_id=account,
            )


    def create_order(self, action, stock_id, quantity, price=None, odd_lot=False, market_order=False, best_price_limit=False, order_cond=OrderCondition.CASH):

        contract = self.api.Contracts.Stocks.get(stock_id)

        assert quantity > 0
        assert contract is not None

        if price == None:
            price = self.api.snapshots([contract])[0].close

        if market_order:
            if action == Action.BUY:
                price = contract.limit_up
            elif action == Action.SELL:
                price = contract.limit_down
        elif best_price_limit:
            if action == Action.BUY:
                price = contract.limit_down
            elif action == Action.SELL:
                price = contract.limit_up

        if action == Action.BUY:
            action = 'Buy'
        elif action == Action.SELL:
            action = 'Sell'

        daytrade_short = order_cond == OrderCondition.DAY_TRADING_SHORT
        daytrade_short = True if daytrade_short else False

        order_cond = {
            OrderCondition.CASH: 'Cash',
            OrderCondition.MARGIN_TRADING: 'MarginTrading',
            OrderCondition.SHORT_SELLING: 'ShortSelling',
            OrderCondition.DAY_TRADING_LONG: 'Cash',
            OrderCondition.DAY_TRADING_SHORT: 'Cash'
        }[order_cond]

        order_lot = sj.constant.StockOrderLot.IntradayOdd\
            if odd_lot else sj.constant.StockOrderLot.Common
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        if datetime.time(13,40) < datetime.time(now.hour,now.minute) and datetime.time(now.hour,now.minute) < datetime.time(14,30) and odd_lot:
            order_lot = sj.constant.StockOrderLot.Odd
        if datetime.time(14,00) < datetime.time(now.hour,now.minute) and datetime.time(now.hour,now.minute) < datetime.time(14,30) and not odd_lot:
            order_lot = sj.constant.StockOrderLot.Fixing

        order = self.api.Order(price=price,
                               quantity=quantity,
                               action=action,
                               price_type=sj.constant.StockPriceType.LMT,
                               order_type=sj.constant.OrderType.ROD,
                               order_cond=order_cond,
                               daytrade_short=daytrade_short,
                               account=self.api.stock_account,
                               order_lot=order_lot,
                               )
        trade = self.api.place_order(contract, order)

        self.trades[trade.status.id] = trade
        return trade.status.id

    def update_trades(self):
        self.api.update_status(self.api.stock_account)
        self.trades = {t.status.id: t for t in self.api.list_trades()}

    def update_order(self, order_id, **argv):
        trade = self.trades[order_id]
        self.api.update_order(trade, **argv)

    def cancel_order(self, order_id):
        self.update_trades()
        self.api.cancel_order(self.trades[order_id])

    def get_position(self):
        position = self.api.list_positions(
            self.api.stock_account, unit=sj.constant.Unit.Share)
        order_conditions = {
            'Cash': OrderCondition.CASH,
            'MarginTrading': OrderCondition.MARGIN_TRADING,
            'ShortSelling': OrderCondition.SHORT_SELLING,
        }
        return Position.from_list([{
            'stock_id': p.code,
            'quantity': p.quantity/1000 if p.direction == 'Buy' else -p.quantity/1000,
            'order_condition': order_conditions[p.cond]
        } for p in position])

    def get_orders(self):
        self.update_trades()
        return {t.status.id: Order.from_shioaji(t) for name, t in self.trades.items()}

    def get_stocks(self, stock_ids):
        try:
            contracts = [self.api.Contracts.Stocks.get(s) for s in stock_ids]
            snapshots = self.api.snapshots(contracts)
        except:
            time.sleep(10)
            contracts = [self.api.Contracts.Stocks.get(s) for s in stock_ids]
            snapshots = self.api.snapshots(contracts)

        return {s.code: Stock.from_shioaji(s) for s in snapshots}

    def get_total_balance(self):
        # get bank balance
        bank_balance = self.api.account_balance().acc_balance

        # get settlements
        settlements = self.api.settlements(self.api.stock_account)
        settlements = settlements[0].amount + \
            settlements[1].amount + settlements[2].amount

        # get position balance
        position = self.get_position()
        if position.position:
            stocks = self.get_stocks([i['stock_id'] for i in position.position])
            account_balance = sum(
                [i['quantity'] * stocks[i['stock_id']].close * 1000 for i in position.position])
        else:
            account_balance = 0
        return bank_balance + settlements + account_balance
