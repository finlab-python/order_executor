"""Tests for extracted portfolio sync submodules.

Tests the pure-function logic in:
- sync_validation: position_type_check, replace_inf_nan
- sync_decisions: identify_updated_strategies
- sync_stops: apply_stop_triggers
- sync_margin: margin_cash_position_combine
- sync_display: build_position_dataframe, build_strategy_info_dataframe
"""

from __future__ import annotations

import datetime
from copy import deepcopy
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytest

from finlab_online.enums import OrderCondition
from finlab_online.order_executor import Position
from finlab_online.portfolio.sync_decisions import identify_updated_strategies
from finlab_online.portfolio.sync_display import (
    build_position_dataframe,
    build_strategy_info_dataframe,
)
from finlab_online.portfolio.sync_margin import margin_cash_position_combine
from finlab_online.portfolio.sync_stops import apply_stop_triggers
from finlab_online.portfolio.sync_validation import position_type_check, replace_inf_nan

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# sync_validation
# ---------------------------------------------------------------------------


class TestPositionTypeCheck:
    """Tests for position_type_check."""

    @staticmethod
    def _valid_data() -> dict:
        return {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "next_trading_time": "2026-01-02T00:00:00+00:00",
            "position": [{"symbol": "2330", "quantity": 1}],
            "allocation": 1_000_000.0,
            "weight": 1.0,
            "entry_at": "close",
            "exit_at": "close",
            "stop": [],
            "stop_loss": 0.9,
            "take_profit": None,
            "trail_stop": None,
            "market": "tw_stock",
        }

    def test_valid_data_no_warnings(self, caplog):
        data = self._valid_data()
        position_type_check("test_strategy", data)
        assert not caplog.text

    def test_wrong_timestamp_type_warns(self, caplog):
        data = self._valid_data()
        data["timestamp"] = 12345
        position_type_check("test_strategy", data)
        assert "timestamp must be str" in caplog.text

    def test_missing_market_gets_default(self):
        data = self._valid_data()
        data["market"] = None
        position_type_check("test_strategy", data)
        assert data["market"] == "tw_stock"

    def test_optional_fields_none_no_warnings(self, caplog):
        data = self._valid_data()
        data["stop_loss"] = None
        data["take_profit"] = None
        data["trail_stop"] = None
        position_type_check("test_strategy", data)
        assert not caplog.text


class TestReplaceInfNan:
    """Tests for replace_inf_nan."""

    def test_inf_replaced_with_none(self):
        assert replace_inf_nan(float("inf")) is None

    def test_negative_inf_replaced_with_none(self):
        assert replace_inf_nan(float("-inf")) is None

    def test_nan_replaced_with_none(self):
        assert replace_inf_nan(float("nan")) is None

    def test_normal_float_unchanged(self):
        assert replace_inf_nan(3.14) == 3.14

    def test_nested_dict(self):
        data = {"a": float("inf"), "b": 1.0, "c": {"d": float("nan")}}
        result = replace_inf_nan(data)
        assert result == {"a": None, "b": 1.0, "c": {"d": None}}

    def test_nested_list(self):
        data = [1.0, float("inf"), [float("nan"), 2.0]]
        result = replace_inf_nan(data)
        assert result == [1.0, None, [None, 2.0]]

    def test_tuple_preserved_as_tuple(self):
        data = (float("inf"), 1.0)
        result = replace_inf_nan(data)
        assert isinstance(result, tuple)
        assert result == (None, 1.0)

    def test_non_float_unchanged(self):
        assert replace_inf_nan("hello") == "hello"
        assert replace_inf_nan(42) == 42
        assert replace_inf_nan(None) is None


# ---------------------------------------------------------------------------
# sync_decisions
# ---------------------------------------------------------------------------


def _make_allocation(
    *,
    total_weight: float = 1.0,
    is_rebalance_due: bool = False,
    weights_index: list[str] | None = None,
) -> MagicMock:
    """Create a minimal PositionScheduler mock."""
    alloc = MagicMock()
    alloc.total_weight = total_weight
    alloc.is_rebalance_due.return_value = is_rebalance_due
    alloc.market = MagicMock()
    if weights_index is not None:
        alloc.weights = MagicMock()
        alloc.weights.index = MagicMock()
        alloc.weights.index.tolist.return_value = weights_index
    return alloc


class TestIdentifyUpdatedStrategies:
    """Tests for identify_updated_strategies."""

    def test_rebalance_due_triggers_update(self):
        portfolio = {"s1": _make_allocation(is_rebalance_due=True)}
        position = {
            "s1": {"weight": 1.0, "position": []},
        }
        result = identify_updated_strategies(
            portfolio=portfolio,
            position=position,
            smooth_transition=True,
            force_override_difference=False,
        )
        assert result == ["s1"]

    def test_weight_change_without_smooth_triggers_update(self):
        portfolio = {"s1": _make_allocation(total_weight=0.5)}
        position = {
            "s1": {"weight": 1.0, "position": []},
        }
        result = identify_updated_strategies(
            portfolio=portfolio,
            position=position,
            smooth_transition=False,
            force_override_difference=False,
        )
        assert result == ["s1"]

    def test_weight_change_with_smooth_suppresses_update(self):
        portfolio = {"s1": _make_allocation(total_weight=0.5)}
        position = {
            "s1": {"weight": 1.0, "position": []},
        }
        result = identify_updated_strategies(
            portfolio=portfolio,
            position=position,
            smooth_transition=True,
            force_override_difference=False,
        )
        assert result == []

    def test_zero_weight_not_in_position_skipped(self):
        portfolio = {"s1": _make_allocation(total_weight=0)}
        result = identify_updated_strategies(
            portfolio=portfolio,
            position={},
            smooth_transition=False,
            force_override_difference=False,
        )
        assert result == []

    def test_stock_list_drift_with_force_override(self):
        portfolio = {
            "s1": _make_allocation(weights_index=["2330", "2454"]),
        }
        position = {
            "s1": {
                "weight": 1.0,
                "position": [
                    {"symbol": "9999", "stock_id": "9999"},
                ],
            },
        }
        result = identify_updated_strategies(
            portfolio=portfolio,
            position=position,
            smooth_transition=True,
            force_override_difference=True,
        )
        assert "s1" in result

    def test_stock_list_drift_without_force_override_no_update(self):
        portfolio = {
            "s1": _make_allocation(weights_index=["2330"]),
        }
        position = {
            "s1": {
                "weight": 1.0,
                "position": [
                    {"symbol": "9999", "stock_id": "9999"},
                ],
            },
        }
        result = identify_updated_strategies(
            portfolio=portfolio,
            position=position,
            smooth_transition=True,
            force_override_difference=False,
        )
        assert result == []

    def test_new_strategy_not_in_position(self):
        portfolio = {"s1": _make_allocation(is_rebalance_due=True)}
        result = identify_updated_strategies(
            portfolio=portfolio,
            position={},
            smooth_transition=False,
            force_override_difference=False,
        )
        assert result == ["s1"]


# ---------------------------------------------------------------------------
# sync_stops
# ---------------------------------------------------------------------------


def _make_stop_allocation(
    *,
    is_stop_triggered: bool = False,
    actions_data: dict[str, str] | None = None,
    next_trading_date: str = "2026-04-10",
    rebalance_started: bool = False,
) -> MagicMock:
    alloc = MagicMock()
    alloc.is_stop_triggered.return_value = is_stop_triggered
    if actions_data is None:
        actions_data = {}
    alloc.actions = pd.Series(actions_data)
    alloc.market = MagicMock()
    alloc.next_trading_date = next_trading_date
    # Deferred triggers fire until the next rebalance's target takes over.
    alloc.uses_next_weights.return_value = rebalance_started
    return alloc


class TestApplyStopTriggers:
    """Tests for apply_stop_triggers."""

    def test_no_triggers_leaves_position_unchanged(self):
        position = {
            "s1": {
                "position": [{"symbol": "2330", "stock_id": "2330", "quantity": 10}],
                "stop": [],
            }
        }
        original = deepcopy(position)
        apply_stop_triggers(
            position=position,
            portfolio={"s1": _make_stop_allocation()},
            old_positions={},
            now=datetime.datetime.now(tz=datetime.timezone.utc),
        )
        assert position == original

    def test_immediate_stop_zeros_position_and_records_entry(self):
        position = {
            "s1": {
                "position": [{"symbol": "2330", "stock_id": "2330", "quantity": 10}],
                "stop": [],
            }
        }
        alloc = _make_stop_allocation(
            is_stop_triggered=True,
            actions_data={"2330 TW": "sl"},
        )
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        apply_stop_triggers(
            position=position,
            portfolio={"s1": alloc},
            old_positions={
                "s1": {
                    "position": [{"symbol": "2330", "stock_id": "2330", "quantity": 10}]
                }
            },
            now=now,
        )
        # Position should be zeroed
        assert position["s1"]["position"][0]["quantity"] == 0
        # Stop should be recorded
        assert len(position["s1"]["stop"]) == 1
        assert position["s1"]["stop"][0]["reason"] == "sl"

    def test_deferred_stop_fires_before_the_rebalance_starts(self):
        position = {
            "s1": {
                "position": [{"symbol": "2330", "stock_id": "2330", "quantity": 5}],
                "stop": [],
            }
        }
        alloc = _make_stop_allocation(
            actions_data={"2330 TW": "sl_enter"},
        )
        now = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        apply_stop_triggers(
            position=position,
            portfolio={"s1": alloc},
            old_positions={
                "s1": {
                    "position": [{"symbol": "2330", "stock_id": "2330", "quantity": 5}]
                }
            },
            now=now,
        )
        assert position["s1"]["position"][0]["quantity"] == 0
        assert len(position["s1"]["stop"]) == 1

    def test_deferred_stop_skipped_once_the_rebalance_started(self):
        position = {
            "s1": {
                "position": [{"symbol": "2330", "stock_id": "2330", "quantity": 5}],
                "stop": [],
            }
        }
        alloc = _make_stop_allocation(
            actions_data={"2330 TW": "sl_enter"},
            rebalance_started=True,
        )
        now = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        apply_stop_triggers(
            position=position,
            portfolio={"s1": alloc},
            old_positions={
                "s1": {
                    "position": [{"symbol": "2330", "stock_id": "2330", "quantity": 5}]
                }
            },
            now=now,
        )
        # Position should remain unchanged
        assert position["s1"]["position"][0]["quantity"] == 5
        assert len(position["s1"]["stop"]) == 0

    def test_strategy_not_in_position_is_skipped(self):
        position = {}
        apply_stop_triggers(
            position=position,
            portfolio={"s1": _make_stop_allocation(is_stop_triggered=True)},
            old_positions={},
            now=datetime.datetime.now(tz=datetime.timezone.utc),
        )
        assert position == {}


# ---------------------------------------------------------------------------
# sync_margin
# ---------------------------------------------------------------------------


class TestMarginCashPositionCombine:
    """Tests for margin_cash_position_combine."""

    def test_opposing_cash_and_margin_cancel(self):
        account = Position.from_list(
            [
                {
                    "symbol": "2330",
                    "stock_id": "2330",
                    "quantity": Decimal(1),
                    "order_condition": OrderCondition.CASH,
                }
            ]
        )
        ideal = Position.from_list(
            [
                {
                    "symbol": "2330",
                    "stock_id": "2330",
                    "quantity": Decimal(1),
                    "order_condition": OrderCondition.MARGIN_TRADING,
                }
            ]
        )
        merged = margin_cash_position_combine(account, ideal)
        payload = merged.to_list()
        assert len(payload) == 1
        assert payload[0]["order_condition"] == OrderCondition.CASH

    def test_same_direction_no_cancel(self):
        account = Position.from_list([])
        ideal = Position.from_list(
            [
                {
                    "symbol": "2330",
                    "stock_id": "2330",
                    "quantity": Decimal(2),
                    "order_condition": OrderCondition.CASH,
                },
                {
                    "symbol": "2330",
                    "stock_id": "2330",
                    "quantity": Decimal(3),
                    "order_condition": OrderCondition.MARGIN_TRADING,
                },
            ]
        )
        merged = margin_cash_position_combine(account, ideal)
        payload = merged.to_list()
        total_qty = sum(p["quantity"] for p in payload)
        assert total_qty == Decimal(5)

    def test_class_level_static_method_still_works(self):
        """Verify the delegation on PortfolioSyncManager class works."""
        from finlab_online.portfolio import PortfolioSyncManager

        account = Position.from_list([])
        ideal = Position.from_list([])
        result = PortfolioSyncManager.margin_cash_position_combine(account, ideal)
        assert isinstance(result, Position)


# ---------------------------------------------------------------------------
# sync_display
# ---------------------------------------------------------------------------


class TestBuildPositionDataframe:
    """Tests for build_position_dataframe."""

    def test_empty_position_returns_empty_df(self):
        pos = Position({})
        df = build_position_dataframe(
            position=pos,
            position_data={},
            config={},
            ref_price={},
            close_price={},
            volume={},
            total_allocation=1_000_000,
        )
        assert df.empty

    def test_single_position_returns_expected_columns(self):
        pos = Position.from_list(
            [
                {
                    "symbol": "2330",
                    "stock_id": "2330",
                    "quantity": 1,
                    "order_condition": OrderCondition.CASH,
                    "weight": 1.0,
                }
            ]
        )
        position_data = {
            "s1": {
                "position": [
                    {
                        "symbol": "2330",
                        "stock_id": "2330",
                        "quantity": 1,
                        "order_condition": OrderCondition.CASH,
                    }
                ],
                "weight": 1.0,
            }
        }
        df = build_position_dataframe(
            position=pos,
            position_data=position_data,
            config={},
            ref_price={"2330": 600.0},
            close_price={"2330": 600.0},
            volume={"2330": 10000.0},
            total_allocation=1_000_000,
        )
        assert not df.empty
        assert "quantity" in df.columns
        assert "strategy" in df.columns
        assert df.index.name == "symbol"


class TestBuildStrategyInfoDataframe:
    """Tests for build_strategy_info_dataframe."""

    def test_empty_position_returns_empty_df(self):
        df = build_strategy_info_dataframe({}, 1_000_000)
        assert df.empty

    def test_single_strategy_returns_expected_rows(self):
        position_data = {
            "s1": {
                "timestamp": "2026-03-05T09:00:00+00:00",
                "next_trading_time": "2026-03-06T09:00:00+00:00",
                "position": [],
                "allocation": 500_000,
                "weight": 0.5,
                "entry_at": "close",
                "exit_at": "close",
                "stop_loss": 1,
                "take_profit": float("inf"),
                "trail_stop": float("inf"),
                "market": "tw_stock",
            }
        }
        df = build_strategy_info_dataframe(position_data, 1_000_000)
        assert not df.empty
        assert "s1" in df.index
        # stop_loss == 1 should be displayed as "None"
        assert df.loc["s1", "stop_loss"] == "None"
        assert df.loc["s1", "take_profit"] == "None"
        assert df.loc["s1", "trail_stop"] == "None"
