from __future__ import annotations

import importlib
import sys
import types
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from finlab.online.core.enums import Action, OrderCondition, OrderStatus

from ..utils.mock_helpers import patch_utc_host_clock


def _fake_sdk() -> types.ModuleType:
    """與 kgisuperpy 2.1.2 trading/_trade_base.py 相同的列舉值"""
    sdk = types.ModuleType("kgisuperpy")
    sdk.Action = Enum("Action", {"Buy": "B", "Sell": "S"})
    sdk.TimeInForce = Enum("TimeInForce", {"ROD": 0, "IOC": 1, "FOK": 2})
    sdk.PriceType = Enum(
        "PriceType",
        {"LMT": 0, "MKT": "1", "LimitDown": 1, "LimitUp": 9, "Reference": 5},
    )
    sdk.OddLot = Enum(
        "OddLot", {"Common": 0, "Fixing": 2, "Odd_AfterMarket": 1, "Odd": 4}
    )
    sdk.OrderCond = Enum(
        "OrderCond",
        {
            "CASH": 0,
            "MARGIN": 3,
            "SHORT_SELLING": 4,
            "Lend_SELLING": 6,
            "MARGIN_DayTrade": 7,
            "SHORT_DayTrade": 8,
            "CASH_SELLING": 9,
        },
    )
    sdk.Status = Enum(
        "Status",
        {
            n: n
            for n in (
                "Pending",
                "Success",
                "Failed",
                "Submitted",
                "Filled",
                "Cancelled",
                "PartFilled",
                "PartFilled_Cancelled",
            )
        },
    )
    return sdk


class _FakeOrderAPI:
    """同步模擬 SDK：送單後立刻收到交易所回報"""

    def __init__(self, sdk: types.ModuleType) -> None:
        self.sdk = sdk
        self.trades: dict = {}
        self.calls: list = []
        self.reject = False

    def create_order(self, **kwargs):
        self.calls.append(("create", kwargs))
        op = NS(status=self.sdk.Status.Pending, op_time="093000")
        trade = NS(
            order=NS(
                order_id=None,
                action=kwargs["action"],
                symbol=kwargs["symbol"],
                quantity=kwargs["qty"],
                price=kwargs["price"],
                price_type=self.sdk.PriceType.LMT,
                order_cond=kwargs["order_cond"],
                odd_lot=kwargs["odd_lot"],
            ),
            order_status=NS(
                status=self.sdk.Status.Submitted,
                modified_quantity=kwargs["qty"],
                modified_price=kwargs["price"],
                deals=[],
            ),
            operations=[op],
        )
        if self.reject:
            op.status = self.sdk.Status.Failed
        else:
            trade.order.order_id = f"Y{len(self.trades):04d}"
            self.trades[trade.order.order_id] = trade
        return trade

    def get_trades(self, full: bool = False) -> dict:
        done = {
            self.sdk.Status.Filled,
            self.sdk.Status.Cancelled,
            self.sdk.Status.PartFilled_Cancelled,
            self.sdk.Status.Failed,
        }
        trades = {
            k: t
            for k, t in self.trades.items()
            if full or t.order_status.status not in done
        }
        return {**trades, "無效單": []} if full else trades

    def update_order(self, order_id, price=None, qty=None):
        self.calls.append(("update", order_id, price, qty))
        return self.trades[order_id]

    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        trade = self.trades[order_id]
        trade.operations.append(NS(status=self.sdk.Status.Pending))
        trade.order_status.modified_quantity = 0
        trade.order_status.status = self.sdk.Status.Cancelled
        return trade


@pytest.fixture
def make_account(monkeypatch: pytest.MonkeyPatch):
    def make(utc_time: tuple = (2, 0, 0)):
        sdk = _fake_sdk()
        monkeypatch.setitem(sys.modules, "kgisuperpy", sdk)
        sys.modules.pop("finlab.online.brokers.kgi", None)
        module = importlib.import_module("finlab.online.brokers.kgi")
        patch_utc_host_clock(monkeypatch, module, utc_time)
        acc = module.KGIAccount.__new__(module.KGIAccount)
        snapshot = NS(
            price=580.0,
            open_price=575.0,
            high_price=585.0,
            low_price=570.0,
            bid_price=579.0,
            bid_volume=10,
            ask_price=580.0,
            ask_volume=5,
            reference_price=560.0,
            limit_up=616.0,
            limit_down=504.0,
        )
        acc.api = NS(
            Order=_FakeOrderAPI(sdk),
            Account=NS(),
            Data=NS(get_snapshots=lambda ids: {i: snapshot for i in ids}),
        )
        return acc, sdk

    return make


def test_login_selects_stock_account_in_production(make_account, monkeypatch):
    _, sdk = make_account()
    api = NS(
        show_account=lambda: [
            {"account": "F1", "account_flag": "期貨"},
            {"account": "S1", "account_flag": "證券"},
        ],
        Order=NS(set_event=lambda cb: None),
        selected=[],
    )
    api.set_Account = api.selected.append

    def login(*args):
        api.args = args
        return api

    sdk.login = login
    monkeypatch.setenv("KGI_PERSON_ID", "A123456789")
    monkeypatch.setenv("KGI_PASSWORD", "pw")
    from finlab.online.kgi_account import KGIAccount

    KGIAccount()
    assert api.args == ("A123456789", "pw", False) and api.selected == ["S1"]
    with pytest.raises(ValueError, match="S2"):
        KGIAccount(account="S2")


@pytest.mark.parametrize(
    "utc_time, odd_lot, kwargs, lot, price",
    [
        ((2, 0, 0), False, {}, "Common", 580.0),
        ((2, 0, 0), True, {}, "Odd", 580.0),
        ((5, 40, 0), True, {}, "Odd_AfterMarket", 580.0),
        ((6, 0, 0), False, {}, "Fixing", 580.0),
        ((2, 0, 0), False, {"market_order": True}, "Common", 616.0),
        ((2, 0, 0), True, {"best_price_limit": True}, "Odd", 504.0),
    ],
)
def test_create_order_session_and_price(
    make_account, utc_time, odd_lot, kwargs, lot, price
):
    acc, sdk = make_account(utc_time)
    qty = 300 if odd_lot else 2
    order_id = acc.create_order(
        Action.BUY, "2330", qty, price="580", odd_lot=odd_lot, **kwargs
    )

    [(_, sent)] = acc.api.Order.calls
    assert order_id == "Y0000"
    assert (sent["odd_lot"], sent["qty"]) == (sdk.OddLot[lot], qty)
    assert sent["price"] == price


@pytest.mark.parametrize("kwargs", [{"best_price_limit": True}, {"price": 575}])
def test_fixing_session_skips_orders_that_cannot_fill(make_account, kwargs):
    acc, _ = make_account((6, 10, 0))
    assert acc.create_order(Action.BUY, "2330", 1, **{"price": 580, **kwargs}) is None
    assert acc.api.Order.calls == []


def test_rejected_order_returns_none(make_account):
    acc, _ = make_account()
    acc.api.Order.reject = True
    assert acc.create_order(Action.SELL, "2330", 1, price=580) is None


def test_get_orders_converts_units_and_status(make_account):
    acc, sdk = make_account()
    acc.create_order(Action.BUY, "2330", 500, price=580, odd_lot=True)
    acc.create_order(
        Action.SELL, "2330", 3, price=600, order_cond=OrderCondition.MARGIN_TRADING
    )
    odd = acc.api.Order.trades["Y0000"].order_status
    odd.deals, odd.modified_quantity, odd.status = (
        [NS(quantity=200)],
        300,
        sdk.Status.PartFilled,
    )

    orders = acc.get_orders()
    assert (orders["Y0000"].quantity, orders["Y0000"].filled_quantity) == (
        Decimal("0.5"),
        Decimal("0.2"),
    )
    assert orders["Y0000"].status == OrderStatus.PARTIALLY_FILLED
    assert (orders["Y0001"].quantity, orders["Y0001"].status) == (3, OrderStatus.NEW)
    assert orders["Y0001"].order_condition == OrderCondition.MARGIN_TRADING


def test_update_order_price_and_quantity(make_account):
    acc, _ = make_account()
    acc.create_order(Action.BUY, "2330", 3, price=580)
    acc.update_order("Y0000", price=585)
    acc.update_order("Y0000", quantity=1)
    assert acc.api.Order.calls[1:] == [
        ("update", "Y0000", 585.0, None),
        ("update", "Y0000", None, 2),
    ]
    with pytest.raises(ValueError, match="只能減量"):
        acc.update_order("Y0000", quantity=3)


@pytest.mark.parametrize("odd_lot", [True, False])
def test_update_order_replaces_odd_lot_and_market_orders(make_account, odd_lot):
    acc, sdk = make_account()
    acc.create_order(
        Action.BUY, "2330", 500 if odd_lot else 2, price=580, odd_lot=odd_lot
    )
    if not odd_lot:  # 在 App 下的市價單
        acc.api.Order.trades["Y0000"].order.price_type = sdk.PriceType.MKT
    real_cancel = acc.api.Order.cancel_order

    def cancel(order_id):
        # 刪單前一刻成交 100 股或 1 張，只重下剩下的
        acc.api.Order.trades[order_id].order_status.deals = [
            NS(quantity=100 if odd_lot else 1)
        ]
        return real_cancel(order_id)

    acc.api.Order.cancel_order = cancel
    assert acc.update_order("Y0000", price=585) == "Y0001"
    sent = acc.api.Order.calls[-1][1]
    assert (sent["qty"], sent["price"]) == ((400, 585.0) if odd_lot else (1, 585.0))


def test_cancel_order_skips_orders_no_longer_open(make_account):
    acc, sdk = make_account()
    acc.create_order(Action.BUY, "2330", 1, price=580)
    acc.api.Order.trades["Y0000"].order_status.status = sdk.Status.Filled
    acc.cancel_order("Y0000")
    assert ("cancel", "Y0000") not in acc.api.Order.calls


def test_position_settlement_quotes_and_cash(make_account):
    acc, _ = make_account((3, 0, 0))
    acc.api.Account.InventorySum = lambda ftype: pd.DataFrame(
        [
            {
                "Symbol": "2330",
                "NETQTY0": "2000",
                "NETQTY9": "300",
                "NETQTY3": "1000",
                "NETQTY4": "0",
            },
            {
                "Symbol": "2603",
                "NETQTY0": "0",
                "NETQTY9": "0",
                "NETQTY3": "0",
                "NETQTY4": "2000",
            },
        ]
    )
    acc.api.Account.SettleAmt = lambda ftype: pd.DataFrame(
        [
            {
                "CURRENCY": "TWD",
                "CDate1": "20261021",
                "CSRPAMT1": "-100",
                "CDate2": "20261022",
                "CSRPAMT2": "-200",
                "CDate3": "20261023",
                "CSRPAMT3": "50",
            }
        ]
    )
    quantities = {
        (p["stock_id"], p["order_condition"]): p["quantity"]
        for p in acc.get_position().position
    }
    assert quantities == {
        ("2330", OrderCondition.CASH): Decimal("2.3"),
        ("2330", OrderCondition.MARGIN_TRADING): 1,
        ("2603", OrderCondition.SHORT_SELLING): -2,
    }
    assert acc.get_settlement() == -150
    assert acc.get_stocks(["2330"])["2330"].pct_change == pytest.approx(
        3.5714, abs=1e-3
    )
    with pytest.raises(NotImplementedError):
        acc.get_cash()
