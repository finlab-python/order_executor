from __future__ import annotations

import importlib
import sys
import types
from typing import Any

from finlab.online.core.enums import Action


class _FakeWsClient:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}
        self.subscriptions: list[dict[str, str]] = []
        self.unsubscriptions: list[dict[str, str]] = []
        self.disconnected = False
        self.connected = False

    def on(self, event: str, callback: Any) -> None:
        self.handlers[event] = callback

    def connect(self) -> None:
        self.connected = True

    def subscribe(self, payload: dict[str, str]) -> None:
        self.subscriptions.append(payload)

    def unsubscribe(self, payload: dict[str, str]) -> None:
        self.unsubscriptions.append(payload)

    def disconnect(self) -> None:
        self.disconnected = True


class _FakeSdk:
    def __init__(self) -> None:
        self.ws = _FakeWsClient()
        self.marketdata = types.SimpleNamespace(
            websocket_client=types.SimpleNamespace(stock=self.ws),
            rest_client=types.SimpleNamespace(
                stock=types.SimpleNamespace(
                    intraday=types.SimpleNamespace(
                        quote=lambda symbol: {
                            "symbol": symbol,
                            "previousClose": 560.0,
                            "changePercent": 1.23,
                            "bids": [
                                {"price": 567.0, "size": 20},
                                {"price": 566.0, "size": 19},
                            ],
                            "asks": [
                                {"price": 568.0, "size": 30},
                                {"price": 569.0, "size": 31},
                            ],
                            "time": 1_700_000_000_000,
                        },
                        trades=lambda symbol, limit=500, offset=0: {
                            "data": (
                                [
                                    {
                                        "serial": 11,
                                        "price": 568.0,
                                        "size": 3,
                                        "time": "09:00:02.000000",
                                    },
                                    {
                                        "serial": 10,
                                        "price": 567.0,
                                        "size": 2,
                                        "volume": 2,
                                        "time": "09:00:01.000000",
                                    },
                                ]
                                if offset == 0
                                else []
                            )
                        },
                    )
                )
            ),
        )
        self.order_cb: Any = None
        self.filled_cb: Any = None
        self.connected = False

    def set_on_order(self, callback: Any) -> None:
        self.order_cb = callback

    def set_on_filled(self, callback: Any) -> None:
        self.filled_cb = callback

    def connect_websocket(self) -> None:
        self.connected = True


def _import_masterlink_module_with_fake_sdk(monkeypatch: Any) -> types.ModuleType:
    fake_sdk_module = types.ModuleType("masterlink_sdk")
    fake_sdk_module.MasterlinkSDK = object
    fake_sdk_module.Order = object
    fake_sdk_module.Account = object
    fake_sdk_module.BSAction = types.SimpleNamespace(Buy="B", Sell="S")
    fake_sdk_module.MarketType = types.SimpleNamespace()
    fake_sdk_module.PriceType = types.SimpleNamespace()
    fake_sdk_module.TimeInForce = types.SimpleNamespace()
    fake_sdk_module.OrderType = types.SimpleNamespace()

    monkeypatch.setitem(sys.modules, "masterlink_sdk", fake_sdk_module)
    sys.modules.pop("finlab.online.brokers.masterlink", None)

    module = importlib.import_module("finlab.online.brokers.masterlink")
    return importlib.reload(module)


def test_masterlink_realtime_tick_and_trade_callbacks(monkeypatch: Any) -> None:
    masterlink_module = _import_masterlink_module_with_fake_sdk(monkeypatch)
    MasterlinkAccount = masterlink_module.MasterlinkAccount

    account = MasterlinkAccount.__new__(MasterlinkAccount)
    account.sdk = _FakeSdk()
    account._tick_pct_change_cache = {}
    account._init_realtime()

    ticks = []
    trades = []
    bidasks = []
    updates = []
    fills = []
    account.on_tick(ticks.append)
    account.on_trade(trades.append)
    account.on_bidask(bidasks.append)
    account.on_order_update(updates.append)
    account.on_fill(fills.append)

    account.connect_realtime()
    assert account.sdk.connected is True

    # Aggregates payload carries native changePercent.
    account.sdk.ws.handlers["message"](
        {
            "event": "data",
            "data": {
                "symbol": "2330",
                "changePercent": 1.23,
                "closePrice": 567.0,
                "lastSize": 12,
                "total": {"tradeVolume": 3456},
                "openPrice": 560.0,
                "highPrice": 569.0,
                "lowPrice": 558.0,
                "avgPrice": 564.5,
                "lastUpdated": 1_700_000_000_000_000,
            },
            "channel": "aggregates",
        }
    )

    # Trades payload should inherit cached native pct_change.
    account.sdk.ws.handlers["message"](
        {
            "event": "data",
            "data": {
                "symbol": "2330",
                "price": 568.0,
                "size": 3,
                "volume": 3459,
                "time": 1_700_000_001_000_000,
            },
            "channel": "trades",
        }
    )

    account.sdk.ws.handlers["book"](
        {
            "event": "data",
            "data": {
                "symbol": "2330",
                "bids": [{"price": 567.0, "size": 20}],
                "asks": [{"price": 568.0, "size": 30}],
                "time": 1_700_000_002_000_000,
            },
            "channel": "books",
        }
    )

    account.sdk.order_cb(
        types.SimpleNamespace(
            order_no="o-1",
            stock_no="2330",
            buy_sell="B",
            od_price=568.0,
            org_qty=1000,
            filled_qty=200,
        )
    )
    account.sdk.filled_cb(
        types.SimpleNamespace(
            order_no="o-1",
            stock_no="2330",
            buy_sell="S",
            filled_price=569.0,
            filled_qty=100,
        )
    )

    assert len(ticks) >= 2
    assert ticks[-1].stock_id == "2330"
    assert ticks[-1].price == 568.0
    assert ticks[-1].pct_change == 1.23
    assert len(trades) == 1
    assert trades[0].price == 568.0

    assert len(bidasks) == 1
    assert bidasks[0].bid_prices[0] == 567.0
    assert bidasks[0].ask_prices[0] == 568.0

    assert len(updates) == 1
    assert updates[0].order_id == "o-1"
    assert updates[0].stock_id == "2330"
    assert updates[0].action == Action.BUY

    assert len(fills) == 1
    assert fills[0].order_id == "o-1"
    assert fills[0].action == Action.SELL


def test_masterlink_subscribe_ticks_and_bidask(monkeypatch: Any) -> None:
    masterlink_module = _import_masterlink_module_with_fake_sdk(monkeypatch)
    MasterlinkAccount = masterlink_module.MasterlinkAccount

    account = MasterlinkAccount.__new__(MasterlinkAccount)
    account.sdk = _FakeSdk()
    account._tick_pct_change_cache = {"2330": 1.0}
    account._init_realtime()

    account.subscribe_ticks(["2330"])
    account.subscribe_bidask(["2330"])
    account.unsubscribe_ticks(["2330"])
    account.unsubscribe_bidask(["2330"])

    assert {"channel": "trades", "symbol": "2330"} in account.sdk.ws.subscriptions
    assert {"channel": "aggregates", "symbol": "2330"} in account.sdk.ws.subscriptions
    assert {"channel": "books", "symbol": "2330"} in account.sdk.ws.subscriptions

    assert {"channel": "trades", "symbol": "2330"} in account.sdk.ws.unsubscriptions
    assert {"channel": "aggregates", "symbol": "2330"} in account.sdk.ws.unsubscriptions
    assert {"channel": "books", "symbol": "2330"} in account.sdk.ws.unsubscriptions
    assert "2330" not in account._tick_pct_change_cache


def test_masterlink_backfill_ticks_normalizes_intraday_trade_rows(
    monkeypatch: Any,
) -> None:
    masterlink_module = _import_masterlink_module_with_fake_sdk(monkeypatch)
    MasterlinkAccount = masterlink_module.MasterlinkAccount

    account = MasterlinkAccount.__new__(MasterlinkAccount)
    account.sdk = _FakeSdk()
    account.target_account = types.SimpleNamespace(account="9809789")
    account._tick_pct_change_cache = {}
    account._init_realtime()

    ticks = []
    account.on_tick(ticks.append)

    backfilled = account.backfill_ticks(["2330"], emit=True)

    assert len(backfilled["2330"]) == 2
    assert [tick.price for tick in backfilled["2330"]] == [567.0, 568.0]
    assert [tick.total_volume for tick in backfilled["2330"]] == [2, 5]
    assert all(tick.prev_close == 560.0 for tick in backfilled["2330"])
    assert all(tick.pct_change == 1.23 for tick in backfilled["2330"])
    assert [tick.price for tick in ticks] == [567.0, 568.0]


def test_masterlink_get_bidask_snapshot_uses_quote_top5(monkeypatch: Any) -> None:
    masterlink_module = _import_masterlink_module_with_fake_sdk(monkeypatch)
    MasterlinkAccount = masterlink_module.MasterlinkAccount

    account = MasterlinkAccount.__new__(MasterlinkAccount)
    account.sdk = _FakeSdk()
    account.target_account = types.SimpleNamespace(account="9809789")
    account._tick_pct_change_cache = {}
    account._init_realtime()

    bidasks = []
    account.on_bidask(bidasks.append)

    snapshots = account.get_bidask_snapshot(["2330"], emit=True)

    assert list(snapshots) == ["2330"]
    assert snapshots["2330"].bid_prices[:2] == [567.0, 566.0]
    assert snapshots["2330"].ask_prices[:2] == [568.0, 569.0]
    assert len(bidasks) == 1
    assert bidasks[0].ask_prices[:2] == [568.0, 569.0]
