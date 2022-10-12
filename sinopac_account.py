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
    def __init__(self, account=None, password=None, certificate_password=None, certificate_path=None):

        account = account or os.environ.get('SHIOAJI_ACCOUNT')
        password = password or os.environ.get('SHIOAJI_PASSWORD')
        certificate_password = certificate_password or os.environ.get(
            'SHIOAJI_CERT_PASSWORD')
        certificate_path = certificate_path or os.environ.get(
            'SHIOAJI_CERT_PATH')

        if certificate_password is None and account is not None:
            certificate_password = account

        if account is None or password is None or certificate_path is None:
            self.login()
            account = account or os.environ.get('SHIOAJI_ACCOUNT')
            password = password or os.environ.get('SHIOAJI_PASSWORD')
            certificate_password = certificate_password or os.environ.get(
                'SHIOAJI_CERT_PASSWORD')
            certificate_path = certificate_path or os.environ.get(
                'SHIOAJI_CERT_PATH')

        self.api = sj.Shioaji()
        self.accounts = self.api.login(account, password)

        if certificate_path:
            self.api.activate_ca(
                ca_path=certificate_path,
                ca_passwd=certificate_password,
                person_id=account,
            )

        self.trades = {}

    @staticmethod
    def login():
        account = input('Account name not found, please enter account name:\n')
        password = input('Enter an account password:\n')
        cert_password = input('Enter an certificate password :\n')
        cert_path = input('Enter certificate path:\n')

        os.environ['SHIOAJI_ACCOUNT'] = account
        os.environ['SHIOAJI_PASSWORD'] = password
        os.environ['SHIOAJI_CERT_PASSWORD'] = cert_password
        os.environ['SHIOAJI_CERT_PATH'] = cert_path

    def create_order(self, action, stock_id, quantity, price=None, odd_lot=False, market_order=False, best_price_limit=False, order_cond=OrderCondition.CASH):

        contract = self.api.Contracts.Stocks.get(stock_id)

        assert quantity > 0
        assert contract is not None

        if price == None:
            price = self.api.snapshots([contract])[0].close

        close_price = float(price)

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

        price = max(min(close_price * 1.1, price), close_price * 0.9)

        if action == Action.BUY:
            action = 'Buy'
        elif action == Action.SELL:
            action = 'Sell'

        first_sell = order_cond == OrderCondition.DAY_TRADING_SHORT
        first_sell = 'true' if first_sell else 'false'

        order_cond = {
            OrderCondition.CASH: 'Cash',
            OrderCondition.MARGIN_TRADING: 'MarginTrading',
            OrderCondition.SHORT_SELLING: 'ShortSelling',
            OrderCondition.DAY_TRADING_LONG: 'Cash',
            OrderCondition.DAY_TRADING_SHORT: 'Cash'
        }[order_cond]

        order_lot = sj.constant.TFTStockOrderLot.IntradayOdd\
            if odd_lot else sj.constant.TFTStockOrderLot.Common

        order = self.api.Order(price=price,
                               quantity=quantity,
                               action=action,
                               price_type="LMT",
                               order_type="ROD",
                               order_cond=order_cond,
                               first_sell=first_sell,
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
        return Position.from_dict([{
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
        bank_balance = self.api.account_balance()[0].acc_balance

        # get settlements
        settlements = self.api.list_settlements(self.api.stock_account)
        settlements = settlements[0].t_money + \
            settlements[0].t1_money + settlements[0].t2_money

        # get position balance
        position = self.get_position()
        stocks = self.get_stocks(position.keys())
        account_balance = sum(
            [sobj['quantity'] * stocks[sid].close * 1000 for sid, sobj in position.items()])
        return bank_balance + settlements + account_balance
