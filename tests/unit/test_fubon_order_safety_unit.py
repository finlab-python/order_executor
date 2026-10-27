"""富邦：查詢失敗不當成空的、未成交時的價格、盤後時段與定盤價格別（order_executor#34、#51）"""

from __future__ import annotations

import datetime
import types
from typing import Any

import pytest

from finlab.online.core.enums import Action, OrderCondition

from ..fixtures.fubon_mocks import import_fubon_module_with_fake_sdk

OK = types.SimpleNamespace(is_success=True, message="", data=[])
RATE_LIMITED = types.SimpleNamespace(is_success=False, message="rate limit", data=None)


def _load(monkeypatch: Any) -> tuple[types.ModuleType, Any]:
    module = import_fubon_module_with_fake_sdk(monkeypatch)
    account = module.FubonAccount.__new__(module.FubonAccount)
    account.target_account = "acc"
    account.quotes = {}
    intraday = types.SimpleNamespace(quote=lambda symbol: account.quotes[symbol])
    account.sdk = types.SimpleNamespace(
        stock=types.SimpleNamespace(get_order_results=lambda acc: OK),
        accounting=types.SimpleNamespace(unrealized_gains_and_loses=lambda acc: OK),
        marketdata=types.SimpleNamespace(
            rest_client=types.SimpleNamespace(
                stock=types.SimpleNamespace(intraday=intraday)
            )
        ),
    )
    return module, account


def _capture_orders(account: Any) -> list[dict[str, Any]]:
    placed: list[dict[str, Any]] = []
    account.sdk.stock.place_order = lambda acc, order: (
        placed.append(order)
        or types.SimpleNamespace(
            is_success=True, data=types.SimpleNamespace(seq_no="x")
        )
    )
    return placed


def _freeze_utc_host(monkeypatch: Any, module: Any, hour: int, minute: int) -> None:
    """模擬主機時區為 UTC，UTC hour:minute:30 的那一刻"""
    instant = datetime.datetime(
        2026, 10, 21, hour, minute, 30, tzinfo=datetime.timezone.utc
    )

    class Clock(datetime.datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime.datetime:  # type: ignore[override]
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    fake = types.SimpleNamespace(datetime=Clock, time=datetime.time)
    monkeypatch.setattr(module, "datetime", fake)


def _timeout(acc: Any) -> Any:
    raise TimeoutError("timeout")


@pytest.mark.parametrize("response", [lambda acc: RATE_LIMITED, _timeout])
def test_query_failure_raises_instead_of_empty(monkeypatch: Any, response: Any) -> None:
    _, account = _load(monkeypatch)
    account.sdk.accounting.unrealized_gains_and_loses = response
    account.sdk.stock.get_order_results = response
    with pytest.raises(Exception):
        account.get_position()
    with pytest.raises(Exception):
        account.get_orders()


def test_successful_queries_unchanged(monkeypatch: Any) -> None:
    _, account = _load(monkeypatch)
    assert account.get_position().position == []
    assert account.get_orders() == {}

    holding = types.SimpleNamespace(
        stock_no="2330", order_type="Stock", today_qty=2000, buy_sell="B"
    )
    account.sdk.accounting.unrealized_gains_and_loses = lambda acc: (
        types.SimpleNamespace(is_success=True, data=[holding])
    )
    assert [
        (p["stock_id"], p["quantity"]) for p in account.get_position().position
    ] == [("2330", 2.0)]


def test_close_falls_back_to_reference_price_before_first_trade(
    monkeypatch: Any,
) -> None:
    _, account = _load(monkeypatch)
    no_trade = {"symbol": "2330", "referencePrice": 580.0, "previousClose": 579.0}
    assert account._create_finlab_stock(no_trade, "2330").close == 580.0
    traded = {**no_trade, "closePrice": 585.0}
    assert account._create_finlab_stock(traded, "2330").close == 585.0


@pytest.mark.parametrize(
    ("utc", "odd_lot", "expected"),
    [
        ((5, 41), True, "Odd"),  # 台北 13:41，UTC 主機原本判成盤中零股
        ((5, 40), True, "Odd"),  # 台北 13:40:30
        ((6, 0), False, "Fixing"),  # 台北 14:00:30
        ((6, 15), False, "Fixing"),
        ((2, 0), True, "IntradayOdd"),  # 台北 10:00
        ((2, 0), False, "Common"),
        ((6, 30), False, "Common"),
    ],
)
def test_market_type_uses_taipei_time(
    monkeypatch: Any, utc: tuple[int, int], odd_lot: bool, expected: str
) -> None:
    module, account = _load(monkeypatch)
    _freeze_utc_host(monkeypatch, module, *utc)
    assert account._determine_market_type(odd_lot) == expected


@pytest.mark.parametrize(
    ("utc", "market", "price_type", "price"),
    [((6, 15), "Fixing", "Reference", None), ((2, 0), "Common", "Limit", "580.0")],
)
def test_fixing_order_uses_reference_price(
    monkeypatch: Any,
    utc: tuple[int, int],
    market: str,
    price_type: str,
    price: str | None,
) -> None:
    module, account = _load(monkeypatch)
    _freeze_utc_host(monkeypatch, module, *utc)
    account.quotes["2330"] = {"symbol": "2330", "closePrice": 580.0}
    placed = _capture_orders(account)

    assert account.create_order(Action.BUY, "2330", 1, price=580.0) == "x"
    assert (placed[0]["market_type"], placed[0]["price_type"], placed[0]["price"]) == (
        market,
        price_type,
        price,
    )


def _ok(data: Any) -> Any:
    return types.SimpleNamespace(is_success=True, message="", data=data)


def _order_result(**kw: Any) -> Any:
    base = {
        "seq_no": "S1",
        "stock_no": "2330",
        "buy_sell": "B",
        "order_type": "Stock",
        "market_type": "Common",
        "price": 1000.0,
        "quantity": 1000,
        "after_qty": 1000,
        "filled_qty": 0,
        "status": 10,
        "date": "2026/10/27",
        "last_time": "09:30:00",
    }
    return types.SimpleNamespace(**{**base, **kw})


@pytest.mark.parametrize("failing", ["get_order_results", "cancel_order", None])
def test_cancel_failure_raises(monkeypatch: Any, failing: str | None) -> None:
    _, account = _load(monkeypatch)
    cancelled = []
    account.sdk.stock.get_order_results = lambda acc: _ok([_order_result()])
    account.sdk.stock.cancel_order = lambda acc, o: cancelled.append(o.seq_no) or OK
    if failing:
        setattr(account.sdk.stock, failing, lambda *args: RATE_LIMITED)
        with pytest.raises(ValueError):
            account.cancel_order("S1")
    else:
        account.cancel_order("S1")
        assert cancelled == ["S1"]


def _balance_account(monkeypatch: Any, order_type: str, summary: dict[str, int]) -> Any:
    _, account = _load(monkeypatch)
    holding = types.SimpleNamespace(
        stock_no="2881", order_type=order_type, buy_sell="B", today_qty=10000
    )
    detail = types.SimpleNamespace(
        settlement_date="2026/10/29", total_settlement_amount=-5000
    )
    account.sdk.accounting = types.SimpleNamespace(
        bank_remain=lambda acc: _ok(types.SimpleNamespace(available_balance=100000)),
        query_settlement=lambda acc, r: _ok(types.SimpleNamespace(details=[detail])),
        unrealized_gains_and_loses=lambda acc: _ok([holding]),
        maintenance=lambda acc: _ok(
            types.SimpleNamespace(
                maintenance_summary=types.SimpleNamespace(
                    **{
                        "margin_loan_amt": 0,
                        "collateral": 0,
                        "shortsell_margin": 0,
                        **summary,
                    }
                )
            )
        ),
    )
    account.quotes["2881"] = {"symbol": "2881", "closePrice": 150.0}
    return account


@pytest.mark.parametrize(
    ("order_type", "summary", "position_value"),
    [
        ("Stock", {}, 1_500_000),
        ("Margin", {"margin_loan_amt": 900_000}, 600_000),  # 融資市值扣融資金額
        (
            "Short",
            {"collateral": 1_000_000, "shortsell_margin": 900_000},
            400_000,
        ),  # 擔保品＋保證金－融券市值
    ],
)
def test_total_balance_nets_margin_and_short(
    monkeypatch: Any, order_type: str, summary: dict[str, int], position_value: int
) -> None:
    account = _balance_account(monkeypatch, order_type, summary)
    assert account.get_total_balance() == position_value + 100_000 - 5_000


@pytest.mark.parametrize(
    "failing",
    [
        "bank_remain",
        "query_settlement",
        "unrealized_gains_and_loses",
        "maintenance",
        "quote",
    ],
)
def test_total_balance_raises_when_any_query_fails(
    monkeypatch: Any, failing: str
) -> None:
    account = _balance_account(monkeypatch, "Margin", {"margin_loan_amt": 900_000})
    if failing == "quote":
        account.quotes.clear()
    else:
        setattr(account.sdk.accounting, failing, lambda *args: RATE_LIMITED)
    with pytest.raises(ValueError):
        account.get_total_balance()


@pytest.mark.parametrize(
    ("action", "odd_lot", "sent"),
    [
        (Action.SELL, False, [("S", "DayTrade")]),  # 現沖先賣
        (Action.BUY, False, [("B", "Stock")]),  # 回補
        (Action.BUY, True, [("B", "Stock")]),
        (Action.SELL, True, []),  # 零股不能現沖先賣
    ],
)
def test_day_trading_short_order_type(
    monkeypatch: Any, action: Action, odd_lot: bool, sent: list[tuple[str, str]]
) -> None:
    module, account = _load(monkeypatch)
    _freeze_utc_host(monkeypatch, module, 2, 0)
    placed = _capture_orders(account)
    account.create_order(
        action,
        "2330",
        1,
        price=1000.0,
        odd_lot=odd_lot,
        order_cond=OrderCondition.DAY_TRADING_SHORT,
    )
    assert [(o["buy_sell"], o["order_type"]) for o in placed] == sent


@pytest.mark.parametrize(
    ("action", "kwargs", "sent"),
    [
        (Action.BUY, {"price": 1005.0}, True),
        (Action.SELL, {"price": 995.0}, True),
        (Action.BUY, {"price": 900.0, "market_order": True}, True),
        (Action.BUY, {"price": 900.0}, False),
        (Action.SELL, {"price": 1100.0}, False),
        (Action.BUY, {"price": 1000.0, "best_price_limit": True}, False),
    ],
)
def test_fixing_skips_orders_not_meant_to_fill_at_close(
    monkeypatch: Any, action: Action, kwargs: dict[str, Any], sent: bool
) -> None:
    module, account = _load(monkeypatch)
    _freeze_utc_host(monkeypatch, module, 6, 15)  # 台北 14:15
    account.quotes["2330"] = {"symbol": "2330", "closePrice": 1000.0}
    placed = _capture_orders(account)
    account.create_order(action, "2330", 1, **kwargs)
    assert [o["price_type"] for o in placed] == (["Reference"] if sent else [])


@pytest.mark.parametrize("reorder_ok", [True, False])
def test_odd_lot_reprice_uses_remaining_quantity(
    monkeypatch: Any, reorder_ok: bool
) -> None:
    module, account = _load(monkeypatch)
    _freeze_utc_host(monkeypatch, module, 2, 0)
    # 原委託 500 股，減量到 300 股，成交 100 股
    order = _order_result(
        market_type="IntradayOdd", quantity=500, after_qty=300, filled_qty=100
    )
    account.sdk.stock.get_order_results = lambda acc: _ok([order])
    account.sdk.stock.make_modify_quantity_obj = lambda o, q: q
    account.sdk.stock.modify_quantity = lambda acc, obj: OK
    placed = _capture_orders(account)
    if reorder_ok:
        account.update_order("S1", price=1005.0)
        assert [(o["quantity"], o["price"]) for o in placed] == [(200, "1005.0")]
    else:
        account.sdk.stock.place_order = lambda acc, order: RATE_LIMITED
        with pytest.raises(ValueError):
            account.update_order("S1", price=1005.0)


@pytest.mark.parametrize(
    ("wanted", "expected"),
    [("3333333", "3333333"), (None, "2222222"), ("333333", None)],
)
def test_account_selection(
    monkeypatch: Any, wanted: str | None, expected: str | None
) -> None:
    module = import_fubon_module_with_fake_sdk(monkeypatch)
    monkeypatch.delenv("FUBON_ACCOUNT", raising=False)
    accounts = [
        types.SimpleNamespace(account=a, account_type=t)
        for a, t in [("1111111", "futopt"), ("2222222", "stock"), ("3333333", "stock")]
    ]
    sdk = types.SimpleNamespace(
        login=lambda *a: _ok(accounts), init_realtime=lambda: None, logout=lambda: None
    )
    monkeypatch.setattr(module, "FubonSDK", lambda *a: sdk)
    kwargs = {
        "national_id": "A1",
        "account": wanted,
        "account_pass": "x",
        "cert_path": "/x.pfx",
    }
    if expected is None:
        with pytest.raises(ValueError):
            module.FubonAccount(**kwargs)
    else:
        assert module.FubonAccount(**kwargs).target_account.account == expected
