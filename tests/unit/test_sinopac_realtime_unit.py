import importlib
import sys
import types

from finlab.online.core.enums import Action, OrderStatus
from finlab.online.core.realtime_models import ConnectionState


class _FakeQuote:
    def __init__(self):
        self.event_cb = None
        self.subscriptions = []
        self.unsubscriptions = []

    def on_event(self, callback):
        self.event_cb = callback
        return callback

    def subscribe(self, contract, quote_type=None):
        self.subscriptions.append((contract.code, quote_type))

    def unsubscribe(self, contract, quote_type=None):
        self.unsubscriptions.append((contract.code, quote_type))


class _FakeShioaji:
    def __init__(self):
        self.tick_cb = None
        self.bidask_cb = None
        self.order_cb = None
        self.quote = _FakeQuote()
        self.stock_account = types.SimpleNamespace(account_id="9809789")

    def ticks(self, contract, date=None):
        return types.SimpleNamespace(
            ts=[1_700_000_000_000_000, 1_700_000_001_000_000],
            close=[581.0, 582.0],
            volume=[2, 1],
            tick_type=[1, 2],
        )

    def on_tick_stk_v1(self):
        def decorator(callback):
            self.tick_cb = callback
            return callback
        return decorator

    def on_bidask_stk_v1(self):
        def decorator(callback):
            self.bidask_cb = callback
            return callback
        return decorator

    def set_order_callback(self, callback):
        self.order_cb = callback


def _import_sinopac_module_with_fake_sdk(monkeypatch):
    shioaji_module = types.ModuleType("shioaji")
    shioaji_module.Shioaji = object
    shioaji_module.constant = types.SimpleNamespace(
        QuoteType=types.SimpleNamespace(Tick="Tick", BidAsk="BidAsk")
    )

    constant_module = types.ModuleType("shioaji.constant")
    constant_module.StockPriceType = types.SimpleNamespace()
    constant_module.StockOrderLot = types.SimpleNamespace()
    constant_module.Action = types.SimpleNamespace()
    constant_module.SecurityType = types.SimpleNamespace(Stock="Stock")
    constant_module.Exchange = types.SimpleNamespace(TSE="TSE")
    constant_module.OrderType = types.SimpleNamespace()
    constant_module.Unit = types.SimpleNamespace()
    constant_module.OrderState = types.SimpleNamespace(
        StockDeal=types.SimpleNamespace(value="SDEAL"),
        FuturesDeal=types.SimpleNamespace(value="FDEAL"),
        StockOrder=types.SimpleNamespace(value="SORDER"),
        FuturesOrder=types.SimpleNamespace(value="FORDER"),
    )

    contracts_module = types.ModuleType("shioaji.contracts")

    class _FakeStockContract:
        def __init__(self, security_type=None, code=None, exchange=None):
            self.security_type = security_type
            self.code = code
            self.exchange = exchange

    contracts_module.Stock = _FakeStockContract

    order_module = types.ModuleType("shioaji.order")
    order_module.Trade = object
    order_module.StockOrder = object

    position_module = types.ModuleType("shioaji.position")
    position_module.StockPosition = object
    position_module.SettlementV1 = object

    monkeypatch.setitem(sys.modules, "shioaji", shioaji_module)
    monkeypatch.setitem(sys.modules, "shioaji.constant", constant_module)
    monkeypatch.setitem(sys.modules, "shioaji.contracts", contracts_module)
    monkeypatch.setitem(sys.modules, "shioaji.order", order_module)
    monkeypatch.setitem(sys.modules, "shioaji.position", position_module)
    sys.modules.pop("finlab.online.brokers.sinopac", None)

    module = importlib.import_module("finlab.online.brokers.sinopac")
    return importlib.reload(module)


def test_sinopac_realtime_callbacks_cover_tick_book_order_fill_and_connection(monkeypatch):
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    SinopacAccount = sinopac_module.SinopacAccount

    account = SinopacAccount.__new__(SinopacAccount)
    account.api = _FakeShioaji()
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

    account.api.tick_cb(
        "TSE",
        types.SimpleNamespace(
            code="2330",
            close=581.0,
            volume=2,
            total_volume=100,
            datetime=types.SimpleNamespace(),
            open=579.0,
            high=582.0,
            low=578.0,
            avg_price=580.0,
            tick_type=1,
            reference=572.0,
        ),
    )
    account.api.bidask_cb(
        "TSE",
        types.SimpleNamespace(
            code="2330",
            bid_price=[580.0],
            bid_volume=[100],
            ask_price=[581.0],
            ask_volume=[150],
            datetime=types.SimpleNamespace(),
        ),
    )
    account.api.order_cb(
        types.SimpleNamespace(value="SORDER"),
        types.SimpleNamespace(
            id="o-1",
            code="2330",
            action="Buy",
            price=581.0,
            quantity=1.0,
            deal_quantity=0.5,
            status="PartFilled",
            order_cond="Cash",
            order_datetime=types.SimpleNamespace(),
        ),
    )
    account.api.order_cb(
        types.SimpleNamespace(value="SDEAL"),
        types.SimpleNamespace(
            seqno="o-1",
            code="2330",
            action="Sell",
            price=582.0,
            quantity=0.5,
            ts=1_700_000_000_000,
        ),
    )
    account.api.quote.event_cb(0, 0, "ok", "connected")

    assert len(ticks) == 1
    assert ticks[0].stock_id == "2330"
    assert len(bidasks) == 1
    assert bidasks[0].bid_prices[0] == 580.0

    assert len(updates) == 1
    assert updates[0].action == Action.BUY
    assert updates[0].status == OrderStatus.PARTIALLY_FILLED

    assert len(fills) == 1
    assert fills[0].action == Action.SELL
    assert fills[0].quantity == 0.5

    assert connections[0][0] == ConnectionState.CONNECTED
    assert connections[-1][0] == ConnectionState.CONNECTED


def test_sinopac_subscribe_ticks_and_bidask(monkeypatch):
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    SinopacAccount = sinopac_module.SinopacAccount

    account = SinopacAccount.__new__(SinopacAccount)
    account.api = _FakeShioaji()
    account._init_realtime()

    account.subscribe_ticks(["2330"])
    account.subscribe_bidask(["2330"])
    account.unsubscribe_ticks(["2330"])
    account.unsubscribe_bidask(["2330"])

    assert ("2330", "Tick") in account.api.quote.subscriptions
    assert ("2330", "BidAsk") in account.api.quote.subscriptions
    assert ("2330", "Tick") in account.api.quote.unsubscriptions
    assert ("2330", "BidAsk") in account.api.quote.unsubscriptions


def test_sinopac_backfill_ticks_uses_historical_tick_query(monkeypatch):
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    SinopacAccount = sinopac_module.SinopacAccount

    account = SinopacAccount.__new__(SinopacAccount)
    account.api = _FakeShioaji()
    account._init_realtime()

    ticks = []
    account.on_tick(ticks.append)

    backfilled = account.backfill_ticks(["2330"], emit=True)

    assert len(backfilled["2330"]) == 2
    assert [tick.price for tick in backfilled["2330"]] == [581.0, 582.0]
    assert [tick.total_volume for tick in backfilled["2330"]] == [2, 3]
    assert [tick.tick_type for tick in backfilled["2330"]] == [1, 2]
    assert [tick.price for tick in ticks] == [581.0, 582.0]
