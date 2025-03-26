from finlab.online.utils import greedy_allocation
from finlab.online.enums import *
from finlab import data
from decimal import Decimal
import pandas as pd
import requests
import datetime
import logging
import numbers
import json
import copy
import time
import math

logger = logging.getLogger(__name__)

class Position():

    """使用者可以利用 Position 輕鬆建構股票的部位，並且利用 OrderExecuter 將此部位同步於實際的股票帳戶。

    """

    def __init__(self, stocks, weights=None, margin_trading=False, short_selling=False, day_trading_long=False, day_trading_short=False):
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
                new_position = {'stock_id': s, 
                     'quantity': a, 
                     'order_condition': long_order_condition if a > 0 else short_order_condition}
                
                if weights is not None and s in weights:
                    new_position['weight'] = weights[s]

                self.position.append(new_position)
                

    @classmethod
    def from_list(cls, position):
        """利用 `dict` 建構股票部位


        Attributes:
            position (`list` of `dict`): 股票詳細部位
              ```py
              from finlab.online.enums import OrderCondition
              from finlab.online.order_executor import Position

              Position.from_list(
              [{
                  'stock_id': '1101', # 股票代號
                  'quantity': 1.1, # 張數
                  'order_condition': OrderCondition.CASH # 現股融資融券、先買後賣
              }])

              ```

              其中 OrderCondition 除了 `CASH` 外，還有 `MARGIN_TRADING`、`DAY_TRADING_LONG`、`SHORT_SELLING`、`DAY_TRADING_SHORT`。

        """
        ret = cls({})
        ret.position = ret._format_quantity(position)
        return ret
    
    def to_list(self):
        ret = []

        for p in self.position:
            pp = p.copy()
            if isinstance(pp['quantity'], Decimal):
                pp['quantity'] = str(pp['quantity'])
            ret.append(pp)

        return ret

    @classmethod
    def from_dict(cls, position):

        logger.warning('This method is renamed and will be deprecated.'
             ' Please replace `Position.from_dict()` to `Position.from_list().`')

        return cls.from_list(position)

    @classmethod
    def from_weight(cls, weights, fund, price=None, odd_lot=False, board_lot_size=1000, allocation=greedy_allocation, precision=None, **kwargs):
        """利用 `weight` 建構股票部位

        Attributes:
            weights (`dict` of `float`): 股票詳細部位
            fund (number.Number): 資金大小
            price (pd.Series or `dict` of `float`): 股票代號對應到的價格，若無則使用最近個交易日的收盤價。
            odd_lot (bool): 是否考慮零股
            board_lot_size (int): 一張股票等於幾股
            precision (int or None): 計算張數時的精度，預設為 None 代表依照 board_lot_size 而定，而 1 代表 0.1 張，2 代表 0.01 張，以此類推。
            allocation (func): 資產配置演算法選定，預設為預設為`finlab.online.utils.greedy_allocation`（最大資金部屬貪婪法）
            margin_trading (bool): 做多部位是否使用融資
            short_selling (bool): 做空部位是否使用融券
            day_trading_long (bool): 做多部位為當沖先做多
            day_trading_short (bool): 做空部位為當沖先做空

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

        if precision != None and precision < 0:
            raise ValueError("The precision parameter is out of the valid range >= 0")

        if price is None:
            price = data.get('reference_price').set_index('stock_id')['收盤價'].to_dict()

        if isinstance(price, dict):
            price = pd.Series(price)

        if isinstance(weights, dict):
            weights = pd.Series(weights)

        if precision is not None and board_lot_size != 1:
            logger.warning(
                "The precision parameter is ignored when board_lot_size is not 1.")
        
        if precision is None:
            precision = 0

        if odd_lot:
            if board_lot_size == 1000:
                precision = max(3, precision)
            elif board_lot_size == 100:
                precision = max(2, precision)
            elif board_lot_size == 10:
                precision = max(1, precision)
            elif board_lot_size == 1:
                precision = max(0, precision)
            else:
                raise ValueError(
                    "The board_lot_size parameter is out of the valid range 1, 10, 100, 1000")
            
        for idx in weights.index:
            stock_id = idx.split(' ')[0]
            if stock_id not in price:
                logger.warning(f"Stock {stock_id} is not in price data. It is dropped from the position.")
                
        weights.index = weights.index.astype(str)
        weights = weights[weights.index.str.split(' ').str[0].isin(price.index)]

        multiple = 10**precision

        allocation = greedy_allocation(
            weights, price*board_lot_size, fund*multiple)[0]
        
        for s, q in allocation.items():
            allocation[s] = Decimal(q) / multiple

        if not odd_lot:
            for s, q in allocation.items():
                allocation[s] = round(q)

        # fill zero quantity
        for s in weights.index:
            if s not in allocation:
                allocation[s] = 0

        return cls(allocation, weights=weights, **kwargs)

    @classmethod
    def from_report(cls, report, fund, **kwargs):
        """利用回測完的報告 `finlab.report.Report` 建構股票部位。

        Attributes:
            report (finlab.report.Report): 回測完的結果報告。
            fund (int): 希望部屬的資金。
            price (pd.Series or `dict` of `float`): 股票代號對應到的價格，若無則使用最近個交易日的收盤價。
            odd_lot (bool): 是否考慮零股。預設為 False，只使用整張操作。
            board_lot_size (int): 一張股票等於幾股。預設為1000，一張等於1000股。
            allocation (func): 資產配置演算法選定，預設為`finlab.online.utils.greedy_allocation`（最大資金部屬貪婪法）。
        !!! example
            ```py
            from finlab import backtest
            from finlab.online.order_executor import Position

            report1 = backtest.sim(...)
            report2 = backtest.sim(...)

            position1 = Position.from_report(report1, 1000000) # 策略操作金額一百萬
            position2 = Position.from_report(report2, 1000000) # 策略操作金額一百萬

            total_position = position1 + position2
            ```
        """

        from finlab.portfolio.cloud_report import CloudReport
        if isinstance(report, CloudReport):
            position_schedulers = report.position_schedulers
            if isinstance(position_schedulers, dict):
                raise ValueError("The report contains multiple position. Please use `finlab.portfolio.Portfolio` to handle it.")
            else:
                report = position_schedulers


        # next trading date arrived

        if hasattr(report.market, 'market_close_at_timestamp'):
            next_trading_time = report.market.market_close_at_timestamp(report.next_trading_date)

            # check next_trading_time is tz aware
            if next_trading_time.tzinfo is None:
                raise ValueError("Output from market.market_close_at_timestamp should be timezone aware datetime object.")
        else:
            # tw stock only
            tz = datetime.timezone(datetime.timedelta(hours=8))
            next_trading_time = report.next_trading_date.tz_localize(tz) + datetime.timedelta(hours=16)

        now = datetime.datetime.now(tz=datetime.timezone.utc)

        if now >= next_trading_time:
            w = report.next_weights.copy()
        else:
            w = report.weights.copy()

        ###################################
        # handle stoploss and takeprofit
        ###################################

        is_sl_tp = report.actions.isin(['sl_', 'tp_','sl', 'tp'])

        if sum(is_sl_tp):
            exit_stocks = report.actions[is_sl_tp].index.intersection(w.index)
            w.loc[exit_stocks] = 0

        ######################################################
        # handle exit now and enter in next trading date
        ######################################################

        is_exit_enter = report.actions.isin(['sl_enter', 'tp_enter'])
        if sum(is_exit_enter) and now < next_trading_time:
            exit_stocks = report.actions[is_exit_enter].index.intersection(w.index)
            w.loc[exit_stocks] = 0

        # todo: check if w.index is unique and remove this line if possible
        w = w.groupby(w.index.tolist()).last()

        if 'price' not in kwargs:
            if hasattr(report.market, 'get_reference_price'):
                price = report.market.get_reference_price()

            else:
                price = report.market.get_price('close', adj=False).iloc[-1].to_dict()

            kwargs['price'] = price

        if hasattr(report.market, 'get_board_lot_size'):
            kwargs['board_lot_size'] = report.market.get_board_lot_size()
        
        # find w.index not in price.keys()
        # import pdb; pdb.set_trace()
        for s in w.index.tolist():
            if s.split(' ')[0] not in kwargs['price'] or kwargs['price'][s.split(' ')[0]] != kwargs['price'][s.split(' ')[0]]:
                w = w.drop(s)
                logger.warning(f"Stock {s} is not in price data. It is dropped from the position.")

        return cls.from_weight(w, fund, **kwargs)
    

    def to_json(self, path):
        """
        Converts the position dictionary to a JSON file and saves it to the specified path.
        
        Args:
            path (str): The path where the JSON file will be saved.
            
        Returns:
            None
        """
        
        # Custom JSON Encoder that handles Decimal objects
        class DecimalEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, Decimal):
                    return str(obj)  # Convert Decimal to string
                # Let the base class default method raise the TypeError
                return json.JSONEncoder.default(self, obj)
            
        with open(path, 'w') as f:
            json.dump(self.position, f, cls=DecimalEncoder)


    @staticmethod
    def _format_quantity(position):

        ret = []
        for p in position:
            pp = p.copy()
            if isinstance(pp['quantity'], str):
                pp['quantity'] = Decimal(pp['quantity'])
            ret.append(pp)
        return ret
            
    
    @classmethod
    def from_json(self, path):
        """
        Load a JSON file from the given path and convert it to a list of positions.
        
        Args:
            path (str): The path to the JSON file.
        
        Returns:
            None
        """
        
        with open(path, 'r') as f:
            ret = json.load(f)
            ret = self._format_quantity(ret)

        return Position.from_list(ret)

    def __add__(self, position):
        return self.for_each_trading_condition(self.position, position.position, "+")

    def __sub__(self, position):
        return self.for_each_trading_condition(self.position, position.position, "-")
    
    def __eq__(self, position):
        return self.position == position.position
    
    def __mul__(self, scalar):

        if self.has_weight(self.position):
            return Position.from_list([{**p, 'quantity': p['quantity']*scalar,
                                       'weight': p['weight']*scalar} for p in self.position])
        
        return Position.from_list([{**p, 'quantity': p['quantity']*scalar,
                                    } for p in self.position])
    
    def __rmul__(self, scalar):
        return self.__mul__(scalar)
    
    def __truediv__(self, scalar):
        return self.__mul__(1/scalar)
    
    def __rtruediv__(self, scalar):
        return self.__truediv__(scalar)

    def sum_stock_quantity(self, stocks, oc, attr='quantity'):

        qty = {}
        for s in stocks:
            if s['order_condition'] == oc:
                q = qty.get(s['stock_id'], 0)
                qty[s['stock_id']] = q + s.get(attr, 0)

        return qty
    
    @staticmethod
    def has_weight(position:list) -> bool:
        if len(position) == 0:
            return True
        for p in position:
            if 'weight' in p:
                return True
        return False

    def for_each_trading_condition(self, p1, p2, operator):
        ret = []
        for oc in [OrderCondition.CASH,
                   OrderCondition.MARGIN_TRADING,
                   OrderCondition.SHORT_SELLING,
                   OrderCondition.DAY_TRADING_LONG,
                   OrderCondition.DAY_TRADING_SHORT]:

            qty1 = self.sum_stock_quantity(p1, oc)
            qty2 = self.sum_stock_quantity(p2, oc)

            ps = self.op(qty1, qty2, operator)
            new_pos = [{'stock_id': sid, 'quantity': qty,
                'order_condition': oc} for sid, qty in ps.items()]
            
            if self.has_weight(p1) and self.has_weight(p2):

                w1 = self.sum_stock_quantity(p1, oc, attr='weight')
                w2 = self.sum_stock_quantity(p2, oc, attr='weight')
                ws = self.op(w1, w2, operator)
                for p in new_pos:
                    p['weight'] = ws.get(p['stock_id'], 0)

            ret += new_pos

        return Position.from_list(ret)

    @staticmethod
    def op(position1, position2, operator):
        # Create a set of unique keys from both dictionaries
        keys = set(position1.keys()).union(position2.keys())
        
        # Initialize an empty result dictionary
        result = {}
        
        for key in keys:
            value1 = position1.get(key, 0)
            value2 = position2.get(key, 0)

            # convert to float if value1 or value2 is float or int
            if (isinstance(value1, (float, int)) and value1 != 0)\
                  or (isinstance(value2, (float, int)) and value2 != 0):
                value1 = float(value1)
                value2 = float(value2)

            # fallback to float if value1 or value2 is Decimal
            if type(value1) != type(value2):
                value1 = float(value1)
                value2 = float(value2)
            
            if operator == "-":
                result[key] = value1 - value2
            elif operator == "+":
                result[key] = value1 + value2
        
        # Remove entries with zero values
        result = {k: v for k, v in result.items() if v != 0}
        
        return result

    def fall_back_cash(self):
        pos = []
        for p in self.position:
            pos.append({
                'stock_id': p['stock_id'],
                'quantity': p['quantity'],
                'order_condition': OrderCondition.CASH if p['order_condition'] in [OrderCondition.DAY_TRADING_LONG, OrderCondition.DAY_TRADING_SHORT] else p['order_condition']
            })
        self.position = pos

    def to_df(self):
        return pd.DataFrame(self.position)\
            .pipe(lambda df: df.assign(
                order_condition=df.order_condition\
                    .map(lambda x: OrderCondition._member_names_[x-1])))\
            .sort_values('stock_id')

    def __repr__(self):

        if len(self.position) == 0:
            return 'empty position'

        return self.to_df().to_string(index=False)

    def __iter__(self):
        return iter(self.position)

class OrderExecutor():

    def __init__(
            self, target_position, account):
        """對比實際帳戶與欲部屬的股票部位，進行同步
            Arguments:
                target_position (Position): 想要部屬的股票部位。
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
        quantity = {o['stock_id']: o['quantity'] for o in new_orders}

        res = requests.get('https://www.sinotrade.com.tw/Stock/Stock_3_8_3')
        dfs = pd.read_html(res.text)
        credit_sids = dfs[0][dfs[0]['股票代碼'].astype(str).isin(stock_ids)]['股票代碼']

        res = requests.get('https://www.sinotrade.com.tw/Stock/Stock_3_8_1')
        dfs = pd.read_html(res.text)
        credit_sids = pd.concat(
            [credit_sids, dfs[0][dfs[0]['股票代碼'].astype(str).isin(stock_ids)]['股票代碼'].astype(str)])
        credit_sids.name = None

        if credit_sids.any():
            close = data.get('price:收盤價').ffill().iloc[-1]
            for sid in list(credit_sids.values):
                quantity[sid] = float(quantity[sid])
                if quantity[sid] > 0:
                    total_amount = quantity[sid]*close[sid]*1000*1.1
                    print(
                        f"買入 {sid} {quantity[sid]:>5} 張 - 總價約 {total_amount:>15.2f}")
                else:
                    total_amount = quantity[sid]*close[sid]*1000*0.9
                    print(
                        f"賣出 {sid} {quantity[sid]:>5} 張 - 總價約 {total_amount:>15.2f}")

    def cancel_orders(self):
        """刪除所有未實現委託單"""
        orders = self.account.get_orders()
        for oid, o in orders.items():
            if o.status == OrderStatus.NEW or o.status == OrderStatus.PARTIALLY_FILLED:
                self.account.cancel_order(oid)

    def generate_orders(self, progress=1, progress_precision=0):
        """
        Generate orders based on the difference between target position and present position.
        
        Returns:
        orders (dict): Orders to be executed.
        """

        target_position = Position.from_list(copy.copy(self.target_position.position))

        if hasattr(self.account, 'base_currency'):
            base_currency = self.account.base_currency
            for pp in target_position.position:
                if pp['stock_id'][-len(base_currency):] == base_currency:
                    pp['stock_id'] = pp['stock_id'][:-len(base_currency)]
                else:
                    raise ValueError(f"Stock ID {pp['stock_id']} does not end with {base_currency}")

        present_position = self.account.get_position()
        orders = (target_position - present_position)
        if progress != 1:
            if not (progress >= 0 and progress <= 1):
                raise ValueError("progress should be in the range of 0 to 1")
            if progress_precision is None:
                raise ValueError("progress_precision should be set when progress is not 1")
            
            orders = Position.from_list([{**o, 'quantity': round(float(o['quantity'])*progress, progress_precision)} for o in orders.position])

        return orders.position
    
    def execute_orders(self, orders, market_order=False, best_price_limit=False, view_only=False, extra_bid_pct=0, cancel_orders=True, buy_only=False, sell_only=False):
        """產生委託單，將部位同步成 self.target_position
        預設以該商品最後一筆成交價設定為限價來下單
        
        Attributes:
            orders (list): 欲下單的部位，通常是由 `self.generate_orders` 產生。
            market_order (bool): 以類市價盡量即刻成交：所有買單掛漲停價，所有賣單掛跌停價
            best_price_limit (bool): 掛芭樂價：所有買單掛跌停價，所有賣單掛漲停價
            view_only (bool): 預設為 False，會實際下單。若設為 True，不會下單，只會回傳欲執行的委託單資料(dict)
            extra_bid_pct (float): 以該百分比值乘以價格進行追價下單，如設定為 0.05 時，將以當前價的 +(-)5% 的限價進買入(賣出)，也就是更有機會可以成交，但是成交價格可能不理想；
                假如設定為 -0.05 時，將以當前價的 -(+)5% 進行買入賣出，也就是限價單將不會立即成交，然而假如成交後，價格比較理想。參數有效範圍為 -0.1 到 0.1 內。
            buy_only (bool): 若設為 True，只下買單
            sell_only (bool): 若設為 True，只下賣單
        """

        if [market_order, best_price_limit, bool(extra_bid_pct)].count(True) > 1:
            raise ValueError("Only one of 'market_order', 'best_price_limit', or 'extra_bid_pct' can be set.")
        if extra_bid_pct < -0.1 or extra_bid_pct > 0.1:
            raise ValueError("The extra_bid_pct parameter is out of the valid range 0 to 0.1")
        if buy_only and sell_only:
            raise ValueError("The buy_only and sell_only parameters cannot be set to True at the same time.")

        if cancel_orders:
            self.cancel_orders()

        stocks = self.account.get_stocks(list({o['stock_id'] for o in orders}))

        pinfo = None
        if hasattr(self.account, 'get_price_info'):
            pinfo = self.account.get_price_info()

        # make orders
        for o in orders:

            if o['quantity'] == 0:
                continue

            action = Action.BUY if o['quantity'] > 0 else Action.SELL
            
            if buy_only and action == Action.SELL:
                continue

            if sell_only and action == Action.BUY:
                continue
            
            if o['stock_id'] not in stocks:
                logging.warning(o['stock_id'] + 'not in stocks... skipped!')
                continue

            stock = stocks[o['stock_id']]
            price = stock.close if isinstance(stock.close, numbers.Number) else (
                    stock.bid_price if action == Action.BUY else stock.ask_price
                    )

            if extra_bid_pct != 0:
                price = calculate_price_with_extra_bid(price, extra_bid_pct if action == Action.BUY else -extra_bid_pct)

            if pinfo and o['stock_id'] in pinfo:
                limitup = float(pinfo[o['stock_id']]['漲停價'])
                limitdn = float(pinfo[o['stock_id']]['跌停價'])
                price = max(price, limitdn)
                price = min(price, limitup)
            else:
                logger.warning('No price info for stock %s', o['stock_id'])

            if isinstance(price, Decimal):
                price = format(price, 'f')

            if best_price_limit:
                price_string = 'LOWEST' if action == Action.BUY else 'HIGHEST'
            elif market_order:
                price_string = 'HIGHEST' if action == Action.BUY else 'LOWEST'
            else:
                price_string = str(price)

            extra_bid_text = ''
            if extra_bid_pct > 0:
                extra_bid_text = f'with extra bid {extra_bid_pct*100}%'

            # logger.warning('%-11s %-6s X %-10s @ %-11s %s %s', action, o['stock_id'], abs(o['quantity']), price_string, extra_bid_text, o['order_condition'])
            # use print f-string format instead of logger
            action_str = 'BUY' if action == Action.BUY else 'SELL'
            order_condition_str = 'CASH' if o['order_condition'] == OrderCondition.CASH else 'MARGIN_TRADING' if o['order_condition'] == OrderCondition.MARGIN_TRADING else 'SHORT_SELLING' if o['order_condition'] == OrderCondition.SHORT_SELLING else 'DAY_TRADING_LONG' if o['order_condition'] == OrderCondition.DAY_TRADING_LONG else 'DAY_TRADING_SHORT' if o['order_condition'] == OrderCondition.DAY_TRADING_SHORT else 'UNKNOWN'
            print(f'{action_str:<11} {o["stock_id"]:10} X {round(abs(o["quantity"]), 3):<10} @ {price_string:<11} {extra_bid_text} {order_condition_str}')


            quantity = abs(o['quantity'])
            board_lot_quantity = int(abs(quantity // 1))
            odd_lot_quantity = int(abs(round(1000 * (quantity % 1))))

            if view_only:
                continue

            if self.account.sep_odd_lot_order():
                if odd_lot_quantity != 0:
                    self.account.create_order(action=action,
                                              stock_id=o['stock_id'],
                                              quantity=odd_lot_quantity,
                                              price=price, market_order=market_order,
                                              order_cond=o['order_condition'],
                                              odd_lot=True,
                                              best_price_limit=best_price_limit,
                                              )

                if board_lot_quantity != 0:
                    self.account.create_order(action=action,
                                              stock_id=o['stock_id'],
                                              quantity=board_lot_quantity,
                                              price=price, market_order=market_order,
                                              order_cond=o['order_condition'],
                                              best_price_limit=best_price_limit,
                                              )
            else:
                self.account.create_order(action=action,
                                          stock_id=o['stock_id'],
                                          quantity=quantity,
                                          price=price, market_order=market_order,
                                          order_cond=o['order_condition'],
                                          best_price_limit=best_price_limit,
                                          )
                
        return orders


    def create_orders(self, market_order=False, best_price_limit=False, view_only=False, extra_bid_pct=0, progress=1, progress_precision=0, buy_only=False, sell_only=False):
        """產生委託單，將部位同步成 self.target_position
        預設以該商品最後一筆成交價設定為限價來下單
        
        Attributes:
            market_order (bool): 以類市價盡量即刻成交：所有買單掛漲停價，所有賣單掛跌停價
            best_price_limit (bool): 掛芭樂價：所有買單掛跌停價，所有賣單掛漲停價
            view_only (bool): 預設為 False，會實際下單。若設為 True，不會下單，只會回傳欲執行的委託單資料(dict)
            extra_bid_pct (float): 以該百分比值乘以價格進行追價下單，如設定為 0.05 時，將以當前價的 +(-)5% 的限價進買入(賣出)，也就是更有機會可以成交，但是成交價格可能不理想；
                假如設定為 -0.05 時，將以當前價的 -(+)5% 進行買入賣出，也就是限價單將不會立即成交，然而假如成交後，價格比較理想。參數有效範圍為 -0.1 到 0.1 內。
            progress (float): 進度，預設為 1，即全部下單。若設定為 0.5，則只下一半的單。
            progress_precision (int): 進度的精度，預設為 0，即只下整數張。若設定為 1，則下到 0.1 張。
            buy_only (bool): 若設為 True，只下買單
            sell_only (bool): 若設為 True，只下賣單
        """
        self.cancel_orders()
        orders = self.generate_orders(progress, progress_precision)
        return self.execute_orders(orders, market_order, best_price_limit, view_only, extra_bid_pct, cancel_orders=False, buy_only=buy_only, sell_only=sell_only)
    
    
    def update_order_price(self, extra_bid_pct=0):
        """更新委託單，將委託單的限價調整成當天最後一筆價格。
        （讓沒成交的限價單去追價）
        Attributes:
            extra_bid_pct (float): 以該百分比值乘以價格進行追價下單，如設定為 0.1 時，將以超出(低於)現價之10%價格下單，以漲停(跌停)價為限。參數有效範圍為 0 到 0.1 內
            """
        if extra_bid_pct < -0.1 or extra_bid_pct > 0.1:
            raise ValueError("The extra_bid_pct parameter is out of the valid range 0 to 0.1")
        orders = self.account.get_orders()
        sids = set([o.stock_id for i, o in orders.items()])
        stocks = self.account.get_stocks(sids)

        pinfo = None
        if hasattr(self.account, 'get_price_info'):
            pinfo = self.account.get_price_info()

        for i, o in orders.items():
            if o.status == OrderStatus.NEW or o.status == OrderStatus.PARTIALLY_FILLED:

                price = stocks[o.stock_id].close

                if o.price == price:
                    continue
                
                price = calculate_price_with_extra_bid(price, extra_bid_pct if o.action == Action.BUY else -extra_bid_pct)

                if pinfo and o.stock_id in pinfo:
                    up_limit = float(pinfo[o.stock_id]['漲停價'])
                    dn_limit = float(pinfo[o.stock_id]['跌停價'])
                    price = max(price, dn_limit)
                    price = min(price, up_limit)
                else:
                    logger.warning('No price info for stock %s', o.stock_id)

                self.account.update_order(i, price=price)


    def get_order_info(self):

        def calc_order_info(oe):
            target = oe.target_position
            current = oe.account.get_position()
            return {
                'target': target.to_list(),
                'current': current.to_list(),
                'orders': (target - current).to_list()
            }

        def get_symbols(orders):
            return [(o['stock_id'], str(o['order_condition'])) for o in orders]


        def find_symbols(orders, symbol):
            ret = [o for o in orders if o['stock_id'] == symbol]
            if len(ret) == 0:
                return {'quantity': 0, 'symbol': symbol[0], 'order_condition': symbol[1]}
            return ret[0]

        orders = calc_order_info(self)
        symbols = sorted(list(set(get_symbols(orders['target']) + get_symbols(orders['current']))))
        stocks = self.account.get_stocks(list(set([s[0] for s in symbols])))

        order_info = []
        for s in symbols:
            pqty = float(find_symbols(orders['current'], s[0])['quantity'])
            tqty = float(find_symbols(orders['target'], s[0])['quantity'])
            order_info.append({
                'price': stocks[s[0]].close,
                'current_qty': pqty,
                'target_qty': tqty,
                'order_qty': tqty - pqty,
                'symbol': s[0],
                'order_condition': s[1],
                })
                
        return sorted(order_info, key=lambda x: x['order_qty'] * x['price'], reverse=True)
                

def calculate_price_with_extra_bid(price, extra_bid_pct):

    if extra_bid_pct == 0:
        return price

    if extra_bid_pct > 0:
        result = price * (1 + extra_bid_pct)
        if result <= 10:
            result = math.floor(round(result, 3) * 100) / 100
        elif result <= 50:
            result = math.floor(result * 20) / 20
        elif result <= 100:
            result = math.floor(result * 10) / 10
        elif result <= 500:
            result = math.floor(result * 2) / 2
        elif result <= 1000:
            result = math.floor(result)
        else:
            result = math.floor(result / 5) * 5
    else:
        result = price * (1 + extra_bid_pct)
        if result <= 10:
            result = math.ceil(round(result, 3) * 100) / 100
        elif result <= 50:
            result = math.ceil(result * 20) / 20
        elif result <= 100:
            result = math.ceil(result * 10) / 10
        elif result <= 500:
            result = math.ceil(result * 2) / 2
        elif result <= 1000:
            result = math.ceil(result)
        else:
            result = math.ceil(result / 5) * 5

    return result