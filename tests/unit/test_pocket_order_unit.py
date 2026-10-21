from __future__ import annotations

import importlib
import sys
import types

import pytest

from finlab.online.core.enums import Action

from ..utils.mock_helpers import patch_utc_host_clock


class _FakePocket:
    def __init__(self) -> None:
        self.Contracts = types.SimpleNamespace(Stocks={"2330": object()})
        self.stock_account = object()
        self.placed_orders: list[types.SimpleNamespace] = []

    def Order(self, **kwargs: object) -> types.SimpleNamespace:
        return types.SimpleNamespace(**kwargs)

    def place_order(self, contract: object, order: object) -> types.SimpleNamespace:
        self.placed_orders.append(order)
        return types.SimpleNamespace(order=types.SimpleNamespace(entid="order-1"))


@pytest.mark.parametrize(
    "utc_time, odd_lot, order_lot",
    [
        ((5, 40, 30), True, "Odd"),
        ((6, 0, 10), False, "Fixing"),
        ((6, 30, 0), True, "IntradayOdd"),
        ((1, 0, 0), False, "Common"),
        ((1, 0, 0), True, "IntradayOdd"),
    ],
)
def test_pocket_create_order_session_starts_at_taipei_minute(
    monkeypatch: pytest.MonkeyPatch, utc_time: tuple, odd_lot: bool, order_lot: str
) -> None:
    monkeypatch.setitem(sys.modules, "pocket", types.ModuleType("pocket"))
    sys.modules.pop("finlab.online.brokers.pocket", None)
    pocket_module = importlib.import_module("finlab.online.brokers.pocket")
    patch_utc_host_clock(monkeypatch, pocket_module, utc_time)
    account = pocket_module.PocketAccount.__new__(pocket_module.PocketAccount)
    account.api = _FakePocket()
    account.trades = {}
    account.get_price_info = lambda: {
        "2330": {"漲停價": 638.0, "跌停價": 522.0, "收盤價": 580.0}
    }

    account.create_order(Action.BUY, "2330", 1, price=580, odd_lot=odd_lot)

    assert account.api.placed_orders[0].order_lot == order_lot
