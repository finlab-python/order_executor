from __future__ import annotations

import importlib
import sys
import types

import pytest

from finlab.online.core.enums import Action, OrderStatus
from finlab.online.core.realtime_models import ConnectionState


class _FakeQuote:
    def __init__(self) -> None:
        self.event_cb = None
        self.subscriptions: list[tuple[str, str | None]] = []
        self.unsubscriptions: list[tuple[str, str | None]] = []

    def on_event(self, callback: object) -> object:
        self.event_cb = callback
        return callback

    def subscribe(self, contract: object, quote_type: str | None = None) -> None:
        self.subscriptions.append((contract.code, quote_type))

    def unsubscribe(self, contract: object, quote_type: str | None = None) -> None:
        self.unsubscriptions.append((contract.code, quote_type))


class _FakeContracts:
    """Mimics shioaji 1.7 api.contracts with exchange auto-resolution."""

    _exchange_by_code = {"2330": "TSE", "8042": "OTC"}

    def get(self, code: str) -> types.SimpleNamespace | None:
        exchange = self._exchange_by_code.get(code)
        if exchange is None:
            return None
        return types.SimpleNamespace(
            security_type="Stock", code=code, exchange=exchange,
        )


class _FakeShioaji:
    def __init__(self) -> None:
        self.tick_cb = None
        self.bidask_cb = None
        self.order_cb = None
        self.quote = _FakeQuote()
        self.contracts = _FakeContracts()
        self.stock_account = types.SimpleNamespace(account_id="9809789")
        self.snapshot_calls: list[list[tuple[str | None, str | None]]] = []
        self.placed_orders: list[tuple[object, object]] = []

    def snapshots(self, contracts: list[object]) -> list[types.SimpleNamespace]:
        self.snapshot_calls.append([(c.code, c.exchange) for c in contracts])
        return [
            types.SimpleNamespace(
                code=c.code,
                exchange=c.exchange,
                open=100.0,
                high=105.0,
                low=99.0,
                close=102.0,
                buy_price=101.5,
                buy_volume=12,
                sell_price=102.5,
                sell_volume=15,
                change_rate=1.2,
            )
            for c in contracts
        ]

    def Order(self, **kwargs: object) -> types.SimpleNamespace:
        return types.SimpleNamespace(**kwargs)

    def place_order(
        self, contract: object, order: object
    ) -> types.SimpleNamespace:
        self.placed_orders.append((contract, order))
        return types.SimpleNamespace(status=types.SimpleNamespace(id="order-1"))

    def ticks(self, contract: object, date: str | None = None) -> types.SimpleNamespace:
        return types.SimpleNamespace(
            ts=[1_700_000_000_000_000, 1_700_000_001_000_000],
            close=[581.0, 582.0],
            volume=[2, 1],
            tick_type=[1, 2],
        )

    def on_tick_stk_v1(self) -> object:
        def decorator(callback: object) -> object:
            self.tick_cb = callback
            return callback

        return decorator

    def on_bidask_stk_v1(self) -> object:
        def decorator(callback: object) -> object:
            self.bidask_cb = callback
            return callback

        return decorator

    def set_order_callback(self, callback: object) -> None:
        self.order_cb = callback


def _import_sinopac_module_with_fake_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> types.ModuleType:
    shioaji_module = types.ModuleType("shioaji")
    shioaji_module.Shioaji = object
    shioaji_module.constant = types.SimpleNamespace(
        QuoteType=types.SimpleNamespace(Tick="Tick", BidAsk="BidAsk")
    )

    constant_module = types.ModuleType("shioaji.constant")
    constant_module.StockPriceType = types.SimpleNamespace(LMT="LMT")
    constant_module.StockOrderLot = types.SimpleNamespace(
        Common="Common", IntradayOdd="IntradayOdd", Odd="Odd", Fixing="Fixing"
    )
    constant_module.Action = types.SimpleNamespace(Buy="Buy", Sell="Sell")
    constant_module.OrderType = types.SimpleNamespace(ROD="ROD")
    constant_module.Unit = types.SimpleNamespace()
    constant_module.OrderState = types.SimpleNamespace(
        StockDeal=types.SimpleNamespace(value="SDEAL"),
        FuturesDeal=types.SimpleNamespace(value="FDEAL"),
        StockOrder=types.SimpleNamespace(value="SORDER"),
        FuturesOrder=types.SimpleNamespace(value="FORDER"),
    )

    order_module = types.ModuleType("shioaji.order")
    order_module.Trade = object
    order_module.StockOrder = object

    position_module = types.ModuleType("shioaji.position")
    position_module.StockPosition = object
    position_module.SettlementV1 = object

    monkeypatch.setitem(sys.modules, "shioaji", shioaji_module)
    monkeypatch.setitem(sys.modules, "shioaji.constant", constant_module)
    monkeypatch.setitem(sys.modules, "shioaji.order", order_module)
    monkeypatch.setitem(sys.modules, "shioaji.position", position_module)
    sys.modules.pop("finlab.online.brokers.sinopac", None)

    module = importlib.import_module("finlab.online.brokers.sinopac")
    return importlib.reload(module)


def _make_account(
    sinopac_module: types.ModuleType, api: object
) -> object:
    account = sinopac_module.SinopacAccount.__new__(
        sinopac_module.SinopacAccount
    )
    account.api = api
    return account


def _forbid_fetch(api: object) -> None:
    api.fetch_contracts = lambda **kwargs: pytest.fail(
        "fetch_contracts must not be called on the shioaji >= 1.7 path"
    )


def test_sinopac_realtime_callbacks_cover_tick_book_order_fill_and_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    account.on_connection(
        lambda state, message="": connections.append((state, message))
    )

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


def test_sinopac_subscribe_ticks_and_bidask(monkeypatch: pytest.MonkeyPatch) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)

    account = _make_account(sinopac_module, _FakeShioaji())
    account._init_realtime()

    account.subscribe_ticks(["2330"])
    account.subscribe_bidask(["2330"])
    account.unsubscribe_ticks(["2330"])
    account.unsubscribe_bidask(["2330"])

    assert ("2330", "Tick") in account.api.quote.subscriptions
    assert ("2330", "BidAsk") in account.api.quote.subscriptions
    assert ("2330", "Tick") in account.api.quote.unsubscriptions
    assert ("2330", "BidAsk") in account.api.quote.unsubscriptions


def test_sinopac_resolves_otc_exchange_for_stocks_and_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)

    account = _make_account(sinopac_module, _FakeShioaji())
    account.trades = {}

    stocks = account.get_stocks(["2330", "8042"])

    assert sorted(stocks) == ["2330", "8042"]
    assert ("8042", "OTC") in account.api.snapshot_calls[-1]

    account.get_price_info = lambda: {"8042": {"漲停價": 110, "跌停價": 90}}
    order_id = account.create_order(
        sinopac_module.Action.BUY,
        stock_id="8042",
        quantity=1,
        price=100,
    )

    assert order_id == "order-1"
    assert account.api.placed_orders[0][0].code == "8042"
    assert account.api.placed_orders[0][0].exchange == "OTC"


class _FakeLegacyShioaji:
    """Mimics shioaji < 1.7: no lowercase ``contracts`` accessor.

    ``Contracts.Stocks`` is a plain dict, matching the legacy SDK's
    indexable, KeyError-on-miss lookup.
    """

    def __init__(
        self,
        contracts: dict[str, object] | None = None,
        fetch_result: dict[str, object] | None = None,
    ) -> None:
        self.Contracts = types.SimpleNamespace(Stocks=dict(contracts or {}))
        self._fetch_result = dict(fetch_result or {})
        self.fetch_calls: list[tuple[object, object]] = []

    def fetch_contracts(
        self, contract_download: object = False, contracts_timeout: object = 0
    ) -> None:
        self.fetch_calls.append((contract_download, contracts_timeout))
        # Like the real SDK, contracts_timeout=0 means a non-blocking fetch:
        # contracts are not available by the time this call returns.
        if contract_download and contracts_timeout:
            self.Contracts.Stocks.update(self._fetch_result)


def test_sinopac_get_contract_returns_present_contract_without_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    contract = types.SimpleNamespace(code="2330")
    api = _FakeLegacyShioaji(contracts={"2330": contract})
    account = _make_account(sinopac_module, api)

    assert account._get_contract("2330") is contract
    assert api.fetch_calls == []


def test_sinopac_get_contract_fetches_once_when_legacy_stocks_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    contract = types.SimpleNamespace(code="8421")
    api = _FakeLegacyShioaji(fetch_result={"8421": contract})
    account = _make_account(sinopac_module, api)

    assert account._get_contract("8421") is contract
    [(contract_download, contracts_timeout)] = api.fetch_calls
    assert contract_download is True
    assert contracts_timeout > 0


def test_sinopac_get_contract_modern_contracts_path_never_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    api = _FakeShioaji()
    _forbid_fetch(api)
    account = _make_account(sinopac_module, api)

    assert account._get_contract("2330").code == "2330"


def test_sinopac_get_contract_modern_miss_raises_without_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    api = _FakeShioaji()
    _forbid_fetch(api)
    account = _make_account(sinopac_module, api)

    with pytest.raises(KeyError):
        account._get_contract("9999")


def test_sinopac_get_contract_raises_when_still_missing_after_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    api = _FakeLegacyShioaji()
    account = _make_account(sinopac_module, api)

    with pytest.raises(KeyError):
        account._get_contract("9999")
    # The one-time download must not be re-run on a later miss.
    with pytest.raises(KeyError):
        account._get_contract("9999")
    assert len(api.fetch_calls) == 1


def test_sinopac_backfill_ticks_uses_historical_tick_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)

    account = _make_account(sinopac_module, _FakeShioaji())
    account._init_realtime()

    ticks = []
    account.on_tick(ticks.append)

    backfilled = account.backfill_ticks(["2330"], emit=True)

    assert len(backfilled["2330"]) == 2
    assert [tick.price for tick in backfilled["2330"]] == [581.0, 582.0]
    assert [tick.total_volume for tick in backfilled["2330"]] == [2, 3]
    assert [tick.tick_type for tick in backfilled["2330"]] == [1, 2]
    assert [tick.price for tick in ticks] == [581.0, 582.0]


_ODD_LOT_ORDER_ID = "odd-1"
_ODD_LOT_PRICE_INFO = {"2330": {"漲停價": 638.0, "跌停價": 522.0}}


def _odd_lot_trade(order_id: str = _ODD_LOT_ORDER_ID) -> types.SimpleNamespace:
    """A working intraday odd-lot buy of 300 shares of 2330."""
    return types.SimpleNamespace(
        contract=types.SimpleNamespace(code="2330", exchange="TSE"),
        order=types.SimpleNamespace(
            action="Buy",
            order_cond="Cash",
            daytrade_short=False,
            quantity=300,
            price=580.0,
            order_lot="IntradayOdd",
        ),
        status=types.SimpleNamespace(
            id=order_id,
            status="Submitted",
            deal_quantity=0,
            modified_price=0,
            order_datetime=None,
        ),
    )


class _FakeOrderShioaji(_FakeShioaji):
    """Shioaji fake holding one odd-lot order, with injectable failures."""

    def __init__(
        self,
        cancel_error: Exception | None = None,
        place_error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.cancel_error = cancel_error
        self.place_error = place_error
        self.cancelled: list[str] = []

    def update_status(self, account: object) -> None:
        pass

    def list_trades(self) -> list[types.SimpleNamespace]:
        return [] if self.cancelled else [_odd_lot_trade()]

    def cancel_order(self, trade: types.SimpleNamespace) -> None:
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancelled.append(trade.status.id)

    def place_order(
        self, contract: object, order: object
    ) -> types.SimpleNamespace:
        if self.place_error is not None:
            raise self.place_error
        return super().place_order(contract, order)


def _make_odd_lot_account(
    sinopac_module: types.ModuleType, api: _FakeOrderShioaji
) -> object:
    account = _make_account(sinopac_module, api)
    account.trades = {}
    account.get_price_info = lambda: _ODD_LOT_PRICE_INFO
    return account


def test_sinopac_update_odd_lot_order_cancels_and_replaces_remaining_shares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    api = _FakeOrderShioaji()
    account = _make_odd_lot_account(sinopac_module, api)

    account.update_order(_ODD_LOT_ORDER_ID, price=585.0)

    assert api.cancelled == [_ODD_LOT_ORDER_ID]
    [(contract, order)] = api.placed_orders
    assert contract.code == "2330"
    assert order.quantity == 300
    assert order.price == 585.0


def test_sinopac_update_odd_lot_order_raises_when_replace_fails_after_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    broker_error = ValueError("broker rejected order: price out of range")
    api = _FakeOrderShioaji(place_error=broker_error)
    account = _make_odd_lot_account(sinopac_module, api)

    with pytest.raises(sinopac_module.OddLotRepriceError) as excinfo:
        account.update_order(_ODD_LOT_ORDER_ID, price=585.0)

    message = str(excinfo.value)
    assert _ODD_LOT_ORDER_ID in message
    assert "2330" in message
    assert "300" in message
    assert "585.0" in message
    assert str(broker_error) in message
    assert excinfo.value.__cause__ is broker_error
    assert api.cancelled == [_ODD_LOT_ORDER_ID]


def test_sinopac_update_odd_lot_order_raises_when_replace_returns_no_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    api = _FakeOrderShioaji()
    account = _make_odd_lot_account(sinopac_module, api)
    # create_order returns "" when the stock is missing from price info.
    account.get_price_info = dict

    with pytest.raises(sinopac_module.OddLotRepriceError, match="no order id"):
        account.update_order(_ODD_LOT_ORDER_ID, price=585.0)

    assert api.placed_orders == []


def test_sinopac_update_odd_lot_order_keeps_original_when_cancel_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sinopac_module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    api = _FakeOrderShioaji(cancel_error=ValueError("order already filled"))
    account = _make_odd_lot_account(sinopac_module, api)

    account.update_order(_ODD_LOT_ORDER_ID, price=585.0)

    assert api.placed_orders == []
    assert list(account.get_orders()) == [_ODD_LOT_ORDER_ID]
    assert "order already filled" in caplog.text
