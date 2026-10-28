from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import Mock

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


def _make_account(
    monkeypatch: pytest.MonkeyPatch, utc_time: tuple | None = None
) -> object:
    monkeypatch.setitem(sys.modules, "pocketx", types.ModuleType("pocketx"))
    sys.modules.pop("finlab.online.brokers.pocket", None)
    pocket_module = importlib.import_module("finlab.online.brokers.pocket")
    if utc_time is not None:
        patch_utc_host_clock(monkeypatch, pocket_module, utc_time)
    account = pocket_module.PocketAccount.__new__(pocket_module.PocketAccount)
    account.api = _FakePocket()
    account.trades = {}
    account.get_price_info = lambda: {
        "2330": {"漲停價": 638.0, "跌停價": 522.0, "收盤價": 580.0}
    }
    return account


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
    account = _make_account(monkeypatch, utc_time)

    account.create_order(Action.BUY, "2330", 1, price=580, odd_lot=odd_lot)

    assert account.api.placed_orders[0].order_lot == order_lot


@pytest.mark.parametrize(
    "utc_time, odd_lot, price_type",
    [
        ((2, 0, 0), False, "MKT"),
        ((2, 0, 0), True, "LMT"),
        ((5, 50, 0), True, "LMT"),
        ((6, 10, 0), False, "LMT"),
    ],
)
def test_pocket_market_order_is_limit_order_outside_common_session(
    monkeypatch: pytest.MonkeyPatch, utc_time: tuple, odd_lot: bool, price_type: str
) -> None:
    account = _make_account(monkeypatch, utc_time)

    account.create_order(
        Action.BUY, "2330", 1, price=580, odd_lot=odd_lot, market_order=True
    )

    [order] = account.api.placed_orders
    assert (order.price_type, order.price) == (price_type, 638.0)


@pytest.mark.parametrize(
    "last_price, short_value", [(500.0, 449_287.5), (600.0, 349_145.0)]
)
def test_pocket_total_balance_values_short_position_at_buyback_cost(
    monkeypatch: pytest.MonkeyPatch, last_price: float, short_value: float
) -> None:
    account = _make_account(monkeypatch)
    long = {"direction": "Buy", "quantity": 1000, "last_price": 100.0,
            "collateral": 0, "short_sale_margin": 0,
            "margin_purchase_amount": 0, "interest": 0}
    # Sold short 1000 shares at 500: 500,000 collateral, 450,000 margin.
    short = {**long, "direction": "Sell", "last_price": last_price,
             "collateral": 500_000, "short_sale_margin": 450_000}
    account.api.list_positions = lambda account: [
        types.SimpleNamespace(**p) for p in (long, short)
    ]
    account.api.account_balance = lambda: types.SimpleNamespace(acc_balance=1_000_000)
    account.api.settlements = lambda account: []

    assert account.get_total_balance() == pytest.approx(
        1_000_000 + 99_557.9275 + short_value
    )


@pytest.mark.parametrize("simu_ca", [None, "test-simulation-ca"])
def test_pocket_public_import_uses_official_sdk(monkeypatch, simu_ca):
    sdk = types.ModuleType("pocketx")
    sdk.Pocket = Mock()
    sdk.Pocket.return_value.login.return_value = []
    monkeypatch.setitem(sys.modules, "pocketx", sdk)
    # The unrelated PyPI package must never be used as the broker SDK.
    monkeypatch.setitem(sys.modules, "pocket", types.ModuleType("pocket"))
    sys.modules.pop("finlab.online.brokers.pocket", None)
    monkeypatch.delenv("POCKET_SIMU_CA", raising=False)
    if simu_ca:
        monkeypatch.setenv("POCKET_SIMU_CA", simu_ca)

    pocket_module = importlib.import_module("finlab.online.brokers.pocket")
    assert pocket_module.pk is sdk

    from finlab.online import PocketAccount

    account = PocketAccount(
        api_key="test-key", secret_key="test-password",
        certificate_path="test.pfx", certificate_password="test-ca-password",
        certificate_person_id="test-person",
    )
    assert account.api is sdk.Pocket.return_value
    expected = {"api_key": "test-key", "password": "test-password"}
    if simu_ca:
        expected["simu_ca"] = simu_ca
        account.api.activate_ca.assert_not_called()
    else:
        account.api.activate_ca.assert_called_once_with(
            ca_path="test.pfx", ca_passwd="test-ca-password", person_id="test-person"
        )
    account.api.login.assert_called_once_with(**expected)
