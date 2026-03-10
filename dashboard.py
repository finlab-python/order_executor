from finlab.online.order_executor import Position
from finlab.online.order_executor import OrderExecutor
from finlab.compat import resolve_position_entry_symbol
import sched
import time
import finlab
import threading
import datetime
import requests
import pandas as pd
from typing import List


class Dashboard():

    def __init__(self, acc, paper_trade=False, odd_lot=True, trade_in_advance=1800, price_update_period=300, *args, **kwargs):
        self.acc = acc
        self.paper_trade = paper_trade
        self.odd_lot = odd_lot
        self.thread_callback = None
        self.thread_balancecheck = None
        self.position = None
        self.target_position = None
        self.trade_in_advance = trade_in_advance
        self.price_update_period = price_update_period

        self.sched = sched.scheduler(time.time, time.sleep)
        self.events = []
        self.thread_sched = threading.Thread(target=self.running_sched)
        self.thread_sched.start()

        self.thread_update_price = threading.Thread(target=self.update_price)
        if self.paper_trade:
            self.thread_update_price.start()

        self.record_txn_event()
        self.args = args
        self.kwargs = kwargs
        self.oe = None

    def running_sched(self):
        while True:
            time.sleep(3)
            self.sched.run(blocking=True)

    def update_price(self):
        while True:
            time.sleep(self.price_update_period)

            if self.oe:
                self.oe.update_order_price()

    def fetch_portfolio(self):
        url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_get_portfolio'
        return requests.post(url, json={'api_token': finlab.get_token()[0]}).json()['msg']

    def set_portfolio(self, allocs):
        url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_set_portfolio'
        # url = 'http://127.0.0.1:8080'
        return requests.post(url, json={
            'api_token': finlab.get_token()[0],
            'allocs': allocs,
            }).json()['msg']

    def get_present_qty(self):

        # get present_qty
        position = self.acc.get_position()
        if len(position.position) == 0:
            acc_position = []
        else:
            rows = []
            for p in position.position:
                rows.append({
                    'symbol': resolve_position_entry_symbol(p),
                    'quantity': p['quantity'],
                })
            acc_position = pd.DataFrame(rows).groupby('symbol').sum()

        stocks = self.acc.get_stocks(acc_position.index.tolist())


        if isinstance(acc_position, list):
            present_qty = []
        else:
            present_qty = [{
                'symbol': f'{stock_id}.tw_stock',
                'price': stocks[stock_id].close,
                'qty': row['quantity']
            } for stock_id, row in acc_position.iterrows()]

        return present_qty

    def get_target_qty(self, port, sid) -> List:

        if (sid not in port.strategy 
            or len(port.strategy[sid]) == 0
            or port.strategy[sid][-1].q is not None):
            return []

        s = port.strategy[sid][-1]

        alloc = s['al']
        weight = s['w']

        # get price
        stocks = self.acc.get_stocks(list(weight.keys()))
        price = {sid:stock.close for sid, stock in stocks.items()}

        position = Position.from_weight(weight, price=price, fund=alloc, odd_lot=self.odd_lot)

        q = {}

        for p in position.position:
            q[resolve_position_entry_symbol(p)] = p['quantity']

        target_qty = []

        for p in position.position:
            symbol = resolve_position_entry_symbol(p)
            target_qty.append({
                'symbol': symbol,
                'qty': p['quantity'],
                'strategy_id': sid
            })

        return target_qty

    def set_qty(self, sid=None):
        port = self.fetch_portfolio()

        if sid is not None:

            target_qty = self.get_target_qty(port, sid)
            present_qty = self.get_present_qty() if not self.paper_trade else []

            url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_set_qty'
            res = requests.post(url, json={
                                'target_qty': target_qty, 'present_qty': present_qty,
                                'api_token': finlab.get_token()[0], 'pt': self.paper_trade})
        
            for t in target_qty:
                port.s[t['strategy_id']][-1].q[t['symbol']] = t['qty']

        p = self.calc_target_position(port)

        if not self.paper_trade:
            self.oe = OrderExecutor(p, self.acc)
            self.oe.create_orders(*self.args, **self.kwargs)
        else:
            symbols = [resolve_position_entry_symbol(pp) for pp in p.position]
            stocks = self.acc.get_stocks([symbol.split('.')[0] for symbol in symbols])

            present_qty = []
            for symbol, pp in zip(symbols, p.position):
                base_symbol = symbol.split('.')[0]
                stock = stocks.get(symbol) or stocks[base_symbol]
                present_qty.append({
                    'symbol': symbol,
                    'price': stock.close,
                    'qty': pp['quantity'],
                })

            # upload present and target qty
            url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_set_qty'
            requests.post(url, json={
                'target_qty': [], 'present_qty': present_qty,
                'api_token': finlab.get_token()[0], 'pt': True})
 

    def set_schedule(self):

        port = self.fetch_portfolio()

        for e in self.events:
            self.sched.cancel(e)
        self.events = []

        self.set_qty()

        for sid, strategy in port['s'].items():
            if strategy and strategy[-1]['q'] is None:
                rebalance_time = datetime.datetime.fromisoformat(strategy[-1]['tb']) - datetime.timedelta(seconds=self.trade_in_advance)
                print(time.time(), rebalance_time.timestamp())

                print(strategy[-1]['tb'])
                print(sid, rebalance_time)
                secs = int(rebalance_time.timestamp())
                self.events.append(self.sched.enter(secs, 1, self.set_qty, (sid,)))


    def start(self):

        while True:
            self.set_schedule()
            time.sleep(60)

                
    @staticmethod
    def calc_target_position(port) -> Position:


        ret = Position({})

        for sid, strategy in port['s'].items():
            sqty = {}

            if len(strategy) == 0:
                pass
            elif strategy[-1]['q'] is not None:
                sqty = strategy[-1]['q']
            elif len(strategy) >= 2 and strategy[-2].q is not None:
                sqty = strategy[-2]['q']

            ret += Position(sqty)

        return ret

    def record_txn_event(self):

        if self.acc.threading and self.acc.threading.is_alive():
            return

        def upload_trade(trade):

            url = "https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_add_txn"

            json = {
                "api_token": finlab.get_token()[0],
                "pt": self.paper_trade,
                "symbol": {
                    "id": trade.symbol if isinstance(getattr(trade, "symbol", None), str) else trade.stock_id,
                    "market": "tw_stock",
                },
                "txn": {
                    "price": trade.price,
                    "qty": trade.filled_quantity,
                    "time": trade.time,
                }
            }
            requests.post(url, json=json)

        self.acc.on_trades(upload_trade)
