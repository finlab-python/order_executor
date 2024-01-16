import shioaji as sj
import datetime
import time
import os
import re
import math
import logging
from decimal import Decimal

from finlab.online.base_account import Account, Stock, Order
from finlab.online.enums import *
from finlab.online.order_executor import Position
from finlab import data

pattern = re.compile(r'(?<!^)(?=[A-Z])')


class SinopacAccount(Account):

    required_module = 'shioaji'
    module_version = '1.1.2'

    def __init__(self, api_key=None, secret_key=None, 
                 certificate_person_id=None, 
                 certificate_password=None, 
                 certificate_path=None):

        api_key = api_key or os.environ.get('SHIOAJI_API_KEY')
        secret_key = secret_key or os.environ.get('SHIOAJI_SECRET_KEY')

        certificate_password = certificate_password or os.environ.get(
            'SHIOAJI_CERT_PASSWORD')
        certificate_path = certificate_path or os.environ.get(
                'SHIOAJI_CERT_PATH')
        certificate_person_id = certificate_person_id or os.environ.get(
                'SHIOAJI_CERT_PERSON_ID')

        self.api = sj.Shioaji()
        self.accounts = self.api.login(api_key, secret_key, fetch_contract=False)

        self.trades = {}

        self.api.activate_ca(
            ca_path=certificate_path,
            ca_passwd=certificate_password,
            person_id=certificate_person_id,
        )

    def create_order(self, action, stock_id, quantity, price=None, odd_lot=False, market_order=False, best_price_limit=False, order_cond=OrderCondition.CASH):

        # contract = self.api.Contracts.Stocks.get(stock_id)
        contract = sj.contracts.Contract(security_type='STK', code=stock_id, exchange='TSE')
        pinfo = self.get_price_info()
        limitup = float(pinfo[stock_id]['漲停價'])
        limitdn = float(pinfo[stock_id]['跌停價'])
        last_close = float(pinfo[stock_id]['收盤價'])

        if stock_id not in pinfo:
            raise Exception(f"stock {stock_id} not in price info")
        
        if quantity <= 0:
            raise Exception(f"quantity must be positive, got {quantity}")

        if price == None:
            price = self.api.snapshots([contract])[0].close

        price_type = sj.constant.StockPriceType.LMT

        if market_order:
            if action == Action.BUY:
                price = limitup
            elif action == Action.SELL:
                price = limitdn

        elif best_price_limit:
            if action == Action.BUY:
                price = limitdn
            elif action == Action.SELL:
                price = limitup

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
                               price_type=price_type,
                               order_type=sj.constant.OrderType.ROD,
                               order_cond=order_cond,
                               daytrade_short=daytrade_short,
                               account=self.api.stock_account,
                               order_lot=order_lot,
                               custom_field="FiNlAB",
                               )
        trade = self.api.place_order(contract, order)

        self.trades[trade.status.id] = trade
        return trade.status.id
    
    def get_price_info(self):
        ref = data.get('reference_price')
        return ref.set_index('stock_id').to_dict(orient='index')

    def update_trades(self):
        self.api.update_status(self.api.stock_account)
        self.trades = {t.status.id: t for t in self.api.list_trades()}

    def update_order(self, order_id, price):
        order = self.get_orders()[order_id]
        trade = self.trades[order_id]

        try:
            if trade.order.order_lot == 'IntradayOdd':
                action = order.action
                stock_id = order.stock_id
                q = order.quantity - \
                    order.filled_quantity
                q *= 1000

                self.cancel_order(order_id)
                self.create_order(
                    action=action, stock_id=stock_id, quantity=q, price=price, odd_lot=True)
            else:
                self.api.update_order(trade, price=price)
        except ValueError as ve:
            logging.warning(
                f"update_order: Cannot update price of order {order_id}: {ve}")

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
            'quantity': Decimal(p.quantity)/1000 if p.direction == 'Buy' else -Decimal(p.quantity)/1000,
            'order_condition': order_conditions[p.cond]
        } for p in position])

    def get_orders(self):
        self.update_trades()
        return {t.status.id: trade_to_order(t) for name, t in self.trades.items()}

    def get_stocks(self, stock_ids):
        try:
            contracts = [sj.contracts.Contract(security_type='STK', code=s, exchange='TSE') for s in stock_ids]
            snapshots = self.api.snapshots(contracts)
        except:
            time.sleep(10)
            contracts = [sj.contracts.Contract(security_type='STK', code=s, exchange='TSE') for s in stock_ids]
            snapshots = self.api.snapshots(contracts)

        return {s.code: snapshot_to_stock(s) for s in snapshots}

    def get_total_balance(self):
        # get bank balance
        bank_balance = self.api.account_balance().acc_balance

        # get settlements
        tw_now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        settlements = self.api.settlements(self.api.stock_account)
        settlements = sum(int(settlement.amount) for settlement in settlements if datetime.datetime.combine(settlement.date, datetime.time(10,0)) > tw_now)

        # get position balance
        position = self.get_position()
        if position.position:
            stocks = self.get_stocks([i['stock_id'] for i in position.position])
            account_balance = sum(
                [float(i['quantity']) * stocks[i['stock_id']].close * 1000 for i in position.position])
        else:
            account_balance = 0
        return bank_balance + settlements + account_balance    


    def sep_odd_lot_order(self):
        return True

def trade_to_order(trade):
    """將 shioaji package 的委託單轉換成 finlab 格式"""
    if trade.order.action == 'Buy':
        action = Action.BUY
    elif trade.order.action == 'Sell':
        action = Action.SELL
    else:
        raise Exception('trader order action should be "Buy" or "Sell"')

    status = {
            'PendingSubmit': OrderStatus.NEW,
            'PreSubmitted': OrderStatus.NEW,
            'Submitted': OrderStatus.NEW,
            'Failed': OrderStatus.CANCEL,
            'Cancelled': OrderStatus.CANCEL,
            'Filled': OrderStatus.FILLED,
            'Filling': OrderStatus.PARTIALLY_FILLED,
            'PartFilled': OrderStatus.PARTIALLY_FILLED,
            }[trade.status.status]

    order_condition = {
            'Cash': OrderCondition.CASH,
            'MarginTrading': OrderCondition.MARGIN_TRADING,
            'ShortSelling': OrderCondition.SHORT_SELLING,
            }[trade.order.order_cond]

    # calculate quantity
    # calculate filled quantity
    quantity = Decimal(trade.order.quantity)
    filled_quantity = Decimal(trade.status.deal_quantity)

    if trade.order.order_lot == 'IntradayOdd':
        quantity /= 1000
        filled_quantity /= 1000

    # calculate order condition
    if trade.order.daytrade_short == True and order_condition == OrderCondition.CASH:
        order_condition = OrderCondition.DAY_TRADING_SHORT

    return Order(**{
        'order_id': trade.status.id,
        'stock_id': trade.contract.code,
        'action': action,
        'price': trade.order.price if trade.status.modified_price == 0 else trade.status.modified_price,
        'quantity': quantity,
        'filled_quantity': filled_quantity,
        'status': status,
        'order_condition': order_condition,
        'time': trade.status.order_datetime,
        'org_order': trade
        })


def snapshot_to_stock(snapshot):
    """將 shioaji 股價行情轉換成 finlab 格式"""
    d = snapshot
    return Stock(stock_id=d.code, open=d.open, high=d.high, low=d.low, close=d.close,
               bid_price=d.buy_price, ask_price=d.sell_price, bid_volume=d.buy_volume, ask_volume=d.sell_volume)

