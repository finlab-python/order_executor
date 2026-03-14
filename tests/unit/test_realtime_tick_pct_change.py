from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from finlab.online.core.realtime_models import Tick
from finlab.online.core.realtime_normalizers import (
    calculate_tick_pct_change,
    get_first_valid_float,
)


def test_tick_pct_change_prefers_broker_native_value() -> None:
    tick = Tick(
        stock_id="2330",
        price=110.0,
        volume=100,
        total_volume=1000,
        time=datetime.datetime(2026, 3, 5, 9, 1, 0),
        open=100.0,
        prev_close=105.0,
        pct_change=7.25,
    )

    assert tick.pct_change == pytest.approx(7.25)


def test_tick_pct_change_computed_from_prev_close() -> None:
    tick = Tick(
        stock_id="2330",
        price=110.0,
        volume=100,
        total_volume=1000,
        time=datetime.datetime(2026, 3, 5, 9, 1, 0),
        prev_close=105.0,
    )

    assert tick.pct_change == pytest.approx((110.0 / 105.0 - 1.0) * 100.0)


def test_tick_pct_change_none_without_prev_close_even_if_open_exists() -> None:
    tick = Tick(
        stock_id="2330",
        price=110.0,
        volume=100,
        total_volume=1000,
        time=datetime.datetime(2026, 3, 5, 9, 1, 0),
        open=100.0,
    )

    assert tick.pct_change is None


def test_tick_pct_change_none_when_prev_close_zero() -> None:
    tick = Tick(
        stock_id="2330",
        price=110.0,
        volume=100,
        total_volume=1000,
        time=datetime.datetime(2026, 3, 5, 9, 1, 0),
        prev_close=0,
    )

    assert tick.pct_change is None


def test_calculate_tick_pct_change_only_uses_prev_close() -> None:
    assert calculate_tick_pct_change(110.0, prev_close=100.0) == pytest.approx(10.0)
    assert calculate_tick_pct_change(110.0, prev_close=None) is None


def test_get_first_valid_float_for_object_and_dict() -> None:
    obj = SimpleNamespace(pct_chg="1.23")
    payload = {"changePercent": "2.5"}

    assert get_first_valid_float(obj, "pct_chg", "pct_change") == pytest.approx(1.23)
    assert get_first_valid_float(
        payload, "pct_change", "changePercent"
    ) == pytest.approx(2.5)


def test_tick_old_fields_unchanged() -> None:
    t = datetime.datetime(2026, 3, 5, 9, 5, 0)
    tick = Tick(
        stock_id="2317",
        price=199.5,
        volume=320,
        total_volume=10240,
        time=t,
        open=198.0,
        high=200.0,
        low=197.5,
        avg_price=199.2,
        tick_type=1,
    )

    assert tick.stock_id == "2317"
    assert tick.price == pytest.approx(199.5)
    assert tick.open == pytest.approx(198.0)
    assert tick.high == pytest.approx(200.0)
    assert tick.low == pytest.approx(197.5)
    assert tick.avg_price == pytest.approx(199.2)
    assert tick.tick_type == 1
    assert tick.time == t
