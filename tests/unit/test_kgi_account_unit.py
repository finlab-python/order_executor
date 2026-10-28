from __future__ import annotations

import importlib
import sys
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from finlab.online.core.enums import Action, OrderCondition, OrderStatus

from ..utils.mock_helpers import patch_utc_host_clock

# fmt: off
# 與 kgisuperpy 2.1.2 trading/_trade_base.py 相同的列舉值
SDK = NS(
    Action=Enum("Action", {"Buy": "B", "Sell": "S"}),
    TimeInForce=Enum("TimeInForce", {"ROD": 0}),
    PriceType=Enum("PriceType", {"LMT": 0, "MKT": "1"}),
    OddLot=Enum("OddLot", {"Common": 0, "Odd_AfterMarket": 1, "Fixing": 2, "Odd": 4}),
    OrderCond=Enum("OrderCond", {"CASH": 0, "MARGIN": 3, "SHORT_SELLING": 4, "Lend_SELLING": 6,
                                 "MARGIN_DayTrade": 7, "SHORT_DayTrade": 8, "CASH_SELLING": 9}),
    Status=Enum("Status", "Pending Success Failed Submitted Filled Cancelled PartFilled PartFilled_Cancelled"),
)
SNAP = NS(price=580.0, open_price=575.0, high_price=585.0, low_price=570.0, bid_price=579.0, bid_volume=10,
          ask_price=580.0, ask_volume=5, reference_price=560.0, limit_up=616.0, limit_down=504.0)
# fmt: on


class _Order:
    """同步回報的 api.Order：數量 999 會被拒單；刪單前一刻先成交 fill_on_cancel"""

    def __init__(self) -> None:
        self.trades, self.calls, self.reports, self.fill_on_cancel = {}, [], [], 0

    def create_order(self, **kw):
        self.calls.append(kw)
        ok, oid = kw["qty"] != 999, f"Y{len(self.calls)}"
        trade = NS(
            order=NS(order_id=oid, action=kw["action"], symbol=kw["symbol"], price=kw["price"],
                     order_cond=kw["order_cond"], odd_lot=kw["odd_lot"]),
            order_status=NS(status=SDK.Status.Submitted, modified_quantity=kw["qty"],
                            modified_price=kw["price"], deals=[]),
            operations=[NS(status=SDK.Status.Success if ok else SDK.Status.Failed, op_time="093015")],
        )  # fmt: skip
        if ok:
            self.trades[oid] = trade
        return trade

    def get_trades(self, full=False):
        done = (SDK.Status.Filled, SDK.Status.PartFilled_Cancelled)
        return {
            k: t
            for k, t in self.trades.items()
            if full or t.order_status.status not in done
        }

    def update_order(self, order_id, price):
        self.calls.append(("update", order_id, price))
        self.trades[order_id].operations.append(NS(status=SDK.Status.Success))
        return self.trades[order_id]

    def cancel_order(self, order_id):
        status = self.trades[order_id].order_status
        status.deals.append(NS(quantity=self.fill_on_cancel))
        status.modified_quantity -= self.fill_on_cancel
        self.reports.append(
            {"OrderNo": order_id, "OrderFunc": "D", "ErrCode": "0",
             "BeforeQty": status.modified_quantity, "AfterQty": 0}
        )  # fmt: skip
        status.modified_quantity, status.status = 0, SDK.Status.PartFilled_Cancelled
        self.trades[order_id].operations.append(NS(status=SDK.Status.Success))
        return self.trades[order_id]


@pytest.fixture
def make(monkeypatch):
    def make(utc_time=(2, 0, 0)):
        monkeypatch.setitem(sys.modules, "kgisuperpy", SDK)
        sys.modules.pop("finlab.online.brokers.kgi", None)
        module = importlib.import_module("finlab.online.brokers.kgi")
        patch_utc_host_clock(monkeypatch, module, utc_time)
        acc = module.KGIAccount.__new__(module.KGIAccount)
        order = _Order()
        columns = ["OrderNo", "OrderFunc", "ErrCode", "BeforeQty", "AfterQty"]
        acc.api = NS(
            Order=order,
            Data=NS(get_snapshots=lambda ids: {i: SNAP for i in ids}),
            Account=NS(
                OrderReport=lambda: pd.DataFrame(order.reports, columns=columns)
            ),
        )
        return acc

    return make


def test_login_selects_stock_account_in_production(make, monkeypatch):
    make()
    accounts = [
        {"account": "F1", "account_flag": "期貨"},
        {"account": "S1", "account_flag": "證券"},
    ]
    api = NS(show_account=lambda: accounts, Order=NS(set_event=print), selected=[])
    api.set_Account = api.selected.append
    monkeypatch.setattr(
        SDK, "login", lambda *args: api.__dict__.update(args=args) or api, raising=False
    )
    monkeypatch.setenv("KGI_PERSON_ID", "A123456789")
    monkeypatch.setenv("KGI_PASSWORD", "pw")
    from finlab.online.kgi_account import KGIAccount

    KGIAccount()
    assert (api.args, api.selected) == (("A123456789", "pw", False), ["S1"])


# fmt: off
@pytest.mark.parametrize("utc_time, args, kwargs, sent", [
    ((2, 0, 0), (Action.BUY, "2330", 2, "580"), {}, ("Common", 2, 580.0, "CASH")),
    ((2, 0, 0), (Action.BUY, "2330", 300, 580), {"odd_lot": True}, ("Odd", 300, 580.0, "CASH")),
    ((5, 40, 0), (Action.BUY, "2330", 300, 580), {"odd_lot": True}, ("Odd_AfterMarket", 300, 580.0, "CASH")),
    ((6, 0, 0), (Action.SELL, "2330", 1, 580), {}, ("Fixing", 1, 580.0, "CASH")),
    ((6, 0, 0), (Action.SELL, "2330", 1, 590), {}, None),  # 定價時段比收盤價差，不送
    ((6, 0, 0), (Action.BUY, "2330", 1, 580), {"best_price_limit": True}, None),
    ((2, 0, 0), (Action.BUY, "2330", 1, 580), {"market_order": True}, ("Common", 1, 616.0, "CASH")),
    ((2, 0, 0), (Action.SELL, "2330", 1, 580), {"best_price_limit": True}, ("Common", 1, 616.0, "CASH")),
    ((2, 0, 0), (Action.SELL, "2330", 1, 580), {"order_cond": OrderCondition.DAY_TRADING_SHORT}, ("Common", 1, 580.0, "CASH_SELLING")),
    ((2, 0, 0), (Action.BUY, "2330", 1, 580), {"order_cond": OrderCondition.DAY_TRADING_SHORT}, ("Common", 1, 580.0, "CASH")),
    ((2, 0, 0), (Action.BUY, "2330", 2, 580), {"order_cond": OrderCondition.MARGIN_TRADING}, ("Common", 2, 580.0, "MARGIN")),
])
# fmt: on
def test_create_order(make, utc_time, args, kwargs, sent):
    acc = make(utc_time)
    order_id = acc.create_order(*args, **kwargs)
    if sent is None:
        assert order_id is None and acc.api.Order.calls == []
        return
    [kw] = acc.api.Order.calls
    assert order_id == "Y1"
    assert (kw["odd_lot"].name, kw["qty"], kw["price"], kw["order_cond"].name) == sent


def test_orders_reprice_and_cancel(make):
    acc = make()
    assert acc.create_order(Action.BUY, "2330", 999, price=580) is None  # 拒單
    acc.create_order(Action.BUY, "2330", 3, price=580)
    acc.create_order(Action.BUY, "2330", 500, price=580, odd_lot=True)
    odd = acc.api.Order.trades["Y3"].order_status
    odd.deals, odd.modified_quantity = [NS(quantity=100)], 400
    orders = acc.get_orders()
    assert (orders["Y2"].quantity, orders["Y2"].status) == (3, OrderStatus.NEW)
    assert (orders["Y3"].quantity, orders["Y3"].filled_quantity) == (
        Decimal("0.5"),
        Decimal("0.1"),
    )
    assert orders["Y3"].status == OrderStatus.PARTIALLY_FILLED

    acc.update_order("Y2", price=585)  # 整股限價直接改價
    acc.api.Order.fill_on_cancel = 100  # 零股刪單前一刻又成交 100 股，只重下刪掉的 300 股
    assert acc.update_order("Y3", price=583) == "Y5"
    assert acc.api.Order.calls[3] == ("update", "Y2", 585.0)
    assert (acc.api.Order.calls[4]["qty"], acc.api.Order.calls[4]["price"]) == (300, 583.0)
    acc.api.Order.fill_on_cancel = 0
    acc.cancel_order("Y2")
    acc.cancel_order("Y2")  # 已刪的單不再送
    assert acc.get_orders()["Y2"].status == OrderStatus.CANCEL


def test_position_settlement_quotes(make):
    acc = make((3, 0, 0))
    acc.api.Account.InventorySum = lambda ftype: pd.DataFrame(
        {"Symbol": ["2330", "2317", "2603"], "NETQTY0": ["2000", "-1000", "0"],
         "NETQTY9": ["300", "0", "0"], "NETQTY3": ["1000", "0", "0"], "NETQTY4": ["0", "0", "2000"]}
    )  # fmt: skip
    acc.api.Account.SettleAmt = lambda ftype: pd.DataFrame(
        [{"CDate1": "20261021", "CSRPAMT1": "-100", "CDate2": "20261022",
          "CSRPAMT2": "-200", "CDate3": "20261023", "CSRPAMT3": "50"}]
    )  # fmt: skip
    position = {
        (p["stock_id"], p["order_condition"]): p["quantity"]
        for p in acc.get_position().position
    }
    assert position == {
        ("2330", OrderCondition.CASH): Decimal("2.3"),
        ("2330", OrderCondition.MARGIN_TRADING): 1,
        ("2317", OrderCondition.DAY_TRADING_SHORT): -1,  # 現股當沖先賣、還沒買回
        ("2603", OrderCondition.SHORT_SELLING): -2,
    }
    assert acc.get_settlement() == -150
    assert acc.get_stocks(["2330"])["2330"].pct_change == pytest.approx(3.5714, abs=1e-3)
    with pytest.raises(NotImplementedError):
        acc.get_cash()
