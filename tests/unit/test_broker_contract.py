"""所有券商 adapter 都要通過的共同契約（order_executor#75）

新增券商就在 BROKERS 加一個 builder，契約本身不為個別券商放寬。只用 mock，不登入、不送單。
"""

from __future__ import annotations

import contextlib
import datetime
import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace as NS
from typing import Any

import pandas as pd
import pytest

from finlab.online.core.account import (
    Order,
    Stock,
    TWSession,
    TWStockAccount,
    tw_session,
)
from finlab.online.core.enums import Action, OrderCondition, OrderStatus
from finlab.online.core.executor import OrderExecutor
from finlab.online.core.position import Position

from ..utils.mock_helpers import patch_utc_host_clock
from .test_binance_order_safety_unit import _account as _binance_account
from .test_fubon_order_safety_unit import _balance_account, _capture_orders
from .test_fugle_order_safety_unit import _account as _fugle_account
from .test_fugle_order_safety_unit import _import_fugle, _row
from .test_kgi_account_unit import SDK as KGI_SDK
from .test_kgi_account_unit import SNAP, _Order
from .test_masterlink_realtime_unit import (
    _FakeStockTradeApi,
    _new_masterlink_account,
    _record,
)
from .test_pocket_order_unit import _make_account as _pocket_account
from .test_schwab_order_safety_unit import _account as _schwab_account
from .test_schwab_order_safety_unit import _response
from .test_sinopac_realtime_unit import (
    _FakeOrderShioaji,
    _import_sinopac_module_with_fake_sdk,
    _make_odd_lot_account,
    _odd_lot_trade,
)
from .test_yuanta_account_unit import ACCOUNT, _fake_sdk, _FakeSpark, _List

CLOSE, LIMIT_UP, LIMIT_DOWN = 580.0, 616.0, 504.0
REFERENCE = "reference"


@dataclass
class Broker:
    account: Any
    placed: Callable[[], list[Any]]
    lot_of: Callable[[Any], Any]
    price_of: Callable[[Any], Any]
    lots: tuple[Any, Any, Any, Any]  # SDK 時段參數：整股、盤中零股、盤後零股、定盤
    is_market: Callable[[Any], bool] = lambda _: False
    failure: Any = None  # SDK 查詢失敗但不拋例外時的回傳值
    reprice: dict[str, Callable[[], Any]] = field(default_factory=dict)
    target: dict[str, float] = field(default_factory=lambda: {"2330": 1})


def _raise(*_: Any, **__: Any) -> Any:
    raise TimeoutError("sdk timeout")


def _reject(*_: Any, **__: Any) -> Any:
    raise ValueError("broker rejected")


def _order(org_order: Any, order_id: str = "o-1") -> Order:
    return Order(
        order_id, "2330", Action.BUY, 500.0, 2, 0, OrderStatus.NEW, OrderCondition.CASH,
        datetime.datetime(2026, 10, 21, 9, 30), org_order,
    )  # fmt: skip


def _fubon(monkeypatch: Any) -> Broker:
    account = _balance_account(monkeypatch, "Stock", {})
    account.quotes["2330"] = {"symbol": "2330", "closePrice": CLOSE}
    placed = _capture_orders(account)
    stock = account.sdk.stock

    def arm(market_type: str, **sdk: Any) -> Callable[[], str]:
        def armed() -> str:
            account.get_orders = lambda: {"o-1": _order(NS(market_type=market_type))}
            stock.make_modify_price_obj = stock.make_modify_quantity_obj = lambda *_: (
                "req"
            )
            for name, fn in sdk.items():
                setattr(stock, name, fn)
            return "o-1"

        return armed

    return Broker(
        account, lambda: placed,
        lambda o: o["market_type"],
        lambda o: REFERENCE if o["price_type"] == "Reference" else float(o["price"]),
        ("Common", "IntradayOdd", "Odd", "Fixing"),
        is_market=lambda o: o["price_type"] == "Market",
        failure=NS(is_success=False, message="rate limit", data=None),
        reprice={
            "board_lot": arm("Common", modify_price=_raise),
            "odd_lot": arm(
                "IntradayOdd",
                modify_quantity=lambda *_: NS(is_success=False, message="rejected"),
            ),
        },
    )  # fmt: skip


def _taishin(monkeypatch: Any) -> Broker:
    _, account = _new_masterlink_account(monkeypatch)
    stock = _FakeStockTradeApi()
    stock.get_order_results = lambda _: []
    account.sdk = NS(
        stock=stock,
        accounting=NS(
            skbank_balance=lambda _: NS(available_balance=100.0),
            bank_balance=lambda _: [NS(available_balance=100.0)],
            history_settlement=lambda *_: NS(settlements=[]),
            today_settlement=lambda _: NS(net_amount="0"),
            inventories=lambda _: NS(position_summaries=[], market_value="0"),
        ),
        marketdata=NS(
            rest_client=NS(
                stock=NS(intraday=NS(quote=lambda symbol: {"symbol": symbol, "closePrice": CLOSE}))
            )
        ),
    )  # fmt: skip

    def arm(market_type: str, **sdk: Any) -> Callable[[], str]:
        def armed() -> str:
            record = _record(market_type=market_type, org_qty=2000)
            account.get_orders = lambda: {"o-1": account._create_finlab_order(record)}
            for name, fn in sdk.items():
                setattr(stock, name, fn)
            return "o-1"

        return armed

    return Broker(
        account, lambda: stock.placed_orders,
        lambda o: o.market_type,
        lambda o: REFERENCE if o.price_type == "Reference" else float(o.price),
        ("Common", "IntradayOdd", "Odd", "Fixing"),
        is_market=lambda o: o.price_type == "Market",
        reprice={
            "board_lot": arm("Common", modify_price=_raise),
            "odd_lot": arm("IntradayOdd", modify_volume=_raise),
        },
    )  # fmt: skip


def _fugle(monkeypatch: Any) -> Broker:
    module = _import_fugle(monkeypatch)
    placed: list[dict[str, Any]] = []
    results = [_row(ap_code="1")]
    sdk = NS(
        place_order=lambda o: placed.append(o) or {"ord_no": "A1"},
        cancel_order=lambda o: None,
        modify_price=lambda *_: None,
        get_order_results=lambda: results,
        get_inventories=list,
        get_balance=lambda: {"available_balance": 100},
        get_settlements=list,
    )
    account = _fugle_account(module, sdk)
    account.market_api_key = "key"
    quote = {
        "symbol": "2330", "closePrice": CLOSE, "openPrice": CLOSE, "highPrice": CLOSE,
        "lowPrice": CLOSE, "lastTrade": {},
    }  # fmt: skip
    monkeypatch.setattr(module.requests, "get", lambda *_, **__: NS(json=lambda: quote))

    def arm(row: dict[str, Any], **calls: Any) -> Callable[[], str]:
        def armed() -> str:
            results[0] = row
            account.get_orders()
            for name, fn in calls.items():
                setattr(sdk, name, fn)
            return "B1"

        return armed

    return Broker(
        account, lambda: placed,
        lambda o: o["ap_code"],
        lambda o: float(o["price"]),
        ("1", "5", "3", "2"),
        reprice={
            "board_lot": arm(_row(ap_code="1"), modify_price=_reject),
            "odd_lot": arm(_row(), cancel_order=_raise),
        },
    )  # fmt: skip


def _sinopac(monkeypatch: Any) -> Broker:
    module = _import_sinopac_module_with_fake_sdk(monkeypatch)
    api = _FakeOrderShioaji()
    account = _make_odd_lot_account(module, api)
    account.get_price_info = lambda: {
        "2330": {"漲停價": LIMIT_UP, "跌停價": LIMIT_DOWN}
    }
    api.snapshots = _shioaji_snapshots
    api.list_positions = lambda *_, **__: []
    api.account_balance = lambda: NS(acc_balance=100.0, errmsg="")
    api.settlements = lambda *_: []

    def board_lot() -> str:
        trade = _odd_lot_trade()
        trade.order.order_lot = "Common"
        api.list_trades = lambda: [trade]
        api.update_order = _reject
        return "odd-1"

    def cancel_raises() -> str:
        api.cancel_error = ValueError("order already filled")
        return "odd-1"

    def cancel_reports_failed() -> str:
        api.cancel_order = lambda trade: NS(status=NS(status="Failed", msg="rejected"))
        return "odd-1"

    return Broker(
        account, lambda: api.placed_orders,
        lambda o: o[1].order_lot,
        lambda o: float(o[1].price),
        ("Common", "IntradayOdd", "Odd", "Fixing"),
        is_market=lambda o: o[1].price_type == "MKT",
        reprice={
            "board_lot": board_lot,
            "odd_lot": cancel_raises,
            "odd_lot_failed_status": cancel_reports_failed,
        },
    )  # fmt: skip


def _shioaji_snapshots(contracts: list[Any]) -> list[NS]:
    return [
        NS(code=c.code, open=CLOSE, high=CLOSE, low=CLOSE, close=CLOSE, buy_price=CLOSE,
           sell_price=CLOSE, buy_volume=1, sell_volume=1, change_rate=0.0)
        for c in contracts
    ]  # fmt: skip


def _pocket(monkeypatch: Any) -> Broker:
    account = _pocket_account(monkeypatch)
    sys.modules["pocketx"].contracts = NS(Contract=lambda **kw: NS(**kw))
    api = account.api
    account.get_price_info = lambda: {
        "2330": {"漲停價": LIMIT_UP, "跌停價": LIMIT_DOWN, "收盤價": CLOSE}
    }
    api.snapshots = _shioaji_snapshots
    api.update_status = lambda *_: None
    api.list_trades = lambda: [NS(order=NS(entid="p-1"))]
    api.list_positions = lambda *_, **__: []
    api.account_balance = lambda: NS(acc_balance=100, errmsg="")
    api.settlements = lambda *_: []

    def board_lot() -> str:
        api.update_order = _reject
        return "p-1"

    return Broker(
        account, lambda: api.placed_orders,
        lambda o: o.order_lot,
        lambda o: float(o.price),
        ("Common", "IntradayOdd", "Odd", "Fixing"),
        is_market=lambda o: o.price_type == "MKT",
        reprice={"board_lot": board_lot},
    )  # fmt: skip


def _kgi(monkeypatch: Any) -> Broker:
    monkeypatch.setitem(sys.modules, "kgisuperpy", KGI_SDK)
    sys.modules.pop("finlab.online.brokers.kgi", None)
    module = importlib.import_module("finlab.online.brokers.kgi")
    account = module.KGIAccount.__new__(module.KGIAccount)
    order = _Order()
    account.api = NS(
        Order=order,
        Data=NS(get_snapshots=lambda ids: {i: SNAP for i in ids}),
        Account=NS(
            InventorySum=lambda *_: pd.DataFrame(),
            SettleAmt=lambda *_: pd.DataFrame(),
        ),
    )

    def arm(quantity: int, odd_lot: bool, **calls: Any) -> Callable[[], str]:
        def armed() -> str:
            order_id = account.create_order(
                Action.BUY, "2330", quantity, price=500, odd_lot=odd_lot
            )
            order.calls.clear()
            for name, fn in calls.items():
                setattr(order, name, fn)
            return order_id

        return armed

    return Broker(
        account, lambda: order.calls,
        lambda o: o["odd_lot"].name,
        lambda o: float(o["price"]),
        ("Common", "Odd", "Odd_AfterMarket", "Fixing"),
        reprice={
            "board_lot": arm(2, False, update_order=_reject),
            "odd_lot": arm(300, True, cancel_order=lambda *_: None),
        },
    )  # fmt: skip


def _yuanta(monkeypatch: Any) -> Broker:
    sys.modules.pop("finlab.online.brokers.yuanta", None)
    module = importlib.import_module("finlab.online.brokers.yuanta")
    account = module.YuantaAccount.__new__(module.YuantaAccount)
    account.account = ACCOUNT
    account._init_state()
    account._sdk, account._List = _fake_sdk(None), _List
    api = account.api = _FakeSpark(account)

    def arm(quantity: int, odd_lot: bool) -> Callable[[], str]:
        def armed() -> str:
            order_id = account.create_order(
                Action.BUY, "2330", quantity, price=500, odd_lot=odd_lot
            )
            api.sent.clear()
            api.reject = True
            return order_id

        return armed

    return Broker(
        account, lambda: [o for o in api.sent if o.TradeKind == 0],
        lambda o: o.APCode,
        lambda o: float(o.Price),
        (0, 4, 2, 7),
        is_market=lambda o: o.PriceFlag == "M",
        failure=False,
        reprice={"board_lot": arm(2, False), "odd_lot": arm(300, True)},
    )  # fmt: skip


def _binance(monkeypatch: Any) -> Broker:
    account = _binance_account(monkeypatch)
    client = account.simple_client.client

    def cancel_raises() -> str:
        client.order = {
            "side": "BUY",
            "origQty": "1",
            "executedQty": "0",
            "price": "60000",
        }
        client.cancel_order = _raise
        return "BTCUSDT|7"

    return Broker(
        account, lambda: client.created, lambda o: None, lambda o: None, (None,) * 4,
        reprice={"cancel": cancel_raises}, target={"BTCUSDT": 0.1},
    )  # fmt: skip


def _schwab(monkeypatch: Any) -> Broker:
    account = _schwab_account(monkeypatch, cancel_status=400)
    return Broker(
        account, lambda: account.client.placed, lambda o: None, lambda o: None, (None,) * 4,
        failure=_response(500), reprice={"cancel": lambda: 1}, target={"AAPL": 1},
    )  # fmt: skip


class _SdkOnlyAccount(TWStockAccount):
    """只實作 SDK 呼叫的假 adapter：時段與定盤規則全部來自共同層"""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def session_params(self) -> dict[TWSession, Any]:
        return {session: session.value for session in TWSession}

    def create_order(
        self, action: Action, stock_id: str, quantity: float, price: float | None = None,
        odd_lot: bool = False, market_order: bool = False, best_price_limit: bool = False,
        order_cond: OrderCondition = OrderCondition.CASH,
    ) -> str | None:  # fmt: skip
        plan = self._plan_order(
            action, stock_id, price, odd_lot=odd_lot, market_order=market_order,
            best_price_limit=best_price_limit,
        )  # fmt: skip
        if plan is None:
            return None
        self.sent.append({"lot": plan.session_param, "price": plan.price})
        return "sdk-order"

    def get_stocks(self, stock_ids: list[str]) -> dict[str, Stock]:
        return {s: Stock(s, 0, 0, 0, CLOSE, 0, 0, 0, 0) for s in stock_ids}

    def update_order(self, order_id: str, price: float | None = None, quantity: float | None = None) -> None: ...  # fmt: skip
    def cancel_order(self, order_id: str) -> None: ...
    def get_orders(self) -> dict[str, Order]: return {}  # fmt: skip

    def get_position(self) -> Position: return Position({})  # fmt: skip

    def get_total_balance(self) -> int: return 0  # fmt: skip

    def get_cash(self) -> int: return 0  # fmt: skip

    def get_settlement(self) -> int: return 0  # fmt: skip


def _sdk_only(monkeypatch: Any) -> Broker:
    account = _SdkOnlyAccount()
    return Broker(
        account, lambda: account.sent, lambda o: o["lot"], lambda o: o["price"],
        ("common", "intraday_odd", "after_hours_odd", "fixing"),
    )  # fmt: skip


BROKERS: dict[str, Callable[[Any], Broker]] = {
    "fubon": _fubon, "taishin": _taishin, "fugle": _fugle, "sinopac": _sinopac,
    "pocket": _pocket, "kgi": _kgi, "yuanta": _yuanta, "binance": _binance, "schwab": _schwab,
}  # fmt: skip
TW_BROKERS = [
    "fubon",
    "taishin",
    "fugle",
    "sinopac",
    "pocket",
    "kgi",
    "yuanta",
    "sdk_only",
]
BROKERS["sdk_only"] = _sdk_only
REAL_BROKERS = [name for name in BROKERS if name != "sdk_only"]

_FUGLE_Q = {"position": "sdk.get_inventories", "orders": "sdk.get_order_results",
            "cash": "sdk.get_balance", "settlement": "sdk.get_settlements"}  # fmt: skip
_SHIOAJI_Q = {"position": "api.list_positions", "orders": "api.list_trades",
              "cash": "api.account_balance", "settlement": "api.settlements"}  # fmt: skip
_FUBON_Q = {"position": "sdk.accounting.unrealized_gains_and_loses",
            "orders": "sdk.stock.get_order_results", "cash": "sdk.accounting.bank_remain",
            "settlement": "sdk.accounting.query_settlement"}  # fmt: skip
_YUANTA_Q = {"position": "api.GetStoreSummary", "orders": "api.GetOrderTradeReport",
             "cash": "api.GetBankBalance", "settlement": "api.GetStkTransactionOutlay"}  # fmt: skip
_TAISHIN_CASH = ("sdk.accounting.skbank_balance", "sdk.accounting.bank_balance")
_BINANCE_ACCOUNT = "simple_client.client.get_account"
_SCHWAB_ACCOUNT = "client.get_accounts"


def _standard(paths: dict[str, str]) -> dict[str, list[tuple[str, ...]]]:
    return {
        "get_position": [(paths["position"],)],
        "get_orders": [(paths["orders"],)],
        "get_cash": [(paths["cash"],)],
        "get_settlement": [(paths["settlement"],)],
        "get_total_balance": [
            (paths["position"],), (paths["cash"],), (paths["settlement"],),
        ],
    }  # fmt: skip


QUERIES: dict[str, dict[str, list[tuple[str, ...]]]] = {
    "fubon": _standard(_FUBON_Q),
    "fugle": _standard(_FUGLE_Q),
    "sinopac": _standard(_SHIOAJI_Q),
    "pocket": _standard(_SHIOAJI_Q),
    "yuanta": _standard(_YUANTA_Q),
    "taishin": {
        "get_position": [("sdk.accounting.inventories",)],
        "get_orders": [("sdk.stock.get_order_results",)],
        "get_cash": [_TAISHIN_CASH],
        "get_settlement": [
            ("sdk.accounting.history_settlement",),
            ("sdk.accounting.today_settlement",),
        ],
        "get_total_balance": [
            ("sdk.accounting.inventories",),
            _TAISHIN_CASH,
            ("sdk.accounting.today_settlement",),
        ],
    },  # fmt: skip
    "kgi": {
        "get_position": [("api.Account.InventorySum",)],
        "get_orders": [("api.Order.get_trades",)],
        "get_settlement": [("api.Account.SettleAmt",)],
        # 凱基 API 沒有銀行餘額查詢，永遠報錯
        "get_cash": [()],
        "get_total_balance": [()],
    },
    "binance": {
        "get_position": [(_BINANCE_ACCOUNT,)],
        "get_orders": [("simple_client.client.get_open_orders",)],
        "get_cash": [(_BINANCE_ACCOUNT,)],
        "get_total_balance": [
            (_BINANCE_ACCOUNT,),
            ("simple_client.client.get_all_tickers",),
        ],
    },  # 幣安沒有交割款，get_settlement 固定回 0
    "schwab": {
        "get_position": [(_SCHWAB_ACCOUNT,)],
        "get_orders": [("client.get_orders_for_account",)],
        "get_cash": [(_SCHWAB_ACCOUNT,)],
        "get_total_balance": [(_SCHWAB_ACCOUNT,)],
        "get_settlement": [()],  # 嘉信未實作，永遠報錯
    },
}
QUERY_CASES = [
    (name, query, group)
    for name, queries in QUERIES.items()
    for query, groups in queries.items()
    for group in groups
]


@pytest.fixture
def no_sleep(monkeypatch: Any) -> None:
    monkeypatch.setattr("time.sleep", lambda *_: None)


def _freeze(monkeypatch: Any, broker: Broker, taipei: tuple[int, int, int]) -> None:
    hour, minute, second = taipei
    module = sys.modules[type(broker.account).__module__]
    patch_utc_host_clock(monkeypatch, module, (hour - 8, minute, second))


def _set_path(root: Any, path: str, value: Any) -> None:
    *parents, attr = path.split(".")
    for name in parents:
        root = getattr(root, name)
    setattr(root, attr, value)


@pytest.mark.usefixtures("no_sleep")
@pytest.mark.parametrize("mode", ["raises", "failure_value"])
@pytest.mark.parametrize("name, query, group", QUERY_CASES)
def test_query_failure_raises_instead_of_empty(
    monkeypatch: Any, name: str, query: str, group: tuple[str, ...], mode: str
) -> None:
    broker = BROKERS[name](monkeypatch)
    failing = _raise if mode == "raises" else (lambda *_, **__: broker.failure)
    for path in group:
        _set_path(broker.account, path, failing)
    with pytest.raises(Exception):
        getattr(broker.account, query)()


@pytest.mark.parametrize("name", ["sinopac", "pocket"])
def test_balance_query_reporting_error_raises(monkeypatch: Any, name: str) -> None:
    broker = BROKERS[name](monkeypatch)
    broker.account.api.account_balance = lambda: NS(acc_balance=0, errmsg="timeout")
    with pytest.raises(RuntimeError):
        broker.account.get_cash()


@pytest.mark.parametrize("name", TW_BROKERS)
@pytest.mark.parametrize(
    "taipei, odd_lot, lot",
    [
        ((13, 39, 59), True, 1),
        ((13, 40, 0), True, 2),
        ((14, 29, 59), True, 2),
        ((14, 30, 0), True, 1),
        ((10, 0, 0), True, 1),
        ((13, 59, 59), False, 0),
        ((14, 0, 0), False, 3),
        ((14, 29, 59), False, 3),
        ((14, 30, 0), False, 0),
        ((10, 0, 0), False, 0),
    ],
)
def test_session_boundaries(
    monkeypatch: Any, name: str, taipei: tuple[int, int, int], odd_lot: bool, lot: int
) -> None:
    broker = BROKERS[name](monkeypatch)
    _freeze(monkeypatch, broker, taipei)
    broker.account.create_order(Action.BUY, "2330", 1, price=CLOSE, odd_lot=odd_lot)
    assert [broker.lot_of(o) for o in broker.placed()] == [broker.lots[lot]]


FIXING_TIME = (14, 10, 0)


@pytest.mark.parametrize("name", TW_BROKERS)
@pytest.mark.parametrize(
    "action, kwargs",
    [
        (Action.BUY, {"price": CLOSE, "best_price_limit": True}),
        (Action.SELL, {"price": CLOSE, "best_price_limit": True}),
        (Action.BUY, {"price": CLOSE - 10}),
        (Action.SELL, {"price": CLOSE + 10}),
    ],
)
def test_fixing_skips_orders_not_filled_at_close(
    monkeypatch: Any, name: str, action: Action, kwargs: dict[str, Any]
) -> None:
    broker = BROKERS[name](monkeypatch)
    _freeze(monkeypatch, broker, FIXING_TIME)
    assert not broker.account.create_order(action, "2330", 1, **kwargs)
    assert broker.placed() == []


@pytest.mark.parametrize("name", TW_BROKERS)
@pytest.mark.parametrize(
    "action, kwargs",
    [
        (Action.BUY, {"price": CLOSE}),
        (Action.BUY, {"price": CLOSE + 10}),
        (Action.SELL, {"price": CLOSE - 10}),
        (Action.BUY, {"price": CLOSE, "market_order": True}),
        (Action.SELL, {"price": CLOSE, "market_order": True}),
    ],
)
def test_fixing_sends_at_close_and_never_market(
    monkeypatch: Any, name: str, action: Action, kwargs: dict[str, Any]
) -> None:
    broker = BROKERS[name](monkeypatch)
    _freeze(monkeypatch, broker, FIXING_TIME)
    broker.account.create_order(action, "2330", 1, **kwargs)
    [order] = broker.placed()
    assert broker.lot_of(order) == broker.lots[3]
    assert broker.price_of(order) in (CLOSE, REFERENCE)
    assert not broker.is_market(order)


@pytest.mark.parametrize("name", TW_BROKERS)
def test_fixing_without_close_price_does_not_send(monkeypatch: Any, name: str) -> None:
    broker = BROKERS[name](monkeypatch)
    _freeze(monkeypatch, broker, FIXING_TIME)
    broker.account.get_stocks = lambda stock_ids: {}
    assert not broker.account.create_order(Action.BUY, "2330", 1, price=CLOSE)
    assert broker.placed() == []


@pytest.mark.parametrize("name", TW_BROKERS)
@pytest.mark.parametrize("kwargs", [{"market_order": True}, {"best_price_limit": True}])
def test_after_hours_odd_lot_is_never_a_market_order(
    monkeypatch: Any, name: str, kwargs: dict[str, Any]
) -> None:
    broker = BROKERS[name](monkeypatch)
    _freeze(monkeypatch, broker, (13, 50, 0))
    broker.account.create_order(
        Action.BUY, "2330", 1, price=CLOSE, odd_lot=True, **kwargs
    )
    [order] = broker.placed()
    assert broker.lot_of(order) == broker.lots[2]
    assert not broker.is_market(order)


@pytest.mark.parametrize("name", REAL_BROKERS)
@pytest.mark.parametrize(
    "kwargs",
    [
        {"market_order": True, "best_price_limit": True},
        {"extra_bid_pct": 0.5},
        {"buy_only": True, "sell_only": True},
        {"progress": 2},
        {"progress": 0.5, "progress_precision": None},
    ],
)
def test_invalid_arguments_raise_before_cancelling(
    monkeypatch: Any, name: str, kwargs: dict[str, Any]
) -> None:
    broker = BROKERS[name](monkeypatch)
    cancelled: list[str] = []
    broker.account.get_orders = lambda: {"old": _order(None, "old")}
    broker.account.cancel_order = cancelled.append
    with pytest.raises(ValueError):
        OrderExecutor(Position(broker.target), broker.account).create_orders(**kwargs)
    assert cancelled == []
    assert broker.placed() == []


def test_wrong_quote_currency_raises_before_cancelling(monkeypatch: Any) -> None:
    broker = BROKERS["binance"](monkeypatch)
    cancelled: list[str] = []
    broker.account.get_orders = lambda: {"old": _order(None, "old")}
    broker.account.cancel_order = cancelled.append
    with pytest.raises(ValueError):
        OrderExecutor(Position({"BTC": 1}), broker.account).create_orders()
    assert cancelled == []


@pytest.mark.usefixtures("no_sleep")
@pytest.mark.parametrize(
    "name, case",
    [
        (name, case)
        for name, cases in {
            "fubon": ("board_lot", "odd_lot"),
            "taishin": ("board_lot", "odd_lot"),
            "fugle": ("board_lot", "odd_lot"),
            "sinopac": ("board_lot", "odd_lot", "odd_lot_failed_status"),
            "pocket": ("board_lot",),
            "kgi": ("board_lot", "odd_lot"),
            "yuanta": ("board_lot", "odd_lot"),
            "binance": ("cancel",),
            "schwab": ("cancel",),
        }.items()
        for case in cases
    ],
)
def test_failed_reprice_does_not_place_a_new_order(
    monkeypatch: Any, name: str, case: str
) -> None:
    broker = BROKERS[name](monkeypatch)
    if name in TW_BROKERS:
        _freeze(monkeypatch, broker, (10, 0, 0))
    order_id = broker.reprice[case]()
    with contextlib.suppress(Exception):
        broker.account.update_order(order_id, price=CLOSE + 1)
    assert broker.placed() == []


def test_fugle_failed_odd_lot_cancel_leaves_no_reorder_callback(
    monkeypatch: Any,
) -> None:
    broker = BROKERS["fugle"](monkeypatch)
    module = sys.modules[type(broker.account).__module__]
    module.callbacks.clear()
    order_id = broker.reprice["odd_lot"]()
    broker.account.update_order(order_id, price=CLOSE + 1)
    assert module.callbacks == {}


def test_tw_session_requires_timezone_and_converts_to_taipei() -> None:
    with pytest.raises(ValueError):
        tw_session(True, datetime.datetime(2026, 10, 21, 13, 40))
    utc_host = datetime.datetime(2026, 10, 21, 5, 40, tzinfo=datetime.timezone.utc)
    assert tw_session(True, utc_host) is TWSession.AFTER_HOURS_ODD
