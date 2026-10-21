from __future__ import annotations

import importlib
import sys
import types
from typing import Any

import pytest

from finlab.online.core.enums import Action

from ..utils.mock_helpers import patch_utc_host_clock


def _import_fugle_module_with_fake_sdk(monkeypatch: Any) -> types.ModuleType:
    sdk_module = types.ModuleType("esun_trade.sdk")
    sdk_module.SDK = object

    order_module = types.ModuleType("esun_trade.order")
    order_module.OrderObject = types.SimpleNamespace

    constant_module = types.ModuleType("esun_trade.constant")
    constant_module.Action = types.SimpleNamespace(Buy="B", Sell="S")
    ap_codes = ("Common", "IntradayOdd", "Odd", "AfterMarket")
    constant_module.APCode = types.SimpleNamespace(**{c: c for c in ap_codes})
    trades = ("Cash", "Margin", "Short", "DayTradingSell")
    constant_module.Trade = types.SimpleNamespace(**{t: t for t in trades})
    constant_module.PriceFlag = types.SimpleNamespace(Limit="L")
    constant_module.BSFlag = types.SimpleNamespace()

    util_module = types.ModuleType("esun_trade.util")
    util_module.setup_keyring = lambda *args, **kwargs: None
    util_module.set_password = lambda *args, **kwargs: None

    package_module = types.ModuleType("esun_trade")
    package_module.sdk = sdk_module
    package_module.order = order_module
    package_module.constant = constant_module
    package_module.util = util_module

    monkeypatch.setitem(sys.modules, "esun_trade", package_module)
    monkeypatch.setitem(sys.modules, "esun_trade.sdk", sdk_module)
    monkeypatch.setitem(sys.modules, "esun_trade.order", order_module)
    monkeypatch.setitem(sys.modules, "esun_trade.constant", constant_module)
    monkeypatch.setitem(sys.modules, "esun_trade.util", util_module)
    sys.modules.pop("finlab.online.brokers.fugle", None)

    module = importlib.import_module("finlab.online.brokers.fugle")
    return importlib.reload(module)


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


def test_fugle_backfill_ticks_uses_marketdata_http_api(monkeypatch: Any) -> None:
    fugle_module = _import_fugle_module_with_fake_sdk(monkeypatch)
    FugleAccount = fugle_module.FugleAccount

    def fake_get(
        url: str, headers: dict | None = None, params: dict | None = None
    ) -> _FakeResponse:
        assert headers == {"X-API-KEY": "demo-key"}
        if url.endswith("/stock/intraday/quote/2330"):
            return _FakeResponse(
                {
                    "symbol": "2330",
                    "previousClose": 100.0,
                    "changePercent": 1.0,
                    "bids": [
                        {"price": 100.0, "size": 10},
                        {"price": 99.5, "size": 9},
                    ],
                    "asks": [
                        {"price": 100.5, "size": 11},
                        {"price": 101.0, "size": 12},
                    ],
                    "time": "09:00:00.000000",
                }
            )
        if url.endswith("/stock/intraday/trades/2330"):
            offset = (params or {}).get("offset", 0)
            return _FakeResponse(
                {
                    "data": (
                        [
                            {
                                "serial": 2,
                                "price": 101.0,
                                "size": 1,
                                "time": "09:00:02.000000",
                            },
                            {
                                "serial": 1,
                                "price": 100.5,
                                "size": 2,
                                "volume": 2,
                                "time": "09:00:01.000000",
                            },
                        ]
                        if offset == 0
                        else []
                    )
                }
            )
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(fugle_module.requests, "get", fake_get)

    account = FugleAccount.__new__(FugleAccount)
    account.market_api_key = "demo-key"
    account._init_realtime()

    ticks = []
    account.on_tick(ticks.append)

    backfilled = account.backfill_ticks(["2330"], emit=True)

    assert len(backfilled["2330"]) == 2
    assert [tick.price for tick in backfilled["2330"]] == [100.5, 101.0]
    assert [tick.total_volume for tick in backfilled["2330"]] == [2, 3]
    assert all(tick.prev_close == 100.0 for tick in backfilled["2330"])
    assert all(tick.pct_change == 1.0 for tick in backfilled["2330"])
    assert [tick.price for tick in ticks] == [100.5, 101.0]


def test_fugle_get_bidask_snapshot_uses_marketdata_http_api(monkeypatch: Any) -> None:
    fugle_module = _import_fugle_module_with_fake_sdk(monkeypatch)
    FugleAccount = fugle_module.FugleAccount

    def fake_get(
        url: str, headers: dict | None = None, params: dict | None = None
    ) -> _FakeResponse:
        assert headers == {"X-API-KEY": "demo-key"}
        if url.endswith("/stock/intraday/quote/2330"):
            return _FakeResponse(
                {
                    "symbol": "2330",
                    "bids": [
                        {"price": 100.0, "size": 10},
                        {"price": 99.5, "size": 9},
                    ],
                    "asks": [
                        {"price": 100.5, "size": 11},
                        {"price": 101.0, "size": 12},
                    ],
                    "time": "09:00:00.000000",
                }
            )
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(fugle_module.requests, "get", fake_get)

    account = FugleAccount.__new__(FugleAccount)
    account.market_api_key = "demo-key"
    account._init_realtime()

    bidasks = []
    account.on_bidask(bidasks.append)

    snapshots = account.get_bidask_snapshot(["2330"], emit=True)

    assert list(snapshots) == ["2330"]
    assert snapshots["2330"].bid_prices[:2] == [100.0, 99.5]
    assert snapshots["2330"].ask_prices[:2] == [100.5, 101.0]
    assert len(bidasks) == 1
    assert bidasks[0].bid_volumes[:2] == [10, 9]


@pytest.mark.parametrize(
    "utc_time, odd_lot, ap_code",
    [
        ((5, 40, 30), True, "Odd"),
        ((6, 0, 10), False, "AfterMarket"),
        ((6, 30, 0), True, "IntradayOdd"),
        ((1, 0, 0), False, "Common"),
        ((1, 0, 0), True, "IntradayOdd"),
    ],
)
def test_fugle_create_order_session_starts_at_taipei_minute(
    monkeypatch: Any, utc_time: tuple, odd_lot: bool, ap_code: str
) -> None:
    fugle_module = _import_fugle_module_with_fake_sdk(monkeypatch)
    patch_utc_host_clock(monkeypatch, fugle_module, utc_time)
    placed: list[Any] = []
    account = fugle_module.FugleAccount.__new__(fugle_module.FugleAccount)
    account.sdk = types.SimpleNamespace(
        place_order=lambda order: placed.append(order) or {"ord_no": "o-1"}
    )

    account.create_order(Action.BUY, "2330", 1, price=580, odd_lot=odd_lot)

    assert placed[0].ap_code == ap_code
