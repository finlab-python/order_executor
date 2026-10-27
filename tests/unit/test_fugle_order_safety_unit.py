from __future__ import annotations

import datetime
import importlib
import sys
import types
from typing import Any

import pytest


def _import_fugle(monkeypatch: Any) -> types.ModuleType:
    ns = types.SimpleNamespace
    constant = types.ModuleType("esun_trade.constant")
    constant.Action = ns(Buy="B", Sell="S")
    constant.APCode = ns(Common="1", AfterMarket="2", Odd="3", IntradayOdd="5")
    constant.Trade = ns(Cash="0", Margin="3", Short="4", DayTradingSell="A")
    constant.PriceFlag = ns(Limit="0", Flat="1", LimitDown="2", LimitUp="4")
    order = types.ModuleType("esun_trade.order")
    order.OrderObject = lambda **kw: kw
    sdk = types.ModuleType("esun_trade.sdk")
    sdk.SDK = object
    util = types.ModuleType("esun_trade.util")
    util.setup_keyring = util.set_password = lambda *a, **k: None
    for name, mod in [("constant", constant), ("order", order), ("sdk", sdk), ("util", util)]:
        monkeypatch.setitem(sys.modules, f"esun_trade.{name}", mod)
    monkeypatch.setitem(sys.modules, "esun_trade", types.ModuleType("esun_trade"))
    sys.modules.pop("finlab.online.brokers.fugle", None)
    return importlib.import_module("finlab.online.brokers.fugle")


def _account(fugle: types.ModuleType, sdk: Any) -> Any:
    account = fugle.FugleAccount.__new__(fugle.FugleAccount)
    account.sdk = sdk
    account.user_account = "acc"
    account.timestamp_for_get_position = datetime.datetime(2000, 1, 1)
    fugle.trades["acc"] = {}
    return account


def _inv(trade: str, qty_l: int, qty_bm: int = 0, qty_sm: int = 0, qty_c: int = 0) -> dict:
    return {"stk_no": "2330", "trade": trade, "qty_l": str(qty_l), "qty_bm": str(qty_bm),
            "qty_sm": str(qty_sm), "qty_c": str(qty_c)}


@pytest.mark.parametrize(
    "row, expected",
    [
        (_inv("4", 0, qty_sm=1000), -1),  # 今天融券賣 1 張
        (_inv("4", 2000, qty_bm=1000), -1),  # 持有 2 張、今天回補 1 張
        (_inv("4", 2000, qty_c=-1000), -1),  # 現券償還 1 張
        (_inv("4", 2000), -2),  # 只有昨日餘額
        (_inv("0", 1150), 1.15),
        (_inv("0", 1000, qty_bm=2000, qty_sm=500), 2.5),
        (_inv("3", 3000, qty_sm=1000), 2),
    ],
)
def test_get_position_quantity_by_trade(monkeypatch: Any, row: dict, expected: float) -> None:
    fugle = _import_fugle(monkeypatch)
    sdk = types.SimpleNamespace(get_inventories=lambda: [row])
    position = _account(fugle, sdk).get_position()
    assert [float(p["quantity"]) for p in position.position] == [expected]


def test_create_order_day_trading_long_sends_cash_trade(monkeypatch: Any) -> None:
    fugle = _import_fugle(monkeypatch)
    placed: list[dict] = []
    sdk = types.SimpleNamespace(place_order=lambda o: placed.append(o) or {"ord_no": "A1"})
    account = _account(fugle, sdk)
    order_id = account.create_order(
        fugle.Action.BUY, "2330", 1, price=500, order_cond=fugle.OrderCondition.DAY_TRADING_LONG
    )
    assert order_id == "A1"
    assert placed[0]["trade"] == "0"


def test_update_odd_lot_price_replaces_cancelled_shares(monkeypatch: Any) -> None:
    fugle = _import_fugle(monkeypatch)
    result = {"ord_no": "B1", "pre_ord_no": "", "ap_code": "5", "buy_sell": "B", "stock_no": "2330",
              "trade": "0", "od_price": 500, "org_qty": 0.3, "mat_qty": 0.1, "cel_qty": 0,
              "org_qty_share": 300, "mat_qty_share": 100, "cel_qty_share": 0, "celable": "1",
              "err_code": "00000000", "ord_date": "20261021", "ord_time": "100000000"}
    results = [result]
    placed: list[dict] = []
    sdk = types.SimpleNamespace(
        get_order_results=lambda: results,
        cancel_order=lambda o: None,
        place_order=lambda o: placed.append(o) or {"ord_no": "B2"},
    )
    account = _account(fugle, sdk)
    account.get_orders()

    account.update_order("B1", price=510)

    # 取消完成：委託明細剩下的 200 股變成已取消，ACK 只有以張計的 cel_qty
    results[0] = {**result, "cel_qty": 0.2, "cel_qty_share": 200, "celable": "2"}
    ack = fugle.create_finlab_order({**result, "kind": "ACK", "cel_qty": "0.2", "celable": "2"})
    fugle.callbacks.pop("accB1")(ack)

    assert [(o["quantity"], o["price"]) for o in placed] == [(200, 510)]



def _row(**kw: Any) -> dict:
    base = {"ord_no": "B1", "pre_ord_no": "", "ap_code": "5", "buy_sell": "B", "stock_no": "2330",
            "trade": "0", "od_price": 500, "org_qty": 0.3, "mat_qty": 0.1, "cel_qty": 0,
            "org_qty_share": 300, "mat_qty_share": 100, "cel_qty_share": 0, "celable": "1",
            "err_code": "00000000", "ord_date": "20261027", "ord_time": "100000000"}
    return {**base, **kw}


@pytest.mark.parametrize(
    "kw, expected",
    [
        ({"org_qty": 3, "mat_qty": 0, "cel_qty": 1}, ("NEW", 2)),  # App 減量 1 張，剩 2 張排隊
        ({"org_qty": 3, "mat_qty": 1, "cel_qty": 1}, ("PARTIALLY_FILLED", 2)),
        ({"cel_qty": 0.2, "celable": "2"}, ("CANCEL", 0.1)),
        ({"org_qty": 3, "mat_qty": 0}, ("NEW", 3)),
    ],
)
def test_reduced_order_with_remaining_quantity_stays_open(
    monkeypatch: Any, kw: dict, expected: tuple
) -> None:
    order = _import_fugle(monkeypatch).create_finlab_order(_row(**kw))
    assert (order.status.name, round(order.quantity, 3)) == expected


@pytest.mark.parametrize("realtime", [False, True])
@pytest.mark.parametrize("place_fails", [False, True])
def test_odd_lot_price_update_after_cancel_ack(
    monkeypatch: Any, tmp_path: Any, caplog: Any, realtime: bool, place_fails: bool
) -> None:
    fugle = _import_fugle(monkeypatch)
    handlers: dict[str, Any] = {}
    results, placed = [_row()], []

    def place_order(o: dict) -> dict:
        if place_fails:
            raise ValueError("餘額不足")
        return placed.append(o) or {"ord_no": "B2", "pre_ord_no": ""}

    sdk = types.SimpleNamespace(  # on() 同 fugle_trade：一個事件只留最後註冊的 callback
        login=lambda: None, connect_websocket=lambda: None, get_order_results=lambda: results,
        on=lambda name: lambda f: handlers.__setitem__(name, f),
        cancel_order=lambda o: None, place_order=place_order)
    monkeypatch.setattr(fugle, "SDK", lambda config: sdk)
    monkeypatch.setattr(fugle.FugleAccount, "check_version", classmethod(lambda cls: None))
    (tmp_path / "config.ini").write_text("[User]\nAccount = 9999999\n")
    account = fugle.FugleAccount(config_path=str(tmp_path / "config.ini"))
    updates: list[Any] = []
    if realtime:
        account.connect_realtime()
        account.on_order_update(updates.append)
    account.get_orders()

    account.update_order("B1", price=510)
    results[0] = _row(cel_qty=0.2, cel_qty_share=200, celable="2")
    handlers["order"]({**results[0], "kind": "ACK"})

    assert [(o["quantity"], o["price"]) for o in placed] == ([] if place_fails else [(200, 510)])
    assert ("需手動重下" in caplog.text) == place_fails
    assert [u.status.name for u in updates] == (["CANCEL"] if realtime else [])
