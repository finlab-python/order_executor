from __future__ import annotations

import imp
from typing import Any

import ipywidgets as widgets
import pandas as pd
from IPython.display import display

from finlab import data
from finlab.compat import resolve_position_entry_symbol
from finlab.online import enums, order_executor
from finlab.online.order_executor import OrderExecutor, Position

imp.reload(order_executor)


def get_strategy_display_name(strategies: dict[str, Any], strategy_id: str) -> str:
    sd = strategies.get(strategy_id)
    if isinstance(sd, dict):
        data_obj = sd.get("data")
        if isinstance(data_obj, dict):
            name = data_obj.get("name")
            if isinstance(name, str) and name:
                return name
    return str(strategy_id)


def get_strategy_positions(
    strategies: dict[str, Any], strategy_id: str
) -> dict[str, Any]:
    sd = strategies.get(strategy_id)
    if isinstance(sd, dict):
        pos = sd.get("positions")
        if isinstance(pos, dict):
            return pos
    return {}


class StrategySelector:
    def __init__(self, strategies: dict[str, Any]) -> None:
        self.out = widgets.Output(layout={"border": "1px solid gray"})
        self.strategy_out = widgets.Output()
        self.strategy_allocation: list[list[Any]] = []
        self.callback: Any = None
        self.strategies = strategies

        # options: show human-friendly strategy name, value is uuid (strategy id)
        snames = [
            (get_strategy_display_name(strategies, sid), sid) for sid in strategies
        ]
        self.dropdown = widgets.Dropdown(
            description="策略:",
            options=snames,
            value=snames[0][1] if snames else None,
            disabled=False,
        )
        self.allocation = widgets.IntText(value=300000, description="金額:")

        self.add_strategy_btn = widgets.Button(description="新增策略")
        self.add_strategy_btn.on_click(lambda s: self.add_strategy())

        form = widgets.HBox([self.dropdown, self.allocation, self.add_strategy_btn])
        with self.out:
            display(
                widgets.VBox(
                    [widgets.HTML("<h2>策略金額</h2>"), form, self.strategy_out]
                )
            )

    def update_strategy(self) -> None:

        boxes = []
        for i, (s, a) in enumerate(self.strategy_allocation):
            cancel_btn = widgets.Button(description="刪除")
            cancel_btn.ith = i
            cancel_btn.on_click(lambda btn: self.cancel_strategy(btn.ith))
            boxes.append(
                widgets.HBox(
                    [
                        cancel_btn,
                        widgets.Label(
                            value=f"策略名稱：{get_strategy_display_name(self.strategies, s)}，部位：{a} 元"
                        ),
                    ]
                )
            )

        self.strategy_out.clear_output()
        with self.strategy_out:
            display(widgets.VBox(boxes))

            if self.strategy_allocation:
                label = widgets.Label(value="開始計算部位：")
                btn1 = widgets.Button(description="整張")
                btn2 = widgets.Button(description="含零股")
                btn1.on_click(lambda btn: self.callback(self, odd_lot=False))
                btn2.on_click(lambda btn: self.callback(self, odd_lot=True))
                display(widgets.HBox([label, btn1, btn2]))

    def add_strategy(self) -> None:
        strategy = self.dropdown.value
        allocation = self.allocation.value
        self.strategy_allocation.append([strategy, allocation])

        self.update_strategy()

    def cancel_strategy(self, i: int) -> None:
        self.strategy_allocation = (
            self.strategy_allocation[:i] + self.strategy_allocation[i + 1 :]
        )

        self.update_strategy()

    def set_callback(self, callback: Any) -> None:
        self.callback = callback


class OrderPanel:
    def __init__(self) -> None:
        self.out = widgets.Output(layout={"border": "1px solid gray"})
        self.out2 = widgets.Output(layout={"border": "1px solid gray"})
        self.callback: Any = None
        self.oe: OrderExecutor | None = None
        self.strategy_stocks: dict[str, list[str]] = {}

        with self.out:
            display(widgets.HTML("<h2>確認部位</h2>"))

        with self.out2:
            display(widgets.HTML("<h2>委託部位</h2>"))

    @staticmethod
    def _order_symbol(order: Any) -> str:
        sid = getattr(order, "symbol", None)
        if isinstance(sid, str) and sid:
            return sid
        return order.stock_id

    def set_position(self, *args: Any, **kwargs: Any) -> None:
        self.oe = OrderExecutor(*args, **kwargs)
        self.display_position(edit=True)

    def set_strategy_stocks(self, strategy_stocks: dict[str, list[str]]) -> None:
        self.strategy_stocks = strategy_stocks

    def display_position(self, edit: bool = True) -> None:
        target_position = self.oe.target_position
        current_position = self.oe.account.get_position()

        delta = target_position - current_position

        self.oe.account.get_stocks(
            [resolve_position_entry_symbol(o) for o in delta.position]
        )

        grid = widgets.GridspecLayout(max(1, len(delta.position)), 5)

        for i, o in enumerate(delta.position):
            sid = resolve_position_entry_symbol(o)
            org_quantity = self.get_quantity(
                current_position.position, sid, o["order_condition"]
            )
            target_quantity = self.get_quantity(
                target_position.position, sid, o["order_condition"]
            )
            strategies_with_sid = ", ".join(
                [sname for sname, sids in self.strategy_stocks.items() if sid in sids]
            )

            grid[i, 0] = widgets.Label(value=sid)
            grid[i, 1] = widgets.Label(value=f"原始張數: {org_quantity}")
            grid[i, 2] = widgets.HBox(
                [
                    widgets.Label(value="目標張數:"),
                    widgets.FloatText(
                        value=target_quantity, layout=widgets.Layout(width="60px")
                    ),
                ]
            )
            grid[i, 3] = widgets.Label(value=str(o["order_condition"]).split(".")[-1])
            grid[i, 4] = widgets.Label(value=strategies_with_sid)

        def update_taget_position(market_order: bool = False) -> None:
            new_target_position = []
            for i, o in enumerate(delta.position):
                o_sid = resolve_position_entry_symbol(o)
                new_target_position.append(
                    {
                        "symbol": o_sid,
                        "stock_id": o_sid,
                        "quantity": grid[i, 2].children[1].value,
                        "order_condition": o["order_condition"],
                    }
                )
            self.oe.target_position = Position.from_list(new_target_position)
            self.start_creating_order(market_order=market_order)

        btn = widgets.Button(description="限價下單")
        btn.on_click(lambda btn: update_taget_position(market_order=False))
        btn2 = widgets.Button(description="市價下單")
        btn2.on_click(lambda btn: update_taget_position(market_order=True))

        self.out.clear_output()
        with self.out:
            display(widgets.HTML("<h2>確認部位</h2>"))
            display(grid)
            self.oe.show_alerting_stocks()

            display(widgets.HBox([btn, btn2]))

    @staticmethod
    def get_quantity(
        position_list: list[dict[str, Any]],
        stock_id: str | None = None,
        order_condition: Any = None,
        *,
        symbol: str | None = None,
    ) -> float:
        sid = symbol or stock_id
        for o in position_list:
            o_sid = resolve_position_entry_symbol(o)
            if o_sid == sid and o["order_condition"] == order_condition:
                return o["quantity"]
        return 0

    def start_creating_order(self, market_order: bool) -> None:
        with self.out:
            try:
                self.oe.create_orders(market_order)
            except Exception as e:
                # print traceback
                import traceback

                traceback.print_exc()
                print(e)
                print("錯誤，即時取消所有下單")
                self.oe.cancel_orders()
                return

        self.display_active_order()

    def display_active_order(self) -> bool:

        orders = self.oe.account.get_orders()

        active_orders = [
            o
            for oid, o in orders.items()
            if o.status not in [enums.OrderStatus.CANCEL, enums.OrderStatus.FILLED]
        ]
        active_orders.sort(key=self._order_symbol)

        def cancel_order_btn_func(btn: Any) -> None:
            self.oe.account.cancel_order(btn.oid)
            self.display_active_order()

        def update_price_btn_func(btn: Any) -> None:
            order = orders[btn.oid]
            sid = self._order_symbol(order)
            stock = self.oe.account.get_stocks([sid])[sid]
            self.oe.account.update_order(btn.oid, price=stock.close)
            self.display_active_order()

        def buy_at_market_price_btn_func(btn: Any) -> None:
            self.oe.account.cancel_order(btn.oid)
            order = self.oe.account.get_orders()[btn.oid]
            sid = self._order_symbol(order)
            new_quantity = float(order.quantity) - float(order.filled_quantity)
            if new_quantity >= 1:
                self.oe.account.create_order(
                    order.action,
                    sid,
                    1,
                    order_cond=order.order_condition,
                    market_order=True,
                )
                new_quantity -= 1

            if new_quantity > 0:
                self.oe.account.create_order(
                    order.action, sid, new_quantity, order_cond=order.order_condition
                )

            self.display_active_order()

        def cancel_all_orders_func() -> None:
            self.oe.cancel_orders()
            self.display_active_order()

        def update_order_price_func() -> None:
            self.oe.update_order_price()
            self.display_active_order()

        grid = widgets.GridspecLayout(max(1, len(active_orders)), 1)

        btn_recycle = widgets.Button(description="更新委託")
        btn_recycle.on_click(lambda btn: self.display_active_order())

        btn_cancel_all = widgets.Button(description="全部刪單")
        btn_cancel_all.on_click(lambda btn: cancel_all_orders_func())

        btn_update_price_all = widgets.Button(description="全部限價追價")
        btn_update_price_all.on_click(lambda btn: update_order_price_func())

        btns = widgets.HBox([btn_recycle, btn_update_price_all, btn_cancel_all])

        for i, order in enumerate(active_orders):
            s = f"股票代號 {order.symbol}"
            name_label = widgets.Label(value=s, layout=widgets.Layout(width="300px"))
            s = f'{str(order.action).split(".")[-1]} {order.filled_quantity} / {order.quantity}'

            if order.price != 0:
                s += f" @ {order.price}"

            cancel_order_btn = widgets.Button(description="刪單")
            cancel_order_btn.oid = order.order_id
            cancel_order_btn.on_click(cancel_order_btn_func)

            limit_order_update_price_btn = widgets.Button(description="限價追價")
            limit_order_update_price_btn.oid = order.order_id
            limit_order_update_price_btn.on_click(update_price_btn_func)

            buy_at_market_price_btn = widgets.Button(description="市價買一張")
            buy_at_market_price_btn.oid = order.order_id
            buy_at_market_price_btn.on_click(buy_at_market_price_btn_func)

            grid[i, 0] = widgets.HBox(
                [
                    name_label,
                    widgets.Label(value=s, layout=widgets.Layout(width="300px")),
                    widgets.Label(
                        value=f"ID: {order.order_id}",
                        layout=widgets.Layout(width="300px"),
                    ),
                    cancel_order_btn,
                    limit_order_update_price_btn,
                    buy_at_market_price_btn,
                ]
            )

        keys = [
            "symbol",
            "action",
            "price",
            "quantity",
            "filled_quantity",
            "status",
            "order_condition",
        ]
        df = (
            pd.DataFrame(
                {
                    oid: {k: getattr(order, k) for k in keys}
                    for oid, order in orders.items()
                }
            )
            .transpose()
            .pipe(lambda df: df[df.filled_quantity != 0])
        )

        self.out2.clear_output()
        with self.out2:
            display(btns)
            display(grid)

            if len(df):
                display(df)

        return len(active_orders) != 0


def order_panel(account: Any) -> dict[str, StrategySelector | OrderPanel]:
    """下單 GUI 介面
    Arguments:
        account (Account): 請參考 Account 針對不同券商來建構相對應的操作帳戶
    """

    strategies = data.get_strategies()

    def calc_position(allocations: list[list[Any]], odd_lot: bool = False) -> Position:

        total_position = Position({})

        for strategy, allocation in allocations:
            p = get_strategy_positions(strategies, strategy)
            if "position" in p and isinstance(p.get("position"), dict):
                p = p["position"]

            weights = {
                pname.split(" ")[0]: pp["next_weight"]
                for pname, pp in p.items()
                if isinstance(pp, dict) and "next_weight" in pp
            }

            price = account.get_price([s.split(" ")[0] for s in weights])

            position = Position.from_weight(
                weights, allocation, price=price, odd_lot=odd_lot
            )
            total_position += position

        return total_position

    ss = StrategySelector(strategies)
    op = OrderPanel()

    def position_check(
        strategy_selector: StrategySelector, odd_lot: bool = False
    ) -> None:
        with strategy_selector.strategy_out:
            pos = calc_position(strategy_selector.strategy_allocation, odd_lot)
            strategy_stocks = {
                get_strategy_display_name(strategies, s): [
                    i.split(" ")[0]
                    for i in get_strategy_positions(strategies, s)
                    if isinstance(get_strategy_positions(strategies, s).get(i), dict)
                ]
                for (s, a) in strategy_selector.strategy_allocation
            }
            op.set_strategy_stocks(strategy_stocks)
            op.set_position(pos, account)

    ss.set_callback(position_check)

    display(ss.out)
    display(op.out)
    display(op.out2)
    return {"strategy_selector": ss, "order_panel": op}
