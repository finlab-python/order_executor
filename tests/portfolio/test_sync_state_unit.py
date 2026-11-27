from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from finlab_online.enums import OrderCondition
from finlab_online.portfolio.sync_state import (
    clear_state,
    get_last_market_timestamp,
    get_position,
    get_strategy_position,
)

pytestmark = pytest.mark.unit


def _position(symbol: str, quantity: float = 1.0, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": symbol,
        "quantity": quantity,
        "order_condition": OrderCondition.CASH,
    }
    payload.update(extra)
    return payload


def _strategy_state(
    *,
    symbol: str = "2330",
    market: str = "tw_stock",
    weight: float = 1.0,
    entry_at: str = "close",
    exit_at: str = "close",
    last_market_timestamp: str = "2026-01-02T13:30:00+00:00",
) -> dict[str, object]:
    return {
        "timestamp": "2026-01-02T09:00:00+00:00",
        "next_trading_time": "2026-01-03T09:00:00+00:00",
        "position": [_position(symbol)],
        "allocation": 100000.0,
        "weight": weight,
        "entry_at": entry_at,
        "exit_at": exit_at,
        "stop": [],
        "stop_loss": None,
        "take_profit": None,
        "trail_stop": None,
        "market": market,
        "last_market_timestamp": last_market_timestamp,
    }


def _market_stub(
    close_timestamp: str = "2026-01-02T13:30:00+00:00",
) -> SimpleNamespace:
    close_frame = pd.DataFrame(
        {"2330": [100.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-02")]),
    )
    return SimpleNamespace(
        market_close_at_timestamp=lambda _dt: pd.Timestamp(close_timestamp),
        get_price=lambda _field: close_frame,
    )


def test_clear_state_returns_normalized_skeleton() -> None:
    assert clear_state() == {
        "position": {},
        "history": {},
        "market": None,
        "config": {},
    }


def test_get_last_market_timestamp_returns_latest_seen_value() -> None:
    data = {
        "position": {
            "s1": {"last_market_timestamp": "2026-01-02T13:30:00+00:00"},
            "s2": {"last_market_timestamp": "2026-01-03T13:30:00+00:00"},
            "s3": {},
        }
    }
    assert get_last_market_timestamp(data) == "2026-01-03T13:30:00+00:00"


def test_get_strategy_position_uses_previous_history_when_open_before_refresh() -> None:
    data = {
        "position": {"alpha": _strategy_state(symbol="2330")},
        "history": {
            "alpha": [
                {"position": [_position("1101")]},
                {
                    "last_market_timestamp": "2026-01-02T13:30:00+00:00",
                    "position": [_position("2454")],
                },
            ]
        },
        "config": {},
    }

    with patch(
        "finlab_online.portfolio.sync_state.get_market_by_name",
        return_value=_market_stub(),
    ):
        result = get_strategy_position(data, "alpha", "open")

    assert result == [_position("1101")]


def test_get_position_merges_custom_and_excludes_symbols() -> None:
    data = {
        "position": {
            "alpha": _strategy_state(symbol="2330", weight=0.6),
            "beta": _strategy_state(symbol="1101", weight=0.4, market="us_stock"),
        },
        "history": {},
        "config": {
            "custom_position": [_position("0050", quantity=2.0)],
            "excluded_stock_ids": ["1101"],
        },
    }

    with patch(
        "finlab_online.portfolio.sync_state.get_market_by_name",
        return_value=_market_stub(),
    ):
        result = get_position(data)

    entries = {entry["symbol"]: entry for entry in result.to_list()}

    assert set(entries) == {"2330", "0050"}
    assert entries["2330"]["quantity"] == pytest.approx(1.0)
    assert entries["0050"]["quantity"] == pytest.approx(2.0)
