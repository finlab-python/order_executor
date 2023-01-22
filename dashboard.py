from finlab.online.order_executor import Position
from finlab.online.order_executor import OrderExecutor
import time
import finlab
import datetime
import requests
import pandas as pd


class Dashboard():

    def __init__(self, acc, paper_trade=False, odd_lot=True, minutes_before=10):
        self.acc = acc
        self.paper_trade = paper_trade
        self.odd_lot = odd_lot
        self.thread_callback = None
        self.thread_balancecheck = None
        self.position = None
        self.target_position = None

    def fetch_portfolio(self):
        url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_get_portfolio'
        return requests.post(url, json={'api_token': finlab.get_token()}).json()['msg']

    def set_portfolio(self, allocs):
        # url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_set_portfolio'
        url = 'http://127.0.0.1:8080'
        return requests.post(url, json={
            'api_token': finlab.get_token(),
            'allocs': allocs,
            }).json()['msg']

    def get_present_qty(self):

        # get present_qty
        position = self.acc.get_position()
        acc_position = pd.DataFrame(position.position).groupby(
            'stock_id').sum() if len(position.position) > 0 else []

        stocks = self.acc.get_stocks(acc_position.index.tolist())

        present_qty = [{
            'symbol': f'{stock_id}.tw_stock',
            'price': stocks[stock_id].close,
            'qty': row['quantity']
        } for stock_id, row in acc_position.iterrows()]

        return present_qty

    def get_target_qty(self, port, sid):

        if (sid not in port.strategy 
            or len(port.strategy[sid]) == 0
            or port.strategy[sid][-1].q is not None):
            return

        s = port.strategy[sid][-1]

        alloc = s['al']
        weight = s['w']

        # get price
        stocks = [l.split('.')[0] for l in list(weight.keys())]
        id_to_symbol = {l.split('.')[0]:l for l in list(weight.keys())}
        stocks = self.acc.get_stocks(stocks)
        price = {id_to_symbol[sid]: stock.close for sid,
                 stock in stocks.items()}

        position = Position.from_weight(weight, price=price, fund=alloc, odd_lot=self.odd_lot)

        q = {}

        for p in position.position:
            q[p['stock_id']] = p['quantity']


        target_qty = []

        for p in position.position:
            target_qty.append({
                'symbol': p["stock_id"],
                'qty': p['quantity'],
                'strategy_id': strategy_id
            })

        return target_qty

    def set_qty(self, sid):
        port = self.fetch_portfolio()

        target_qty = self.get_target_qty(port, sid)
        present_qty = self.get_present_qty() if not self.paper_trade else []

        url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_set_qty'
        res = requests.post(url, json={
                            'target_qty': target_qty, 'present_qty': present_qty,
                            'api_token': finlab.get_token(), 'pt': self.paper_trade})

    def set_schedule(self): # todo refine schedule

        port = self.fetch_portfolio()

        for sid, strategy in port.s.items():
            if strategy and strategy[-1].q:

        # assign rebalance weight
        rebalance_strategy = {aid: dict() for aid, a in port['allocs'].items()}

        tw_stock_accepted_trade_at_price = ['close', 'open'] if (datetime.datetime.utcnow(
        ) + datetime.timedelta(hours=8)).time() > datetime.time(12, 0) else ['open']

        for symbol, asset in port['assets'].items():
            asset_id, market = symbol.split('.')
            for strategy_id, strategy in asset['strategy_events'].items():

                accepted_trade_at_price = tw_stock_accepted_trade_at_price if market == 'tw_stock' else ['close', 'open']

                if strategy[-1]['type'] == 'ALLOC'\
                        and strategy[-1]['qty'] is None\
                        and strategy[-1]['trade_at_price'] in accepted_trade_at_price:

                    rebalance_strategy[strategy_id][symbol] = strategy[-1]['alloc']

        # calculate and assign target qty
        target_qty = []
        for strategy_id, allocation in rebalance_strategy.items():
            fund = sum(allocation.values())

            stocks = [l.split('.')[0] for l in list(allocation.keys())]
            id_to_symbol = {l.split('.')[0]:l for l in list(allocation.keys())}
            stocks = self.acc.get_stocks(stocks)
            price = {id_to_symbol[sid]: stock.close for sid,
                     stock in stocks.items()}
            weight = {k: v/fund for k, v in allocation.items()}
            position = Position.from_weight(weight, price=price, fund=fund, odd_lot=odd_lot)

            for p in position.position:
                target_qty.append({
                    'symbol': p["stock_id"],
                    'qty': p['quantity'],
                    'strategy_id': strategy_id
                })
                port['assets'][p["stock_id"]]['strategy_events'][strategy_id][-1]['qty'] = p['quantity']

        # upload present and target qty
        if self.paper_trade:

            url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_set_qty'
            # url = 'http://localhost:8080'
            res = requests.post(url, json={
                                'target_qty': target_qty, 'present_qty': [],
                                'api_token': finlab.get_token(), 'pt': self.paper_trade})
            return


        # upload present and target qty
        url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_set_qty'
        # url = 'http://localhost:8080'
        res = requests.post(url, json={
                            'target_qty': target_qty, 'present_qty': present_qty,
                            'api_token': finlab.get_token(), 'pt': self.paper_trade})

    def calc_target_position(self):

        port = self.fetch_portfolio()

        # get portfolio position
        now = datetime.datetime.now(
            tz=datetime.timezone(datetime.timedelta(hours=8)))
        target_position = {}
        for symbol, asset in port['assets'].items():
            for strategy_id, strategy in asset['strategy_events'].items():

                q2 = strategy[-1]['qty']  # latest qty
                # previous qty
                q1 = strategy[-2]['qty'] if len(strategy) >= 2 else 0

                qty = q2 if now > datetime.datetime.fromisoformat(
                    strategy[-1]['time']) - datetime.timedelta(minutes=30) else q1
                if qty:
                    if symbol not in target_position:
                        target_position[symbol] = 0
                    target_position[symbol] += qty


        self.target_position = target_position

        return self.target_position

    def connect(self):

        if self.acc.threading and self.acc.threading.is_alive():
            return

        def upload_trade(trade):

            url = "https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_add_txn"

            json = {
                "api_token": finlab.get_token(),
                "pt": self.paper_trade,
                "symbol": {
                    "id": trade.stock_id,
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

    def rebalance(self, *args, refresh_time=30, rebalance_once=True, **kwargs):
        if self.target_position is None:
            self.calc_target_position()

        assert self.target_position is not None

        if self.paper_trade:
            # get present_qty
            position = self.target_position

            stocks = self.acc.get_stocks([symbol.split('.')[0] for symbol in self.target_position.keys()])

            present_qty = [{
                'symbol': symbol,
                'price': stocks[symbol.split('.')[0]].close,
                'qty': qty
            } for symbol, qty in position.items()]

            # upload present and target qty
            url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_set_qty'
            requests.post(url, json={
                'target_qty': [], 'present_qty': present_qty,
                'api_token': finlab.get_token(), 'pt': True})
            return

        self.position = Position(self.target_position)
        self.oe = OrderExecutor(self.position, self.acc)
        position = sorted(self.position.position, key=lambda d: d['stock_id'])

        self.connect()

        self.oe.create_orders(*args, **kwargs)

        while not rebalance_once:
            time.sleep(refresh_time)
            account_present = sorted(
                self.acc.get_position().position, key=lambda d: d['stock_id'])
            if account_present == position:
                break
            self.oe.update_order_price()
