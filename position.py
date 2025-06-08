from finlab.online.utils import greedy_allocation
from finlab.online.enums import *
from decimal import Decimal
from typing import Union
from finlab import config
import pandas as pd
import numpy as np
import datetime
import logging
import math
import json

logger = logging.getLogger(__name__)


class Position:
    """使用者可以利用 Position 輕鬆建構股票的部位，並且利用 OrderExecuter 將此部位同步於實際的股票帳戶。"""

    def __init__(
        self,
        stocks,
        weights=None,
        margin_trading=False,
        short_selling=False,
        day_trading_long=False,
        day_trading_short=False,
    ):
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
                new_position = {
                    "stock_id": s,
                    "quantity": a,
                    "order_condition": (
                        long_order_condition if a > 0 else short_order_condition
                    ),
                }

                if weights is not None and s in weights:
                    new_position["weight"] = weights[s]

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
            if isinstance(pp["quantity"], Decimal):
                pp["quantity"] = str(pp["quantity"])
            ret.append(pp)

        return ret

    @classmethod
    def from_dict(cls, position):

        logger.warning(
            "This method is renamed and will be deprecated."
            " Please replace `Position.from_dict()` to `Position.from_list().`"
        )

        return cls.from_list(position)

    @classmethod
    def from_weight(
        cls,
        weights: Union[dict[str, float], pd.Series],
        fund: int,
        price: Union[None, pd.Series, dict[str, float]] = None,
        odd_lot: bool = False,
        board_lot_size: Union[None, int] = None,
        allocation=greedy_allocation,
        precision: Union[None, int] = None,
        leverage: float = 1.0,
        price_history: Union[None, pd.DataFrame] = None,
        **kwargs,
    ):
        """利用 `weight` 建構股票部位

        Attributes:
            weights (dict[str, float] 或 pd.Series): 股票詳細部位，股票代號對應權重
            fund (int): 資金大小
            price (None 或 pd.Series 或 dict[str, float]): 股票代號對應到的價格，若無則使用最近個交易日的收盤價。
            odd_lot (bool): 是否考慮零股
            board_lot_size (None 或 int): 一張股票等於幾股
            allocation (function): 資產配置演算法選定，預設為`finlab.online.utils.greedy_allocation`（最大資金部屬貪婪法）
            precision (None 或 int): 計算張數時的精度，預設為 None 代表依照 board_lot_size 而定，而 1 代表 0.1 張，2 代表 0.01 張，以此類推。
            leverage (float): 目標槓桿倍數，預設為1.0（不使用融資）。若>1.0，會根據波動度分配融資。
            price_history (None 或 pd.DataFrame): 股票歷史價格，若 leverage > 1.0 時必須提供。
            margin_trading (bool): 做多部位是否使用融資
            short_selling (bool): 做空部位是否使用融券
            day_trading_long (bool): 做多部位為當沖先做多

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

        if board_lot_size is None:
            market = config.get_market()
            board_lot_size = market.get_board_lot_size()

            if board_lot_size is None:
                raise ValueError(
                    "board_lot_size must be provided or market.get_board_lot_size() must return a valid value."
                )

        if precision != None and precision < 0:
            raise ValueError("The precision parameter is out of the valid range >= 0")

        if price is None:
            market = config.get_market()
            price = market.get_reference_price()

        if isinstance(price, dict):
            price = pd.Series(price)

        if price is None:
            raise ValueError("price must be provided")

        if isinstance(weights, dict):
            weights = pd.Series(weights)

        if precision is not None and board_lot_size != 1:
            logger.warning(
                "The precision parameter is ignored when board_lot_size is not 1."
            )

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
                    "The board_lot_size parameter is out of the valid range 1, 10, 100, 1000"
                )

        for idx in weights.index:
            stock_id = idx.split(" ")[0]
            if stock_id not in price:
                logger.warning(
                    f"Stock {stock_id} is not in price data. It is dropped from the position."
                )

        weights.index = weights.index.astype(str)
        weights = weights[weights.index.str.split(" ").str[0].isin(price.index)]

        multiple = 10**precision

        effective_fund = fund * leverage if leverage > 1.0 else fund

        allocation = greedy_allocation(
            weights, price * board_lot_size, effective_fund * multiple
        )[0]

        for s, q in allocation.items():
            allocation[s] = Decimal(q) / multiple

        if not odd_lot:
            for s, q in allocation.items():
                allocation[s] = round(q)

        # fill zero quantity
        for s in weights.index:
            if s not in allocation:
                allocation[s] = 0

        pos = cls(allocation, weights=weights, **kwargs)

        if leverage > 1.0:
            if price_history is None:
                raise ValueError("price_history must be provided when leverage > 1.0")
            pos = cls._apply_leverage_to_position(
                pos, price, price_history, leverage, board_lot_size
            )
        return pos

    @staticmethod
    def _apply_leverage_to_position(
        position,
        price,
        price_history,
        leverage,
        board_lot_size=1000,
        annualisation_factor=252,
    ):
        """
        Return a *new* Position whose cash + margin legs reach target leverage.
        Safety: allocate margin to lowest-volatility holdings first.
        """
        # Latest price per share
        last_px = price
        # Volatility per symbol
        vol = price_history.pct_change().std() * math.sqrt(annualisation_factor)
        orig = position.to_list()
        rows = []
        for p in orig:
            sid = p["stock_id"]
            qty = Decimal(p["quantity"])
            if qty <= 0:
                continue
            if sid not in last_px or sid not in vol:
                continue
            value = float(qty) * board_lot_size * float(last_px[sid])
            rows.append(
                {
                    "stock_id": sid,
                    "quantity": qty,
                    "value": value,
                    "sigma": float(vol[sid]),
                    "weight": p.get("weight"),
                }
            )
        if not rows:
            raise ValueError("Empty or incompatible position – nothing to leverage.")
        df = pd.DataFrame(rows)
        total_val = df["value"].sum()
        target_finance = (leverage - 1.0) / leverage * total_val
        df = df.sort_values("sigma", kind="mergesort")
        finance_remaining = target_finance
        new_entries = []
        for _, row in df.iterrows():
            sid = row.stock_id
            qty = row.quantity
            value = row.value
            base_entry = {
                "stock_id": sid,
                "weight": row.weight,
            }
            if finance_remaining <= 0:
                new_entries.append(
                    {
                        **base_entry,
                        "quantity": qty,
                        "order_condition": OrderCondition.CASH,
                    }
                )
                continue
            if value <= finance_remaining + 1e-6:
                new_entries.append(
                    {
                        **base_entry,
                        "quantity": qty,
                        "order_condition": OrderCondition.MARGIN_TRADING,
                    }
                )
                finance_remaining -= value
            else:
                frac = Decimal(finance_remaining / value)
                lots_margin = (frac * 10).quantize(
                    Decimal("1."), rounding="ROUND_CEILING"
                ) / 10
                lots_margin = min(lots_margin, qty)
                lots_cash = qty - lots_margin
                if lots_margin > 0:
                    new_entries.append(
                        {
                            **base_entry,
                            "quantity": lots_margin,
                            "order_condition": OrderCondition.MARGIN_TRADING,
                        }
                    )
                if lots_cash > 0:
                    new_entries.append(
                        {
                            **base_entry,
                            "quantity": lots_cash,
                            "order_condition": OrderCondition.CASH,
                        }
                    )
                finance_remaining = 0
        for p in orig:
            if p["quantity"] <= 0 or p["order_condition"] not in [OrderCondition.CASH]:
                new_entries.append(p)
        return Position.from_list(new_entries)

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
            margin_trading (bool): 做多部位是否使用融資
            short_selling (bool): 做空部位是否使用融券
            day_trading_long (bool): 做多部位為當沖先做多
            day_trading_short (bool): 做空部位為當沖先做空
            leverage (float): 目標槓桿倍數，預設為1.0（不使用融資）。若>1.0，會根據波動度分配融資。

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
                raise ValueError(
                    "The report contains multiple position. Please use `finlab.portfolio.Portfolio` to handle it."
                )
            else:
                report = position_schedulers

        # next trading date arrived

        if hasattr(report.market, "market_close_at_timestamp"):
            next_trading_time = report.market.market_close_at_timestamp(
                report.next_trading_date
            )

            # check next_trading_time is tz aware
            if next_trading_time.tzinfo is None:
                raise ValueError(
                    "Output from market.market_close_at_timestamp should be timezone aware datetime object."
                )
        else:
            # tw stock only
            tz = datetime.timezone(datetime.timedelta(hours=8))
            next_trading_time = pd.Timestamp(report.next_trading_date).tz_localize(
                tz
            ) + datetime.timedelta(hours=16)

        now = datetime.datetime.now(tz=datetime.timezone.utc)

        if now >= next_trading_time:
            w = report.next_weights.copy()
        else:
            w = report.weights.copy()

        ###################################
        # handle stoploss and takeprofit
        ###################################

        is_sl_tp = report.actions.isin(["sl_", "tp_", "sl", "tp"])

        if sum(is_sl_tp):
            exit_stocks = report.actions[is_sl_tp].index.intersection(w.index.tolist())
            w.loc[exit_stocks] = 0

        ######################################################
        # handle exit now and enter in next trading date
        ######################################################

        is_exit_enter = report.actions.isin(["sl_enter", "tp_enter"])
        if sum(is_exit_enter) and now < next_trading_time:
            exit_stocks = report.actions[is_exit_enter].index.intersection(w.index.tolist())
            w.loc[exit_stocks] = 0

        # todo: check if w.index is unique and remove this line if possible
        w = w.groupby(w.index.tolist()).last()

        if "price" not in kwargs:
            if hasattr(report.market, "get_reference_price"):
                price = report.market.get_reference_price()

            else:
                price = report.market.get_price("close", adj=False).iloc[-1].to_dict()

            kwargs["price"] = price

        if hasattr(report.market, "get_board_lot_size"):
            kwargs["board_lot_size"] = report.market.get_board_lot_size()

        if "leverage" in kwargs:
            kwargs["historical_price"] = (
                report.market.get_price("close", adj=True).iloc[-252:].copy()
            )

        # find w.index not in price.keys()
        # import pdb; pdb.set_trace()
        for s in w.index.tolist():
            if (
                s.split(" ")[0] not in kwargs["price"]
                or kwargs["price"][s.split(" ")[0]] != kwargs["price"][s.split(" ")[0]]
            ):
                w = w.drop(s)
                logger.warning(
                    f"Stock {s} is not in price data. It is dropped from the position."
                )

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
            def default(self, o):
                if isinstance(o, Decimal):
                    return str(o)  # Convert Decimal to string
                # Let the base class default method raise the TypeError
                return json.JSONEncoder.default(self, o)

        with open(path, "w") as f:
            json.dump(self.position, f, cls=DecimalEncoder)

    @staticmethod
    def _format_quantity(position):

        ret = []
        for p in position:
            pp = p.copy()
            if isinstance(pp["quantity"], str):
                pp["quantity"] = Decimal(pp["quantity"])
            ret.append(pp)
        return ret

    @classmethod
    def from_json(cls, path):
        """
        Load a JSON file from the given path and convert it to a list of positions.

        Args:
            path (str): The path to the JSON file.

        Returns:
            None
        """

        with open(path, "r") as f:
            ret = json.load(f)
            ret = cls._format_quantity(ret)

        return Position.from_list(ret)

    def __add__(self, position):
        return self.for_each_trading_condition(self.position, position.position, "+")

    def __sub__(self, position):
        return self.for_each_trading_condition(self.position, position.position, "-")

    def __eq__(self, position):
        return self.position == position.position

    def __mul__(self, scalar):

        if self.has_weight(self.position):
            return Position.from_list(
                [
                    {
                        **p,
                        "quantity": p["quantity"] * scalar,
                        "weight": p["weight"] * scalar,
                    }
                    for p in self.position
                ]
            )

        return Position.from_list(
            [
                {
                    **p,
                    "quantity": p["quantity"] * scalar,
                }
                for p in self.position
            ]
        )

    def __rmul__(self, scalar):
        return self.__mul__(scalar)

    def __truediv__(self, scalar):
        return self.__mul__(1 / scalar)

    def __rtruediv__(self, scalar):
        return self.__truediv__(scalar)

    def sum_stock_quantity(self, stocks, oc, attr="quantity"):

        qty = {}
        for s in stocks:
            if s["order_condition"] == oc:
                q = qty.get(s["stock_id"], 0)
                qty[s["stock_id"]] = q + s.get(attr, 0)

        return qty

    @staticmethod
    def has_weight(position: list) -> bool:
        if len(position) == 0:
            return True
        for p in position:
            if "weight" in p:
                return True
        return False

    def for_each_trading_condition(self, p1, p2, operator):
        ret = []
        for oc in [
            OrderCondition.CASH,
            OrderCondition.MARGIN_TRADING,
            OrderCondition.SHORT_SELLING,
            OrderCondition.DAY_TRADING_LONG,
            OrderCondition.DAY_TRADING_SHORT,
        ]:

            qty1 = self.sum_stock_quantity(p1, oc)
            qty2 = self.sum_stock_quantity(p2, oc)

            ps = self.op(qty1, qty2, operator)
            new_pos = [
                {"stock_id": sid, "quantity": qty, "order_condition": oc}
                for sid, qty in ps.items()
            ]

            if self.has_weight(p1) and self.has_weight(p2):

                w1 = self.sum_stock_quantity(p1, oc, attr="weight")
                w2 = self.sum_stock_quantity(p2, oc, attr="weight")
                ws = self.op(w1, w2, operator)
                for p in new_pos:
                    p["weight"] = ws.get(p["stock_id"], 0)

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
            if (isinstance(value1, (float, int)) and value1 != 0) or (
                isinstance(value2, (float, int)) and value2 != 0
            ):
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
            pos.append(
                {
                    "stock_id": p["stock_id"],
                    "quantity": p["quantity"],
                    "order_condition": (
                        OrderCondition.CASH
                        if p["order_condition"]
                        in [
                            OrderCondition.DAY_TRADING_LONG,
                            OrderCondition.DAY_TRADING_SHORT,
                        ]
                        else p["order_condition"]
                    ),
                }
            )
        self.position = pos

    def to_df(self):
        return (
            pd.DataFrame(self.position)
            .pipe(
                lambda df: df.assign(
                    order_condition=df.order_condition.map(
                        lambda x: OrderCondition._member_names_[x - 1]
                    )
                )
            )
            .sort_values("stock_id")
        )

    def __repr__(self):

        if len(self.position) == 0:
            return "empty position"

        return self.to_df().to_string(index=False)

    def __iter__(self):
        return iter(self.position)
