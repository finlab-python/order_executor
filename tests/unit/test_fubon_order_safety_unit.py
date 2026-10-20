"""富邦：查詢失敗不當成空的、未成交時的價格、盤後時段與定盤價格別（order_executor#34）"""

from __future__ import annotations

import datetime
import importlib
import sys
import types
from typing import Any

import pytest

from finlab.online.core.enums import Action

OK = types.SimpleNamespace(is_success=True, message="", data=[])
RATE_LIMITED = types.SimpleNamespace(is_success=False, message="rate limit", data=None)


def _load(monkeypatch: Any) -> tuple[types.ModuleType, Any]:
    names = "Common Fixing Odd IntradayOdd EmgOdd Limit LimitUp LimitDown Reference Market Stock Margin Short DayTrade ROD"
    enums = types.SimpleNamespace(**{n: n for n in names.split()})
    constant = types.ModuleType("fubon_neo.constant")
    constant.BSAction = types.SimpleNamespace(Buy="B", Sell="S")
    constant.MarketType = constant.PriceType = constant.OrderType = enums
    constant.TimeInForce = enums
    sdk = types.ModuleType("fubon_neo.sdk")
    sdk.FubonSDK = object
    sdk.Order = lambda **kwargs: kwargs
    package = types.ModuleType("fubon_neo")
    package.sdk, package.constant = sdk, constant
    for name, mod in (("fubon_neo", package), ("fubon_neo.sdk", sdk), ("fubon_neo.constant", constant)):
        monkeypatch.setitem(sys.modules, name, mod)
    sys.modules.pop("finlab.online.brokers.fubon", None)
    module = importlib.import_module("finlab.online.brokers.fubon")

    account = module.FubonAccount.__new__(module.FubonAccount)
    account.target_account = "acc"
    account.sdk = types.SimpleNamespace(
        stock=types.SimpleNamespace(get_order_results=lambda acc: OK),
        accounting=types.SimpleNamespace(unrealized_gains_and_loses=lambda acc: OK),
    )
    return module, account


def _freeze_utc_host(monkeypatch: Any, module: Any, hour: int, minute: int) -> None:
    """模擬主機時區為 UTC，UTC hour:minute:30 的那一刻"""
    instant = datetime.datetime(2026, 10, 21, hour, minute, 30, tzinfo=datetime.timezone.utc)

    class Clock(datetime.datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime.datetime:  # type: ignore[override]
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    fake = types.SimpleNamespace(datetime=Clock, time=datetime.time, timezone=datetime.timezone, timedelta=datetime.timedelta)
    monkeypatch.setattr(module, "datetime", fake)


def _timeout(acc: Any) -> Any:
    raise TimeoutError("timeout")


@pytest.mark.parametrize("response", [lambda acc: RATE_LIMITED, _timeout])
def test_query_failure_raises_instead_of_empty(monkeypatch: Any, response: Any) -> None:
    _, account = _load(monkeypatch)
    account.sdk.accounting.unrealized_gains_and_loses = response
    account.sdk.stock.get_order_results = response
    with pytest.raises(Exception):
        account.get_position()
    with pytest.raises(Exception):
        account.get_orders()


def test_successful_queries_unchanged(monkeypatch: Any) -> None:
    _, account = _load(monkeypatch)
    assert account.get_position().position == []
    assert account.get_orders() == {}

    holding = types.SimpleNamespace(stock_no="2330", order_type="Stock", today_qty=2000, buy_sell="B")
    account.sdk.accounting.unrealized_gains_and_loses = lambda acc: types.SimpleNamespace(is_success=True, data=[holding])
    assert [(p["stock_id"], p["quantity"]) for p in account.get_position().position] == [("2330", 2.0)]


def test_close_falls_back_to_reference_price_before_first_trade(monkeypatch: Any) -> None:
    _, account = _load(monkeypatch)
    no_trade = {"symbol": "2330", "referencePrice": 580.0, "previousClose": 579.0}
    assert account._create_finlab_stock(no_trade, "2330").close == 580.0
    traded = {**no_trade, "closePrice": 585.0}
    assert account._create_finlab_stock(traded, "2330").close == 585.0


@pytest.mark.parametrize(
    ("utc", "odd_lot", "expected"),
    [
        ((5, 41), True, "Odd"),  # 台北 13:41，UTC 主機原本判成盤中零股
        ((5, 40), True, "Odd"),  # 台北 13:40:30
        ((6, 0), False, "Fixing"),  # 台北 14:00:30
        ((6, 15), False, "Fixing"),
        ((2, 0), True, "IntradayOdd"),  # 台北 10:00
        ((2, 0), False, "Common"),
        ((6, 30), False, "Common"),
    ],
)
def test_market_type_uses_taipei_time(monkeypatch: Any, utc: tuple[int, int], odd_lot: bool, expected: str) -> None:
    module, account = _load(monkeypatch)
    _freeze_utc_host(monkeypatch, module, *utc)
    assert account._determine_market_type(odd_lot) == expected


@pytest.mark.parametrize(("utc", "market", "price_type", "price"), [((6, 15), "Fixing", "Reference", None), ((2, 0), "Common", "Limit", "580.0")])
def test_fixing_order_uses_reference_price(monkeypatch: Any, utc: tuple[int, int], market: str, price_type: str, price: str | None) -> None:
    module, account = _load(monkeypatch)
    _freeze_utc_host(monkeypatch, module, *utc)
    placed = []
    account.sdk.stock.place_order = lambda acc, order: placed.append(order) or types.SimpleNamespace(is_success=True, data=types.SimpleNamespace(seq_no="x"))

    assert account.create_order(Action.BUY, "2330", 1, price=580.0) == "x"
    assert (placed[0]["market_type"], placed[0]["price_type"], placed[0]["price"]) == (market, price_type, price)
