"""嘉信：改價時取消失敗不重下、委託只查本帳戶（order_executor#37）；查詢失敗報錯、略過 OCO（#54）"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any

import pytest

ORDER = {
    "status": "WORKING",
    "orderLegCollection": [{"instruction": "BUY", "instrument": {"symbol": "AAPL"}}],
    "quantity": 10.0,
    "filledQuantity": 4.0,
    "orderType": "LIMIT",
    "price": 100.0,
    "enteredTime": "2026-10-21T14:00:00+0000",
}


def _response(status: int, body: Any = None) -> Any:
    return types.SimpleNamespace(
        status_code=status, is_success=200 <= status < 300, text="", json=lambda: body
    )


class _FakeClient:
    def __init__(self, cancel_status: int) -> None:
        self.cancel_status = cancel_status
        self.placed: list[dict[str, Any]] = []
        self.accounts = _response(200, [{"securitiesAccount": {}}])
        self.orders = _response(200, [{**ORDER, "orderId": 1}])
        self.Account = types.SimpleNamespace(
            Fields=types.SimpleNamespace(POSITIONS="positions")
        )

    def get_accounts(self, fields: Any = None) -> Any:
        return self.accounts

    def get_orders_for_account(self, account_hash: str) -> Any:
        return self.orders

    def get_orders_for_all_linked_accounts(self) -> Any:
        return _response(200, [{**ORDER, "orderId": 1}, {**ORDER, "orderId": 2}])

    def cancel_order(self, order_id: int, account_hash: str) -> Any:
        return _response(self.cancel_status)

    def place_order(self, account_hash: str, order: dict[str, Any]) -> Any:
        self.placed.append(order)
        return types.SimpleNamespace(status_code=201, headers={"location": "/orders/9"})


def _account(monkeypatch: Any, cancel_status: int = 200) -> Any:
    auth = types.ModuleType("schwab.auth")
    auth.client_from_token_file = None
    monkeypatch.setitem(sys.modules, "schwab", types.ModuleType("schwab"))
    monkeypatch.setitem(sys.modules, "schwab.auth", auth)
    sys.modules.pop("finlab.online.brokers.schwab", None)
    module = importlib.import_module("finlab.online.brokers.schwab")

    account = module.SchwabAccount.__new__(module.SchwabAccount)
    account.client = _FakeClient(cancel_status)
    account.account_hash = "mine"
    account.trades = {}
    account.get_price_info = lambda ids: {"AAPL": {"漲停價": 150.0, "跌停價": 50.0}}
    return account


def test_update_order_replaces_remaining_after_cancel(monkeypatch: Any) -> None:
    account = _account(monkeypatch)
    account.update_order(1, price=101.0)
    [order] = account.client.placed
    assert order["price"] == "101.00"
    assert order["orderLegCollection"][0]["quantity"] == 6.0


def test_update_order_keeps_original_when_cancel_fails(monkeypatch: Any) -> None:
    account = _account(monkeypatch, cancel_status=400)
    account.update_order(1, price=101.0)
    assert account.client.placed == []


def test_get_orders_only_this_account(monkeypatch: Any) -> None:
    assert list(_account(monkeypatch).get_orders()) == [1]


def test_get_position_without_holdings_is_empty(monkeypatch: Any) -> None:
    assert _account(monkeypatch).get_position().position == []


def test_query_failure_raises_instead_of_empty(monkeypatch: Any) -> None:
    from finlab.online.core.executor import OrderExecutor
    from finlab.online.core.position import Position

    account = _account(monkeypatch)
    account.client.accounts = _response(429)
    account.client.orders = _response(500)
    with pytest.raises(ValueError):
        account.get_position()
    with pytest.raises(ValueError):
        account.get_orders()
    with pytest.raises(ValueError):
        OrderExecutor(Position({"AAPL": 10}), account).create_orders()
    assert account.client.placed == []


def test_get_orders_skips_oco_keeps_others(monkeypatch: Any) -> None:
    account = _account(monkeypatch)
    oco = {"orderId": 7, "status": "WORKING", "orderStrategyType": "OCO",
           "childOrderStrategies": [{**ORDER, "orderId": 8}]}  # fmt: skip
    account.client.orders = _response(200, [{**ORDER, "orderId": 1}, oco])
    assert list(account.get_orders()) == [1]
