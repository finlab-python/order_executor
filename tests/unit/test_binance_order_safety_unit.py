"""幣安：掛單中的幣算持有、改價保留方向、市價單可下（order_executor#37）；
只改量保留限價、不支援 best_price_limit、委託轉成 FinLab 型別（order_executor#55）"""

from __future__ import annotations

import importlib
import sys
import types
from decimal import Decimal
from typing import Any

import pytest

from finlab.online.core.enums import Action

FILTERS = [
    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
    {"filterType": "LOT_SIZE", "stepSize": "0.0001", "minQty": "0.0001"},
    {"filterType": "NOTIONAL", "minNotional": "5"},
]


class _FakeClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.balances: list[dict[str, str]] = []
        self.order: dict[str, str] = {}
        self.open_orders: list[dict[str, Any]] = []
        self.canceled: list[str] = []

    def get_exchange_info(self) -> dict[str, Any]:
        return {"symbols": [{"symbol": "BTCUSDT", "filters": FILTERS}]}

    futures_exchange_info = get_exchange_info

    def get_all_tickers(self) -> list[dict[str, str]]:
        return [{"symbol": "BTCUSDT", "price": "60000"}]

    def get_account(self) -> dict[str, Any]:
        return {"balances": self.balances}

    def get_order(self, symbol: str, orderId: str) -> dict[str, str]:
        return self.order

    def get_open_orders(self) -> list[dict[str, Any]]:
        return self.open_orders

    def get_ticker(self, symbols: str) -> list[dict[str, str]]:
        price = {"lastPrice": "60500", "bidPrice": "60499", "askPrice": "60501"}
        return [{"symbol": "BTCUSDT", "openPrice": "60000", "highPrice": "61000",
                 "lowPrice": "59000", "bidQty": "1", "askQty": "1", **price}]

    def cancel_order(self, symbol: str, orderId: str) -> None:
        self.canceled.append(orderId)

    def create_order(self, **params: Any) -> dict[str, Any]:
        self.created.append(params)
        return {"orderId": 9}


def _account(monkeypatch: Any) -> Any:
    enums = types.ModuleType("binance.enums")
    enums.__dict__.update(
        ORDER_TYPE_LIMIT="LIMIT",
        ORDER_TYPE_MARKET="MARKET",
        SIDE_BUY="BUY",
        SIDE_SELL="SELL",
    )
    cachetools = types.ModuleType("cachetools")
    cachetools.func = types.ModuleType("cachetools.func")
    cachetools.func.ttl_cache = lambda ttl: lambda f: f
    binance = types.ModuleType("binance")
    binance.client = types.ModuleType("binance.client")
    for name, module in [
        ("binance", binance),
        ("binance.client", binance.client),
        ("binance.enums", enums),
        ("cachetools", cachetools),
        ("cachetools.func", cachetools.func),
    ]:
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules.pop("finlab.online.brokers.binance", None)
    module = importlib.import_module("finlab.online.brokers.binance")

    account = module.BinanceAccount.__new__(module.BinanceAccount)
    account.simple_client = module.BinanceSimpleClient(_FakeClient())
    account.base_currency = "USDT"
    return account


def test_locked_coins_count_as_position(monkeypatch: Any) -> None:
    account = _account(monkeypatch)
    account.simple_client.client.balances = [
        {"asset": "BTC", "free": "0", "locked": "0.5"},
        {"asset": "USDT", "free": "100", "locked": "0"},
        {"asset": "ETH", "free": "0", "locked": "0"},
    ]
    position = account.get_position().position
    assert [(p["stock_id"], p["quantity"]) for p in position] == [
        ("BTC", 0.5),
        ("USDT", 100),
    ]


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("quantity, expected", [(None, "0.6"), (0.1, "0.1")])
def test_update_order_reprices_in_same_direction(
    monkeypatch: Any, side: str, quantity: float | None, expected: str
) -> None:
    account = _account(monkeypatch)
    client = account.simple_client.client
    client.order = {"side": side, "origQty": "1.00000000", "executedQty": "0.40000000"}
    account.update_order("BTCUSDT|7", price=61000.0, quantity=quantity)
    [order] = client.created
    assert (order["side"], order["quantity"], order["price"]) == (
        side,
        expected,
        "61000.00000000",
    )


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"market_order": True}, {"type": "MARKET"}),
        (
            {"price": 60000},
            {"type": "LIMIT", "price": "60000.00000000", "timeInForce": "GTC"},
        ),
    ],
)
def test_create_order(monkeypatch: Any, kwargs: Any, expected: Any) -> None:
    account = _account(monkeypatch)
    account.create_order(Action.BUY, "BTC", 0.01, **kwargs)
    assert account.simple_client.client.created == [
        {"side": "BUY", "symbol": "BTCUSDT", "quantity": "0.01", **expected}
    ]


def test_update_order_quantity_only_keeps_limit_price(monkeypatch: Any) -> None:
    account = _account(monkeypatch)
    client = account.simple_client.client
    client.order = {"side": "BUY", "price": "50000.00000000",
                    "origQty": "1.00000000", "executedQty": "0.40000000"}
    account.update_order("BTCUSDT|7", quantity=0.2)
    [order] = client.created
    assert (order["type"], order["quantity"], order["price"]) == (
        "LIMIT", "0.2", "50000.00000000")


def test_best_price_limit_is_rejected(monkeypatch: Any) -> None:
    account = _account(monkeypatch)
    with pytest.raises(ValueError, match="best_price_limit"):
        account.create_order(Action.BUY, "BTC", 0.01, price=60000, best_price_limit=True)
    assert account.simple_client.client.created == []


def test_get_orders_use_finlab_types(monkeypatch: Any) -> None:
    from finlab.online.core.executor import OrderExecutor
    from finlab.online.core.position import Position

    account = _account(monkeypatch)
    client = account.simple_client.client
    client.open_orders = [
        {"symbol": "BTCUSDT", "orderId": oid, "side": side, "price": "59000.00000000",
         "origQty": "0.10000000", "executedQty": "0.00000000", "status": "NEW", "time": 0}
        for oid, side in [("1", "BUY"), ("2", "SELL")]
    ]
    order = account.get_orders()["BTCUSDT|2"]
    assert (order.action, order.stock_id, order.quantity) == (Action.SELL, "BTC", Decimal("0.1"))

    executor = OrderExecutor(Position({}), account)
    executor.cancel_orders(buy_only=True)
    assert client.canceled == ["1"]

    client.order = client.open_orders[0]
    executor.update_order_price(buy_only=True)
    assert [(o["side"], o["price"]) for o in client.created] == [("BUY", "60500.00000000")]
