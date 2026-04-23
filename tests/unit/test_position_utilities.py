"""Unit tests for Position utility behaviors."""

from __future__ import annotations

import datetime
import sys
import types
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from finlab.online.enums import OrderCondition
from finlab.online.order_executor import Position


def test_position_json_roundtrip(tmp_path: Path) -> None:
    pos = Position({"2330": 1})
    json_path = tmp_path / "position.json"

    pos.to_json(str(json_path))
    pos2 = Position.from_json(str(json_path))

    assert pos.position[0] == pos2.position[0]


def test_position_arithmetic_and_conditions() -> None:
    pos = Position({"2330": 1}) + Position({"2330": 1, "1101": 1})
    for order in pos.position:
        if order["stock_id"] == "2330":
            assert order["quantity"] == 2
        if order["stock_id"] == "1101":
            assert order["quantity"] == 1

    pos = Position.from_list(pos.to_list())
    for order in pos.position:
        if order["stock_id"] == "2330":
            assert order["quantity"] == 2
        if order["stock_id"] == "1101":
            assert order["quantity"] == 1

    pos = Position({"2330": Decimal("1.1")})
    pos = Position.from_list(pos.to_list())
    assert pos.position[0]["quantity"] == Decimal("1.1")

    pos = Position({"2330": 2}) - Position({"2330": 1, "1101": 1})
    for order in pos.position:
        if order["stock_id"] == "2330":
            assert order["quantity"] == 1
        if order["stock_id"] == "1101":
            assert order["quantity"] == -1

    pos = Position({"2330": 2}, day_trading_long=True)
    pos.fall_back_cash()
    assert pos.position[0]["stock_id"] == "2330"
    assert pos.position[0]["quantity"] == 2
    assert pos.position[0]["order_condition"] == OrderCondition.CASH

    pos = Position({"2330": 2}, margin_trading=True)
    assert pos.position[0]["order_condition"] == OrderCondition.MARGIN_TRADING

    pos = Position({"2330": -2}, margin_trading=True)
    assert pos.position[0]["order_condition"] == OrderCondition.CASH

    pos = Position({"2330": -2}, short_selling=True)
    assert pos.position[0]["order_condition"] == OrderCondition.SHORT_SELLING

    pos = Position({"2330": 2}, short_selling=True)
    assert pos.position[0]["order_condition"] == OrderCondition.CASH

    pos = Position.from_list(
        [{"stock_id": "2330", "quantity": 2, "order_condition": OrderCondition.CASH}]
    )
    pos2 = Position.from_dict(
        [{"stock_id": "2330", "quantity": 2, "order_condition": OrderCondition.CASH}]
    )
    assert pos.position[0] == pos2.position[0]


def test_position_from_weight() -> None:
    position = Position.from_weight(
        {"1101": 0.5, "2330": 0.5},
        fund=1_000_000,
        price={"1101": 50, "2330": 100},
    )
    expected = Position.from_list(
        [
            {
                "stock_id": "1101",
                "quantity": 10,
                "order_condition": OrderCondition.CASH,
            },
            {"stock_id": "2330", "quantity": 5, "order_condition": OrderCondition.CASH},
        ]
    )
    assert len((position - expected).position) == 0

    position = Position.from_weight(
        {"1101": 0.5, "2330": 0.5},
        fund=1_000_000,
        price={"1101": 30, "2330": 60},
        odd_lot=True,
        board_lot_size=100,
    )
    expected = Position.from_list(
        [
            {
                "stock_id": "1101",
                "quantity": Decimal("166.66"),
                "order_condition": OrderCondition.CASH,
            },
            {
                "stock_id": "2330",
                "quantity": Decimal("83.33"),
                "order_condition": OrderCondition.CASH,
            },
        ]
    )
    assert len((position - expected).position) == 0

    position = Position.from_weight(
        {"1101": -0.5, "2330": 0.5},
        fund=1_000_000,
        price={"1101": 30, "2330": 60},
        odd_lot=True,
        board_lot_size=100,
        short_selling=True,
    )
    expected = Position.from_list(
        [
            {
                "stock_id": "1101",
                "quantity": Decimal("-166.66"),
                "order_condition": OrderCondition.SHORT_SELLING,
            },
            {
                "stock_id": "2330",
                "quantity": Decimal("83.33"),
                "order_condition": OrderCondition.CASH,
            },
        ]
    )
    assert len((position - expected).position) == 0

    try:
        Position.from_weight(
            {"1101": 0.5, "2330": 0.5},
            fund=1_000_000,
            price={"1101": 30, "2330": 60},
            odd_lot=True,
            board_lot_size=30,
            margin_trading=True,
        )
        raise AssertionError
    except Exception:
        assert True


class _ReportMarket:
    def market_close_at_timestamp(self, timestamp):
        if isinstance(timestamp, pd.Timestamp):
            timestamp = timestamp.to_pydatetime()
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=datetime.timezone.utc)
        return timestamp.astimezone(datetime.timezone.utc)

    def get_board_lot_size(self):
        return 1000


def test_position_from_report_does_not_use_future_next_weights_after_stop_event() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    weights = pd.Series([1.0], index=["2330"], name=now - datetime.timedelta(days=30))
    next_weights = pd.Series(
        [1.0], index=["1101"], name=now + datetime.timedelta(days=7)
    )
    report = SimpleNamespace(
        weights=weights,
        next_weights=next_weights,
        actions=pd.Series(["sl"], index=["2330"], dtype=object),
        next_trading_date=now - datetime.timedelta(days=1),
        market=_ReportMarket(),
    )

    cloud_report_module = types.ModuleType("finlab.portfolio.cloud_report")
    cloud_report_module.CloudReport = type("CloudReport", (), {})
    portfolio_module = types.ModuleType("finlab.portfolio")
    portfolio_module.cloud_report = cloud_report_module

    with patch.dict(
        sys.modules,
        {
            "finlab.portfolio": portfolio_module,
            "finlab.portfolio.cloud_report": cloud_report_module,
        },
    ):
        position = Position.from_report(
            report,
            fund=1_000_000,
            price={"2330": 100, "1101": 50},
            odd_lot=True,
        )

    assert position.position == []


def test_position_from_report_keeps_current_weights_not_stopped() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    weights = pd.Series(
        [0.25, 0.25, 0.25, 0.25],
        index=["9905 大華", "2897 王道銀行", "2916 滿心", "8433 弘帆"],
        name=now - datetime.timedelta(days=30),
    )
    next_weights = pd.Series(
        [0.25, 0.25, 0.25, 0.25],
        index=["1342", "2248", "2432", "2637"],
        name=now + datetime.timedelta(days=7),
    )
    report = SimpleNamespace(
        weights=weights,
        next_weights=next_weights,
        actions=pd.Series(
            ["sl_", "sl_", "sl"],
            index=["4442 竣邦-KY", "2851 中再保", "2916 滿心"],
            dtype=object,
        ),
        next_trading_date=now - datetime.timedelta(days=1),
        market=_ReportMarket(),
    )

    cloud_report_module = types.ModuleType("finlab.portfolio.cloud_report")
    cloud_report_module.CloudReport = type("CloudReport", (), {})
    portfolio_module = types.ModuleType("finlab.portfolio")
    portfolio_module.cloud_report = cloud_report_module

    with patch.dict(
        sys.modules,
        {
            "finlab.portfolio": portfolio_module,
            "finlab.portfolio.cloud_report": cloud_report_module,
        },
    ):
        position = Position.from_report(
            report,
            fund=1_000_000,
            price={"9905": 21.3, "2897": 10.15, "2916": 46.0, "8433": 57.5},
            odd_lot=True,
        )

    assert {p["stock_id"] for p in position.position} == {"9905", "2897", "8433"}
