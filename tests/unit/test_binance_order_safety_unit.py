"""幣安：掛單中的幣算持有、改價保留方向、市價單可下（order_executor#37）"""

from __future__ import annotations

import importlib
import sys
import types
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

    def get_exchange_info(self) -> dict[str, Any]:
        return {"symbols": [{"symbol": "BTCUSDT", "filters": FILTERS}]}

    futures_exchange_info = get_exchange_info

    def get_all_tickers(self) -> list[dict[str, str]]:
        return [{"symbol": "BTCUSDT", "price": "60000"}]

    def get_account(self) -> dict[str, Any]:
        return {"balances": self.balances}

    def get_order(self, symbol: str, orderId: str) -> dict[str, str]:
        return self.order

    def cancel_order(self, symbol: str, orderId: str) -> None:
        pass

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
def test_update_order_reprices_remaining_in_same_direction(
    monkeypatch: Any, side: str, quantity: Any, expected: str
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
