from finlab.online.order_executor import Position
from finlab.online.order_executor import OrderExecutor
import time
import finlab
import datetime
import requests
import pandas as pd


class Dashboard():

    def __init__(self, acc, paper_trade=False):
        self.acc = acc
        self.paper_trade = paper_trade
        self.thread_callback = None
        self.thread_balancecheck = None
        self.position = None

    def fetch_portfolio(self):
        url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dashboard_get_portfolio'
        return requests.post(url, json={'api_token': finlab.get_token()}).json()['msg']

    def set_qty(self, odd_lot=False):

        port = self.fetch_portfolio()

        # assign rebalance weight
        rebalance_strategy = {aid: dict() for aid, a in port['allocs'].items()}

        accepted_trade_at_price = ['close', 'open'] if (datetime.datetime.utcnow(
        ) + datetime.timedelta(hours=8)).time() > datetime.time(12, 0) else ['open']

        for symbol, asset in port['assets'].items():
            asset_id, market = symbol.split('.')
            for strategy_id, strategy in asset['strategy_events'].items():
                if strategy[-1]['type'] == 'ALLOC'\
                        and strategy[-1]['qty'] is None\
                        and strategy[-1]['trade_at_price'] in accepted_trade_at_price:

                    rebalance_strategy[strategy_id][asset_id] = strategy[-1]['alloc']

        # calculate and assign target qty
        target_qty = []
        for strategy_id, allocation in rebalance_strategy.items():
            fund = sum(allocation.values())

            stocks = self.acc.get_stocks(list(allocation.keys()))
            price = {stock_id: stock.close for stock_id,
                     stock in stocks.items()}
            position = Position.from_weight({k: v/fund for k, v in allocation.items()},
                                            price=price, fund=fund, odd_lot=odd_lot)

            for p in position.position:
                symbol = f'{p["stock_id"]}.tw_stock'
                target_qty.append({
                    'symbol': symbol,
                    'qty': p['quantity'],
                    'strategy_id': strategy_id
                })
                print(symbol, strategy_id)
                port['assets'][symbol]['strategy_events'][strategy_id][-1]['qty'] = p['quantity']

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
            asset_id, market = symbol.split('.')
            for strategy_id, strategy in asset['strategy_events'].items():

                q2 = strategy[-1]['qty']  # latest qty
                # previous qty
                q1 = strategy[-2]['qty'] if len(strategy) >= 2 else 0

                qty = q2 if now > datetime.datetime.fromisoformat(
                    strategy[-1]['time']) - datetime.timedelta(minutes=30) else q1
                if qty:
                    if asset_id not in target_position:
                        target_position[asset_id] = 0
                    target_position[asset_id] += qty

        self.position = Position(target_position)
        self.oe = OrderExecutor(self.position, self.acc)
        return self.position

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
        if self.position is None:
            self.calc_target_position()

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
