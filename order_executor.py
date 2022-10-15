from finlab.online.utils import greedy_allocation
from finlab.online.enums import *
from finlab import data
import pandas as pd
import requests
import datetime
import time


class Position():

    """使用者可以利用 Position 輕鬆建構股票的部位，並且利用 OrderExecuter 將此部位同步於實際的股票帳戶。

    """

    def __init__(self, stocks, margin_trading=False, short_selling=False, day_trading_long=False, day_trading_short=False):
        """建構股票部位

        Attributes:
            stocks (`dict` of `str`:`number.Number`): 股票代號與張數 ex: {'1101': 1} 是指持有一張 1101 台泥，可以接受負數，代表做空。
            margin_trading (bool): 做多部位是否使用融資
            short_selling (bool): 做空部位是否使用融券
            day_trading_long (bool): 做多部位為當沖先做多
            day_trading_short (bool): 做空部位為當沖先做空

        Examples:
            設計部位，持有一張和 100 股 1101
            ```py
            from finlab.online.order_executor import Position

            Position({'1101': 1.1})
            ```
            output
            ```json
            [
                {'stock_id': '1101',
                 'quantity': 1.1,
                 'order_condition': <OrderCondition.CASH: 1>
                }
            ]
            ```

            將兩個部位相加
            ```py
            from finlab.online.order_executor import Position

            p1 = Position({'1101': 1})
            p2 = Position({'2330': 1})
            p1 + p2
            ```
            output
            ```json
            [
                {'stock_id': '1101', 'quantity': 1.0, 'order_condition': <OrderCondition.CASH: 1>},
                {'stock_id': '2330', 'quantity': 1.0, 'order_condition': <OrderCondition.CASH: 1>}
            ]
            ```
        """
        assert margin_trading + day_trading_long <= 1
        assert short_selling + day_trading_short <= 1

        long_order_condition = OrderCondition.CASH
        short_order_condition = OrderCondition.CASH

        if margin_trading:
            long_order_condition = OrderCondition.MARGIN_TRADING
        elif day_trading_long:
            long_order_condition = OrderCondition.DAY_TRADING_LONG

        if short_selling:
            short_order_condition = OrderCondition.SHORT_SELLING
        elif day_trading_short:
            short_order_condition = OrderCondition.DAY_TRADING_SHORT

        self.position = []
        for s, a in stocks.items():
            if a != 0:
                self.position.append(
                    {'stock_id': s, 'quantity': a, 'order_condition': long_order_condition if a > 0 else short_order_condition})

    @classmethod
    def from_dict(cls, position):
        """利用 `dict` 建構股票部位


        Attributes:
            position (`list` of `dict`): 股票詳細部位
              ```py
              from finlab.online.enums import OrderCondition
              from finlab.online.order_executor import Position

              Position.from_dict(
              [{
                  'stock_id': '1101', # 股票代號
                  'quantity': 1.1, # 張數
                  'order_condition': OrderCondition.CASH # 現股融資融券、先買後賣
              }])

              ```

              其中 OrderCondition 除了 `CASH` 外，還有 `MARGIN_TRADING`、`DAY_TRADING_LONG`、`SHORT_SELLING`、`DAY_TRADING_SHORT`。

        """
        ret = cls({})
        ret.position = position
        return ret

    @classmethod
    def from_weight(cls, weights, fund, price=None, odd_lot=False, board_lot_size=1000, allocation=greedy_allocation):
        """利用 `weight` 建構股票部位

        Attributes:
            weight (`dict` of `float`): 股票詳細部位
            fund (number.Number): 資金大小
            price (pd.Series or `dict` of `float`): 股票代號對應到的價格，若無則使用最近個交易日的收盤價。
            odd_lot (bool): 是否考慮零股
            board_lot_size (int): 一張股票等於幾股
            allocation (func): 資產配置演算法（最大資金部屬貪婪法）

        Examples:
              例如，用 100 萬的資金，全部投入，持有 1101 和 2330 各一半：
              ```py
              from finlab.online.order_executor import Position

              Position.from_weight({
                  '1101': 0.5,
                  '2330': 0.5,
              }, fund=1000000)

              ```
              output
              ```
              [
                {'stock_id': '1101', 'quantity': 13, 'order_condition': <OrderCondition.CASH: 1>},
                {'stock_id': '2330', 'quantity': 1, 'order_condition': <OrderCondition.CASH: 1>}
              ]
              ```
        """

        if price is None:
            price = data.get('price:收盤價').ffill().iloc[-1]

        if isinstance(price, dict):
            price = pd.Series(price)

        if isinstance(weights, dict):
            weights = pd.Series(weights)

        if odd_lot:
            allocation = greedy_allocation(weights, price, fund)[0]
            for s, q in allocation.items():
                allocation[s] = round(q) / board_lot_size
        else:
            allocation = greedy_allocation(
                weights, price*board_lot_size, fund)[0]

        return cls(allocation)

    @classmethod
    def from_report(cls, report, fund, **kwargs):
        """利用回測完的報告 `finlab.report.Report` 建構股票部位

        Attributes:
            report (finlab.report.Report): 回測完的結果報告
            fund (int): 希望部屬的資金
            price (pd.Series or `dict` of `float`): 股票代號對應到的價格，若無則使用最近個交易日的收盤價。
            odd_lot (bool): 是否考慮零股
            board_lot_size (int): 一張股票等於幾股
            allocation (func): 資產配置演算法（最大資金部屬貪婪法）

        """

        # next trading date arrived
        tz = datetime.timezone(datetime.timedelta(hours=8))
        next_trading_time = report.next_trading_date.tz_localize(tz) + datetime.timedelta(hours=16)

        if datetime.datetime.now(tz) >= next_trading_time:
            w = report.next_weights
        else:
            w = report.weights.copy()
            w.loc[report.actions[report.actions == 'sl_tp_exit'].index] = 0

        w = w.groupby(w.index).last()

        return cls.from_weight(w, fund, **kwargs)

    def __add__(self, position):
        return self.for_each_trading_condition(self.position, position.position, "+")

    def __sub__(self, position):
        return self.for_each_trading_condition(self.position, position.position, "-")

    def sum_stock_quantity(self, stocks, oc):

        qty = {}
        for s in stocks:
            if s['order_condition'] == oc:
                q = qty.get(s['stock_id'], 0)
                qty[s['stock_id']] = q + s['quantity']

        return qty

    def for_each_trading_condition(self, p1, p2, operator):
        ret = []
        for oc in [OrderCondition.CASH,
                   OrderCondition.MARGIN_TRADING,
                   OrderCondition.SHORT_SELLING,
                   OrderCondition.DAY_TRADING_LONG,
                   OrderCondition.DAY_TRADING_SHORT]:

            qty1 = self.sum_stock_quantity(p1, oc)
            qty2 = self.sum_stock_quantity(p2, oc)

            # qty1 = {sobj['stock_id']: sobj['quantity']
            #         for sobj in p1 if sobj['order_condition'] == oc}
            # qty2 = {sobj['stock_id']: sobj['quantity']
            #         for sobj in p2 if sobj['order_condition'] == oc}

            ps = self.op(qty1, qty2, operator)
            ret += [{'stock_id': sid, 'quantity': round(
                qty, 3), 'order_condition': oc} for sid, qty in ps.items()]

        return Position.from_dict(ret)

    @staticmethod
    def op(position1, position2, operator):
        position1 = pd.Series(position1, dtype="float").astype(float)
        position2 = pd.Series(position2, dtype="float").astype(float)
        union_index = position1.index.union(position2.index)
        position1 = position1.reindex(union_index)
        position1.fillna(0, inplace=True)

        position2 = position2.reindex(union_index)
        position2.fillna(0, inplace=True)

        if operator == "-":
            ret = position1 - position2
        elif operator == "+":
            ret = position1 + position2

        ret = ret[ret != 0]

        return ret.to_dict()

    def fall_back_cash(self):
        pos = []
        for p in self.position:
            pos.append({
                'stock_id': p['stock_id'],
                'quantity': p['quantity'],
                'order_condition': OrderCondition.CASH if p['order_condition'] in [OrderCondition.DAY_TRADING_LONG, OrderCondition.DAY_TRADING_SHORT] else p['order_condition']
            })
        self.position = pos

    def __repr__(self):
        return str(self.position)


class OrderExecutor():

    def __init__(
            self, target_position, account):
        """對比實際帳戶與欲部屬的股票部位，進行同步
            Arguments:
                target_position (Position): 想要部屬的股票部位
                account (Account): 目前支援永豐與富果帳戶，請參考 Account 來實做。
        """

        if isinstance(target_position, dict):
            target_position = Position(target_position)

        self.account = account
        self.target_position = target_position

    def show_alerting_stocks(self):
        """產生下單部位是否有警示股，以及相關資訊"""

        present_position = self.account.get_position()
        new_orders = (self.target_position - present_position).position

        stock_ids = [o['stock_id'] for o in new_orders]
        stocks = self.account.get_stocks(stock_ids)
        quantity = {o['stock_id']: o['quantity'] for o in new_orders}

        res = requests.get('https://www.sinotrade.com.tw/Stock/Stock_3_8_3')
        dfs = pd.read_html(res.text)
        credit_sids = dfs[0][dfs[0]['股票代碼'].isin(stock_ids)]['股票代碼']

        res = requests.get('https://www.sinotrade.com.tw/Stock/Stock_3_8_1')
        dfs = pd.read_html(res.text)
        credit_sids = pd.concat(
            [credit_sids, dfs[0][dfs[0]['股票代碼'].isin(stock_ids)]['股票代碼'].astype(str)])
        credit_sids.name = None

        for sid in list(credit_sids.values):
            total_amount = quantity[sid]*stocks[sid].close*1000
            if quantity[sid] > 0:
                print(
                    f"買入 {sid} {quantity[sid]:>5} 張 - 總價約 {total_amount:>15.2f}")
            else:
                print(
                    f"賣出 {sid} {quantity[sid]:>5} 張 - 總價約 {total_amount:>15.2f}")

    def cancel_orders(self):
        """刪除所有未實現委託單"""
        orders = self.account.get_orders()
        for oid, o in orders.items():
            if o.status == OrderStatus.NEW or o.status == OrderStatus.PARTIALLY_FILLED:
                self.account.cancel_order(oid)

    def create_orders(self, market_order=False, best_price_limit=False, view_only=False):
        """產生委託單，將部位同步成 self.target_position"""

        present_position = self.account.get_position()
        orders = (self.target_position - present_position).position

        if view_only:
            return orders

        self.cancel_orders()
        stocks = self.account.get_stocks(list({o['stock_id'] for o in orders}))

        # make orders
        for o in orders:

            if o['quantity'] == 0:
                continue

            action = Action.BUY if o['quantity'] > 0 else Action.SELL
            price = stocks[o['stock_id']].close
            if best_price_limit:
                limit = 'LOWEST' if action == Action.BUY else 'HIGHEST'
                print('execute', action, o['stock_id'], 'X', abs(
                    o['quantity']), '@', limit, o['order_condition'])
            else:
                print('execute', action, o['stock_id'], 'X', abs(
                    o['quantity']), '@', price, o['order_condition'])

            quantity = abs(o['quantity'])
            board_lot_quantity = int(abs(quantity // 1))
            odd_lot_quantity = int(abs(round(1000 * (quantity % 1))))

            if self.account.sep_odd_lot_order():
                if odd_lot_quantity != 0:
                    self.account.create_order(action=action,
                                              stock_id=o['stock_id'],
                                              quantity=odd_lot_quantity,
                                              price=price, market_order=market_order,
                                              order_cond=o['order_condition'],
                                              odd_lot=True,
                                              best_price_limit=best_price_limit)

                if board_lot_quantity != 0:
                    self.account.create_order(action=action,
                                              stock_id=o['stock_id'],
                                              quantity=board_lot_quantity,
                                              price=price, market_order=market_order,
                                              order_cond=o['order_condition'],
                                              best_price_limit=best_price_limit)
            else:
                self.account.create_order(action=action,
                                          stock_id=o['stock_id'],
                                          quantity=quantity,
                                          price=price, market_order=market_order,
                                          order_cond=o['order_condition'],
                                          best_price_limit=best_price_limit)

    def update_order_price(self):
        """更新委託單，將委託單的限價調整成當天最後一筆價格。
        （讓沒成交的限價單去追價）"""
        orders = self.account.get_orders()
        sids = set([o.stock_id for i, o in orders.items()])
        stocks = self.account.get_stocks(sids)

        for i, o in orders.items():
            if o.status == OrderStatus.NEW or o.status == OrderStatus.PARTIALLY_FILLED:
                self.account.update_order(i, price=stocks[o.stock_id].close)
