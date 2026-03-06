import importlib
import sys
import types

from finlab.online.core.enums import Action, OrderStatus
from finlab.online.core.realtime import ConnectionState


class _FakeWsClient:
    def __init__(self):
        self.handlers = {}
        self.subscriptions = []
        self.unsubscriptions = []
        self.disconnected = False

    def on(self, event, callback):
        self.handlers[event] = callback

    def subscribe(self, payload):
        self.subscriptions.append(payload)

    def unsubscribe(self, payload):
        self.unsubscriptions.append(payload)

    def disconnect(self):
        self.disconnected = True


class _FakeSdk:
    def __init__(self):
        self.ws = _FakeWsClient()
        self.marketdata = types.SimpleNamespace(
            websocket_client=types.SimpleNamespace(stock=self.ws)
        )
        self.order_cb = None
        self.order_changed_cb = None
        self.filled_cb = None
        self.event_cb = None
        self.accounting = types.SimpleNamespace(bank_remain=lambda account: None)

    def set_on_order(self, callback):
        self.order_cb = callback

    def set_on_order_changed(self, callback):
        self.order_changed_cb = callback

    def set_on_filled(self, callback):
        self.filled_cb = callback

    def set_on_event(self, callback):
        self.event_cb = callback


def _import_fubon_module_with_fake_sdk(monkeypatch):
    sdk_module = types.ModuleType("fubon_neo.sdk")
    sdk_module.FubonSDK = object
    sdk_module.Order = object

    constant_module = types.ModuleType("fubon_neo.constant")
    constant_module.TimeInForce = types.SimpleNamespace()
    constant_module.OrderType = types.SimpleNamespace()
    constant_module.PriceType = types.SimpleNamespace()
    constant_module.MarketType = types.SimpleNamespace()
    constant_module.BSAction = types.SimpleNamespace(Buy="B", Sell="S")

    package_module = types.ModuleType("fubon_neo")
    package_module.sdk = sdk_module
    package_module.constant = constant_module

    monkeypatch.setitem(sys.modules, "fubon_neo", package_module)
    monkeypatch.setitem(sys.modules, "fubon_neo.sdk", sdk_module)
    monkeypatch.setitem(sys.modules, "fubon_neo.constant", constant_module)
    sys.modules.pop("finlab.online.brokers.fubon", None)

    module = importlib.import_module("finlab.online.brokers.fubon")
    return importlib.reload(module)


def test_fubon_realtime_callbacks_cover_tick_book_order_fill_and_connection(monkeypatch):
    fubon_module = _import_fubon_module_with_fake_sdk(monkeypatch)
    FubonAccount = fubon_module.FubonAccount

    account = FubonAccount.__new__(FubonAccount)
    account.sdk = _FakeSdk()
    account.target_account = types.SimpleNamespace(account="9809789")
    account._tick_pct_change_cache = {}
    account._init_realtime()

    ticks = []
    bidasks = []
    updates = []
    fills = []
    connections = []
    account.on_tick(ticks.append)
    account.on_bidask(bidasks.append)
    account.on_order_update(updates.append)
    account.on_fill(fills.append)
    account.on_connection(lambda state, message="": connections.append((state, message)))

    account.connect_realtime()

    account.sdk.ws.handlers["message"](
        {
            "event": "data",
            "data": {
                "symbol": "2330",
                "closePrice": 581.0,
                "lastPrice": 581.0,
                "size": 2,
                "totalVolume": 3456,
                "openPrice": 579.0,
                "highPrice": 582.0,
                "lowPrice": 578.0,
                "changePercent": 1.5,
                "time": 1_700_000_000_000,
            },
            "channel": "trades",
        }
    )

    account.sdk.ws.handlers["book"](
        {
            "event": "data",
            "data": {
                "symbol": "2330",
                "bids": [{"price": 580.0, "size": 100}],
                "asks": [{"price": 581.0, "size": 150}],
                "time": 1_700_000_001_000,
            },
            "channel": "books",
        }
    )

    order_payload = types.SimpleNamespace(
        order_no="o-1",
        seq_no="o-1",
        stock_no="2330",
        buy_sell="B",
        order_type="Stock",
        after_price=581.0,
        after_qty=1000,
        filled_qty=500,
        status=10,
        date="2026/03/06",
        last_time="09:05:12.085",
        market_type="Common",
    )
    account.sdk.order_cb(order_payload)
    account.sdk.filled_cb(
        types.SimpleNamespace(
            order_no="o-1",
            seq_no="o-1",
            stock_no="2330",
            buy_sell="S",
            filled_price=582.0,
            filled_qty=500,
            date="2026/03/06",
            filled_time="09:05:13.100",
            market_type="Common",
        )
    )
    account.sdk.event_cb("bye", "disconnect")

    assert len(ticks) == 1
    assert ticks[0].stock_id == "2330"
    assert ticks[0].pct_change == 1.5

    assert len(bidasks) == 1
    assert bidasks[0].bid_prices[0] == 580.0
    assert bidasks[0].ask_prices[0] == 581.0

    assert len(updates) == 1
    assert updates[0].action == Action.BUY
    assert updates[0].status == OrderStatus.PARTIALLY_FILLED
    assert updates[0].quantity == 1.0
    assert updates[0].filled_quantity == 0.5

    assert len(fills) == 1
    assert fills[0].action == Action.SELL
    assert fills[0].quantity == 0.5

    assert connections[0][0] == ConnectionState.CONNECTED
    assert connections[-1][0] == ConnectionState.DISCONNECTED


def test_fubon_subscribe_ticks_tracks_trades_and_aggregates(monkeypatch):
    fubon_module = _import_fubon_module_with_fake_sdk(monkeypatch)
    FubonAccount = fubon_module.FubonAccount

    account = FubonAccount.__new__(FubonAccount)
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
