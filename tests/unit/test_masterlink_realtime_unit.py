from __future__ import annotations

import datetime
import importlib
import sys
import types
from typing import Any

import pytest

from finlab.online.core.account import Order
from finlab.online.core.enums import Action, OrderCondition, OrderStatus

from ..utils.mock_helpers import patch_utc_host_clock


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


class _FakeStockTradeApi:
    def __init__(self) -> None:
        self.modified_volumes: list[tuple[Any, Any, int]] = []
        self.modified_prices: list[tuple[Any, Any, str, Any]] = []
        self.placed_orders: list[Any] = []

    def place_order(self, account: Any, order: Any) -> Any:
        self.placed_orders.append(order)
        return types.SimpleNamespace(order_no="new-o-1")

    def modify_volume(self, account: Any, order_record: Any, quantity: int) -> None:
        self.modified_volumes.append((account, order_record, quantity))
        if quantity == 0:  # 刪單：剩餘量全數刪除
            order_record.cel_qty = getattr(order_record, "org_qty", 0) - getattr(
                order_record, "filled_qty", 0
            )

    def modify_price(
        self, account: Any, order_record: Any, price: str, price_type: Any
    ) -> None:
        self.modified_prices.append((account, order_record, price, price_type))


def _import_masterlink_module_with_fake_sdk(monkeypatch: Any) -> types.ModuleType:
    fake_sdk_module = types.ModuleType("masterlink_sdk")
    fake_sdk_module.MasterlinkSDK = object
    fake_sdk_module.Order = types.SimpleNamespace
    fake_sdk_module.Account = object
    fake_sdk_module.BSAction = types.SimpleNamespace(Buy="B", Sell="S")
    fake_sdk_module.MarketType = types.SimpleNamespace(
        Common="Common",
        IntradayOdd="IntradayOdd",
        Odd="Odd",
        EmgOdd="EmgOdd",
        Fixing="Fixing",
    )
    fake_sdk_module.PriceType = types.SimpleNamespace(
        Limit="Limit", LimitUp="LimitUp", LimitDown="LimitDown", Reference="Reference"
    )
    fake_sdk_module.TimeInForce = types.SimpleNamespace(ROD="ROD")
    fake_sdk_module.OrderType = types.SimpleNamespace(Stock="Stock")

    monkeypatch.setitem(sys.modules, "masterlink_sdk", fake_sdk_module)
    sys.modules.pop("finlab.online.brokers.masterlink", None)

    module = importlib.import_module("finlab.online.brokers.masterlink")
    return importlib.reload(module)


def _new_masterlink_account(monkeypatch: Any) -> tuple[types.ModuleType, Any]:
    masterlink_module = _import_masterlink_module_with_fake_sdk(monkeypatch)
    MasterlinkAccount = masterlink_module.MasterlinkAccount
    account = MasterlinkAccount.__new__(MasterlinkAccount)
    account.target_account = None
    return masterlink_module, account


def _make_finlab_order(market_type: Any) -> Order:
    order_record = types.SimpleNamespace(
        market_type=market_type,
        org_qty=500,
        filled_qty=120,
    )
    return Order(
        order_id="o-1",
        stock_id="2330",
        action=Action.BUY,
        price=560,
        quantity=500,
        filled_quantity=120,
        status=OrderStatus.NEW,
        order_condition=OrderCondition.CASH,
        time=datetime.datetime(2026, 6, 15),
        org_order=order_record,
    )


def test_masterlink_update_order_price_recreates_odd_lot_orders(
    monkeypatch: Any,
) -> None:
    masterlink_module = _import_masterlink_module_with_fake_sdk(monkeypatch)
    MasterlinkAccount = masterlink_module.MasterlinkAccount
    MarketType = masterlink_module.MarketType

    for market_type in (
        MarketType.IntradayOdd,
        MarketType.Odd,
        MarketType.EmgOdd,
    ):
        account = MasterlinkAccount.__new__(MasterlinkAccount)
        stock_api = _FakeStockTradeApi()
        target_account = types.SimpleNamespace(account="9809789")
        order = _make_finlab_order(market_type)
        created_orders: list[dict[str, Any]] = []

        account.sdk = types.SimpleNamespace(stock=stock_api)
        account.target_account = target_account
        account.get_orders = lambda order=order: {"o-1": order}

        def create_order(**kwargs: Any) -> str:
            created_orders.append(kwargs)
            return "new-o-1"

        account.create_order = create_order

        assert account.update_order("o-1", price=567.5) == "new-o-1"
        assert stock_api.modified_volumes == [
            (target_account, order.org_order, 0)
        ]
        assert stock_api.modified_prices == []
        assert created_orders == [
            {
                "action": Action.BUY,
                "stock_id": "2330",
                "quantity": 380,
                "price": 567.5,
                "odd_lot": True,
                "order_cond": OrderCondition.CASH,
            }
        ]


def test_masterlink_update_order_price_modifies_common_orders(
    monkeypatch: Any,
) -> None:
    masterlink_module = _import_masterlink_module_with_fake_sdk(monkeypatch)
    MasterlinkAccount = masterlink_module.MasterlinkAccount
    MarketType = masterlink_module.MarketType
    PriceType = masterlink_module.PriceType

    account = MasterlinkAccount.__new__(MasterlinkAccount)
    stock_api = _FakeStockTradeApi()
    target_account = types.SimpleNamespace(account="9809789")
    order = _make_finlab_order(MarketType.Common)

    account.sdk = types.SimpleNamespace(stock=stock_api)
    account.target_account = target_account
    account.get_orders = lambda: {"o-1": order}
    account.create_order = lambda **kwargs: "unexpected"

    assert account.update_order("o-1", price=567.5) is None
    assert stock_api.modified_volumes == []
    assert stock_api.modified_prices == [
        (target_account, order.org_order, "567.5", PriceType.Limit)
    ]


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


def test_masterlink_get_position_raises_instead_of_empty(monkeypatch: Any) -> None:
    _, account = _new_masterlink_account(monkeypatch)
    summary = types.SimpleNamespace(symbol="2330", current_quantity="1,500")
    inventories = lambda _: types.SimpleNamespace(position_summaries=[summary])
    account.sdk = types.SimpleNamespace(
        accounting=types.SimpleNamespace(inventories=inventories)
    )
    assert account.get_position().position[0]["quantity"] == 1.5

    def rate_limited(_: Any) -> Any:
        raise RuntimeError("rate limited")

    account.sdk.accounting.inventories = rate_limited
    with pytest.raises(RuntimeError):
        account.get_position()


def test_masterlink_stock_close_falls_back_to_reference(monkeypatch: Any) -> None:
    _, account = _new_masterlink_account(monkeypatch)
    quote = {"symbol": "2330", "referencePrice": 560.0, "previousClose": 555.0}
    assert account._create_finlab_stock(quote).close == 560.0
    assert account._create_finlab_stock({**quote, "closePrice": 568.0}).close == 568.0


@pytest.mark.parametrize(
    "org, filled, canceled, can_cancel, status",
    [
        (500, 0, 200, True, OrderStatus.NEW),
        (500, 100, 200, True, OrderStatus.PARTIALLY_FILLED),
        (500, 0, 500, False, OrderStatus.CANCEL),
        (10, 1, 9, True, OrderStatus.CANCEL),
        (500, 0, 0, True, OrderStatus.NEW),
    ],
)
def test_masterlink_reduced_order_status_uses_remaining_quantity(
    monkeypatch: Any, org: int, filled: int, canceled: int, can_cancel: bool,
    status: Any,
) -> None:
    _, account = _new_masterlink_account(monkeypatch)
    record = types.SimpleNamespace(
        buy_sell="B", order_type="Stock", order_date="20261021",
        order_time="090000000", order_no="o-1", symbol="2330", order_price=560,
        org_qty=org, filled_qty=filled, cel_qty=canceled, err_code="000000",
        can_cancel=can_cancel,
    )
    assert account._create_finlab_order(record).status == status


def test_masterlink_update_odd_lot_price_excludes_canceled_quantity(
    monkeypatch: Any,
) -> None:
    masterlink_module, account = _new_masterlink_account(monkeypatch)
    order = _make_finlab_order(masterlink_module.MarketType.IntradayOdd)
    order.org_order.cel_qty = 200
    created_orders: list[dict[str, Any]] = []
    account.sdk = types.SimpleNamespace(stock=_FakeStockTradeApi())
    account.get_orders = lambda: {"o-1": order}
    account.create_order = lambda **kwargs: created_orders.append(kwargs) or "new-o-1"

    account.update_order("o-1", price=567.5)
    assert created_orders[0]["quantity"] == 180


@pytest.mark.parametrize(
    "utc_time, odd_lot, market_type, price_type, price",
    [
        ((5, 40, 30), True, "Odd", "Limit", "560"),
        ((6, 0, 10), False, "Fixing", "Reference", None),
        ((1, 0, 0), False, "Common", "Limit", "560"),
        ((1, 0, 0), True, "IntradayOdd", "Limit", "560"),
    ],
)
def test_masterlink_create_order_session_uses_taipei_time(
    monkeypatch: Any, utc_time: tuple, odd_lot: bool, market_type: str,
    price_type: str, price: Any,
) -> None:
    masterlink_module, account = _new_masterlink_account(monkeypatch)
    instant = datetime.datetime(2026, 10, 21, *utc_time, tzinfo=datetime.timezone.utc)

    class _UtcHostDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    fake_datetime = types.SimpleNamespace(
        datetime=_UtcHostDatetime, time=datetime.time
    )
    monkeypatch.setattr(masterlink_module, "datetime", fake_datetime)
    stock_api = _FakeStockTradeApi()
    account.sdk = types.SimpleNamespace(stock=stock_api, marketdata=_FakeSdk().marketdata)

    assert account.create_order(Action.BUY, "2330", 1, price=560, odd_lot=odd_lot)
    placed = stock_api.placed_orders[0]
    assert (placed.market_type, placed.price_type, placed.price) == (
        market_type, price_type, price
    )


def _record(**kwargs: Any) -> Any:
    return types.SimpleNamespace(**{
        "order_no": "o-1", "symbol": "2330", "buy_sell": "B", "order_type": "Stock",
        "market_type": "Common", "price_type": "Limit", "order_price": 1000.0,
        "org_qty": 5000, "filled_qty": 0, "cel_qty": 0, "can_cancel": True,
        "err_code": "000000", "order_date": "20261026", "order_time": "090000000",
        **kwargs,
    })


def _account_with_order(monkeypatch: Any, record: Any) -> tuple[Any, Any, Any]:
    module, account = _new_masterlink_account(monkeypatch)
    stock_api = _FakeStockTradeApi()
    account.sdk = types.SimpleNamespace(stock=stock_api)
    account.get_orders = lambda: {"o-1": account._create_finlab_order(record)}
    return module, account, stock_api


def _timeout(*_: Any) -> None:
    raise RuntimeError("000008 Timeout")


def test_masterlink_cancel_order_raises_instead_of_reordering(monkeypatch: Any) -> None:
    _, account = _new_masterlink_account(monkeypatch)
    stock_api = _FakeStockTradeApi()
    account.sdk = types.SimpleNamespace(stock=stock_api)
    account.order_records = {"o-1": _record()}
    account.get_orders = lambda: pytest.fail("不應每刪一筆再查一次委託")
    account.cancel_order("o-1")
    assert stock_api.modified_volumes == [(None, account.order_records["o-1"], 0)]

    account.get_orders = lambda: None
    with pytest.raises(RuntimeError):
        account.cancel_order("o-2")

    # 快取裡還不可取消（等交易所確認）的委託，要重查後再刪
    pending, accepted = _record(order_no="o-3", can_cancel=False), _record(order_no="o-3")
    account.order_records["o-3"] = pending
    account.get_orders = lambda: account.order_records.update({"o-3": accepted}) or {}
    account.cancel_order("o-3")
    assert stock_api.modified_volumes[-1] == (None, accepted, 0)

    stock_api.modify_volume = _timeout
    with pytest.raises(RuntimeError):
        account.cancel_order("o-1")


def test_masterlink_total_balance_raises_when_queries_fail(monkeypatch: Any) -> None:
    _, account = _new_masterlink_account(monkeypatch)
    accounting = types.SimpleNamespace(
        skbank_balance=lambda _: types.SimpleNamespace(available_balance=50000.0),
        today_settlement=lambda _: types.SimpleNamespace(net_amount="0"),
        inventories=lambda _: types.SimpleNamespace(market_value="2000000"),
    )
    account.sdk = types.SimpleNamespace(accounting=accounting)
    assert account.get_total_balance() == 2_050_000

    accounting.inventories = _timeout
    with pytest.raises(RuntimeError):
        account.get_total_balance()
    # 即時餘額照樣送出，總淨值給 None（未知），不給偏小的數字
    update = account._get_realtime_balance()
    assert (update.cash, update.total_balance) == (50_000, None)
    accounting.skbank_balance = _timeout
    with pytest.raises(RuntimeError):
        account.get_cash()
    # 另一個來源有回應（帳戶不走新光銀交割）時維持原本的 0
    accounting.bank_balance = lambda _: []
    assert account.get_cash() == 0


@pytest.mark.parametrize("quantity, cel_qty", [(2, 3000), (0.5, 4500), (0, 0)])
def test_masterlink_update_order_quantity_is_new_remaining_lots(
    monkeypatch: Any, quantity: float, cel_qty: int
) -> None:
    record = _record()
    _, account, stock_api = _account_with_order(monkeypatch, record)
    account.update_order("o-1", quantity=quantity)
    assert stock_api.modified_volumes == [(None, record, cel_qty)]


@pytest.mark.parametrize("quantity", [5, 6])
def test_masterlink_update_order_rejects_quantity_increase(
    monkeypatch: Any, quantity: float
) -> None:
    _, account, stock_api = _account_with_order(monkeypatch, _record())
    with pytest.raises(ValueError):
        account.update_order("o-1", quantity=quantity)
    assert stock_api.modified_volumes == []


def test_masterlink_reprice_limit_down_order_before_open_modifies_price(
    monkeypatch: Any,
) -> None:
    record = _record(price_type="LimitDown", org_qty=3000, filled_qty=1000)
    module, account, stock_api = _account_with_order(monkeypatch, record)
    patch_utc_host_clock(monkeypatch, module, (0, 30))  # 台北 08:30
    account.create_order = lambda **_: pytest.fail("開盤前可直接改價，不應刪單重下")
    account.update_order("o-1", price=1005)
    assert stock_api.modified_prices == [(None, record, "1005", "Limit")]


def _fill_1000_then_cancel(record: Any) -> None:
    record.filled_qty += 1000
    record.cel_qty = record.org_qty - record.filled_qty


@pytest.mark.parametrize(
    "quantity, before_cancel, created_lots",
    [
        (None, None, 2.0),
        (1, None, 1.0),
        (0, None, None),
        (None, _fill_1000_then_cancel, 1.0),  # 刪單前一刻成交的 1 張不重下
        (1, _fill_1000_then_cancel, None),  # 剩 1 張的要求已由這 1 張成交滿足
    ],
)
def test_masterlink_reprice_limit_down_order_intraday_replaces(
    monkeypatch: Any, quantity: float | None, before_cancel: Any,
    created_lots: float | None,
) -> None:
    record = _record(price_type="LimitDown", org_qty=3000, filled_qty=1000)
    module, account, stock_api = _account_with_order(monkeypatch, record)
    patch_utc_host_clock(monkeypatch, module, (1, 30))  # 台北 09:30
    if before_cancel:
        stock_api.modify_volume = lambda *args: (
            stock_api.modified_volumes.append(args), before_cancel(record)
        )
    created: list[dict[str, Any]] = []
    account.create_order = lambda **kwargs: created.append(kwargs) or "new-o-1"

    new_order_id = account.update_order("o-1", price=1005, quantity=quantity)
    if created_lots is None:
        assert (new_order_id, created) == (None, [])
        assert stock_api.modified_volumes == [(None, record, 0)]
    else:
        assert new_order_id == "new-o-1"
        assert created == [{
            "action": Action.BUY, "stock_id": "2330", "quantity": created_lots,
            "price": 1005, "odd_lot": False, "order_cond": OrderCondition.CASH,
        }]


@pytest.mark.parametrize("failure", ["replace", "cancel", "unconfirmed"])
def test_masterlink_reprice_by_replace_raises_on_failure(
    monkeypatch: Any, failure: str
) -> None:
    record = _record(price_type="LimitDown", org_qty=3000, filled_qty=1000)
    module, account, stock_api = _account_with_order(monkeypatch, record)
    patch_utc_host_clock(monkeypatch, module, (1, 30))  # 台北 09:30
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    account.create_order = lambda **_: pytest.fail("不應重下")
    if failure == "replace":
        account.create_order = lambda **_: None
    elif failure == "cancel":  # 原委託還在跌停，要報錯
        stock_api.modify_volume = _timeout
    else:  # 刪單後查不到委託，不知道刪了多少
        stock_api.modify_volume = lambda *_: setattr(account, "get_orders", lambda: None)
    with pytest.raises(RuntimeError):
        account.update_order("o-1", price=1005)


@pytest.mark.parametrize(
    "action, kwargs",
    [(Action.BUY, {"best_price_limit": True}), (Action.BUY, {"price": 559}),
     (Action.SELL, {"price": 561})],
)
def test_masterlink_fixing_session_rejects_prices_not_filled_at_close(
    monkeypatch: Any, action: Any, kwargs: dict[str, Any]
) -> None:
    module, account = _new_masterlink_account(monkeypatch)
    patch_utc_host_clock(monkeypatch, module, (6, 10))  # 台北 14:10
    stock_api = _FakeStockTradeApi()
    account.sdk = types.SimpleNamespace(stock=stock_api, marketdata=_FakeSdk().marketdata)
    with pytest.raises(ValueError):
        account.create_order(action, "2330", 1, **kwargs)
    assert stock_api.placed_orders == []


def test_masterlink_settlement_on_monday_includes_friday_trades(monkeypatch: Any) -> None:
    module, account = _new_masterlink_account(monkeypatch)
    # 2026-10-26 是週一，台北 09:00
    patch_utc_host_clock(monkeypatch, module, (1, 0), date=(2026, 10, 26))
    rows = [
        ("20261021", "20261023", "-50,000.00"),
        ("20261022", "20261026", "-300,000.00"),
        ("20261023", "20261027", "-1,000,000.00"),
    ]

    def history_settlement(_: Any, start: str, end: str) -> Any:
        return types.SimpleNamespace(settlements=[
            types.SimpleNamespace(t_date=t, s_date=s, net_amount=n)
            for t, s, n in rows if start <= t <= end
        ])

    account.sdk = types.SimpleNamespace(accounting=types.SimpleNamespace(
        history_settlement=history_settlement,
        today_settlement=lambda _: types.SimpleNamespace(net_amount="-300000.00"),
    ))
    assert account.get_settlement() == -1_300_000


def test_masterlink_fixing_best_price_limit_rejected_before_cancelling(monkeypatch: Any) -> None:
    from finlab.online.core.executor import OrderExecutor
    from finlab.online.core.position import Position

    module, account = _new_masterlink_account(monkeypatch)
    patch_utc_host_clock(monkeypatch, module, (2, 0))  # 台北 10:00
    assert account.support_best_price_limit()

    patch_utc_host_clock(monkeypatch, module, (6, 10))  # 台北 14:10
    account.get_orders = lambda: pytest.fail("不應先查委託、刪舊單")
    with pytest.raises(ValueError, match="best_price_limit"):
        OrderExecutor(Position({}), account).create_orders(best_price_limit=True)
