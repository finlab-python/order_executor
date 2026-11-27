"""Unit tests for finlab_online.portfolio.validation -- pure functions, no auth/network.

When the compiled ``finlab.core`` Cython modules are missing (source-only CI
checkout without a build step), this module installs lightweight stubs so that
``finlab_online.portfolio.validation`` can be imported without its eager transitive
imports blowing up.  When the real modules are present we leave ``sys.modules``
untouched -- stubbing a real package breaks ``importlib.resources.files`` for
later tests in the same pytest session (collection imports every test module
up-front, so module-level pollution here leaks into every sibling test).
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest


def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []  # type: ignore[attr-defined]
    mod.__getattr__ = lambda attr: type(attr, (), {})
    return mod


def _install_core_stubs_if_missing() -> None:
    """Install stub submodules only when the real finlab.core is unavailable."""
    try:
        importlib.import_module("finlab.core.report")
        # Real compiled modules are importable -- don't touch sys.modules.
        return
    except ImportError:
        pass

    stubs = [
        "finlab.core",
        "finlab.core.firestore_rest",
        "finlab.core.report",
        "finlab.core.backtest_core",
        "finlab.core.mae_mfe",
        "finlab.core.metrics",
        "finlab.core.utils_core",
        "finlab.core.aes",
        "finlab.online",
        "finlab_online.enums",
        "finlab_online.order_executor",
        "finlab_online.core",
        "finlab_online.core.account",
    ]
    for name in stubs:
        sys.modules.setdefault(name, _make_stub(name))


_install_core_stubs_if_missing()

from finlab_online.portfolio.validation import (
    check_position_needs_market_default,
    compute_position_value,
    compute_rebalance_funds,
    merge_margin_cash_adjustments,
    normalize_data_payload,
    normalize_weights,
    replace_inf_nan,
    validate_position_fields,
    validate_weights,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_position_data() -> dict:
    """Return a fully-valid position data dict."""
    return {
        "timestamp": "2026-04-01T09:00:00+00:00",
        "next_trading_time": "2026-04-02T09:00:00+00:00",
        "position": [{"symbol": "2330", "quantity": 1}],
        "allocation": 500_000.0,
        "weight": 0.5,
        "entry_at": "close",
        "exit_at": "close",
        "stop": [],
        "stop_loss": 0.9,
        "take_profit": 1.5,
        "trail_stop": None,
        "market": "tw_stock",
    }


# ===================================================================
# validate_position_fields
# ===================================================================


class TestValidatePositionFields:
    def test_valid_data_returns_no_errors(self):
        errors = validate_position_fields("s1", _valid_position_data())
        assert errors == []

    def test_missing_timestamp_reports_error(self):
        data = _valid_position_data()
        data["timestamp"] = 12345
        errors = validate_position_fields("s1", data)
        assert len(errors) == 1
        assert "timestamp" in errors[0]
        assert "string" in errors[0]

    def test_missing_multiple_string_fields(self):
        data = _valid_position_data()
        data["timestamp"] = None
        data["entry_at"] = 42
        errors = validate_position_fields("s1", data)
        assert len(errors) == 2
        assert any("timestamp" in e for e in errors)
        assert any("entry_at" in e for e in errors)

    def test_position_not_list(self):
        data = _valid_position_data()
        data["position"] = "not_a_list"
        errors = validate_position_fields("s1", data)
        assert any("position must be a list" in e for e in errors)

    def test_allocation_not_numeric(self):
        data = _valid_position_data()
        data["allocation"] = "one million"
        errors = validate_position_fields("s1", data)
        assert any("allocation" in e and "float or int" in e for e in errors)

    def test_weight_not_numeric(self):
        data = _valid_position_data()
        data["weight"] = [0.5]
        errors = validate_position_fields("s1", data)
        assert any("weight" in e and "float or int" in e for e in errors)

    def test_stop_not_list(self):
        data = _valid_position_data()
        data["stop"] = "not_a_list"
        errors = validate_position_fields("s1", data)
        assert any("stop must be a list" in e for e in errors)

    def test_optional_numeric_none_is_valid(self):
        data = _valid_position_data()
        data["stop_loss"] = None
        data["take_profit"] = None
        data["trail_stop"] = None
        errors = validate_position_fields("s1", data)
        assert errors == []

    def test_optional_numeric_bad_type(self):
        data = _valid_position_data()
        data["stop_loss"] = "bad"
        errors = validate_position_fields("s1", data)
        assert any("stop_loss" in e for e in errors)

    def test_market_non_string_non_none(self):
        data = _valid_position_data()
        data["market"] = 42
        errors = validate_position_fields("s1", data)
        assert any("market" in e for e in errors)

    def test_market_none_is_valid(self):
        data = _valid_position_data()
        data["market"] = None
        errors = validate_position_fields("s1", data)
        assert not any("market" in e for e in errors)

    def test_position_name_in_errors(self):
        data = _valid_position_data()
        data["timestamp"] = None
        errors = validate_position_fields("my_strategy", data)
        assert errors[0].startswith("my_strategy:")

    def test_empty_data_reports_all_required_fields(self):
        errors = validate_position_fields("empty", {})
        # Should flag: timestamp, next_trading_time, entry_at, exit_at (4 strings)
        # + position (list) + allocation, weight (2 numerics) + stop (list) = 8
        assert len(errors) == 8


# ===================================================================
# check_position_needs_market_default
# ===================================================================


class TestCheckPositionNeedsMarketDefault:
    def test_none_market_needs_default(self):
        assert check_position_needs_market_default({"market": None}) is True

    def test_string_market_does_not_need_default(self):
        assert check_position_needs_market_default({"market": "tw_stock"}) is False

    def test_missing_market_key(self):
        # data.get("market") returns None, and not isinstance(None, str) is True
        assert check_position_needs_market_default({}) is True

    def test_numeric_market_does_not_need_default(self):
        # not isinstance(42, str) is True, but data.get("market") is not None
        assert check_position_needs_market_default({"market": 42}) is False


# ===================================================================
# replace_inf_nan
# ===================================================================


class TestReplaceInfNan:
    def test_regular_float_unchanged(self):
        assert replace_inf_nan(3.14) == 3.14

    def test_inf_replaced_with_none(self):
        assert replace_inf_nan(float("inf")) is None

    def test_negative_inf_replaced(self):
        assert replace_inf_nan(float("-inf")) is None

    def test_nan_replaced_with_none(self):
        assert replace_inf_nan(float("nan")) is None

    def test_int_unchanged(self):
        assert replace_inf_nan(42) == 42

    def test_string_unchanged(self):
        assert replace_inf_nan("hello") == "hello"

    def test_none_unchanged(self):
        assert replace_inf_nan(None) is None

    def test_nested_dict(self):
        result = replace_inf_nan({"a": float("inf"), "b": 1.0, "c": "x"})
        assert result == {"a": None, "b": 1.0, "c": "x"}

    def test_nested_list(self):
        result = replace_inf_nan([float("nan"), 2.0, 3])
        assert result == [None, 2.0, 3]

    def test_nested_tuple(self):
        result = replace_inf_nan((float("inf"), 1.0))
        assert result == (None, 1.0)

    def test_deeply_nested(self):
        data = {"positions": [{"value": float("inf")}, {"value": 100.0}]}
        result = replace_inf_nan(data)
        assert result == {"positions": [{"value": None}, {"value": 100.0}]}

    def test_empty_structures(self):
        assert replace_inf_nan({}) == {}
        assert replace_inf_nan([]) == []
        assert replace_inf_nan(()) == ()


# ===================================================================
# normalize_data_payload
# ===================================================================


class TestNormalizeDataPayload:
    def test_none_returns_skeleton(self):
        result = normalize_data_payload(None)
        assert result == {"position": {}, "history": {}, "market": None, "config": {}}

    def test_fills_missing_keys(self):
        result = normalize_data_payload({"market": "tw_stock"})
        assert result["position"] == {}
        assert result["history"] == {}
        assert result["config"] == {}
        assert result["market"] == "tw_stock"

    def test_preserves_existing_data(self):
        data = {
            "position": {"s1": {"weight": 0.5}},
            "history": {"s1": []},
            "config": {"params": {}},
        }
        result = normalize_data_payload(data)
        assert result["position"] == {"s1": {"weight": 0.5}}
        assert result["history"] == {"s1": []}
        assert result["config"] == {"params": {}}

    def test_deep_copies_input(self):
        data = {"position": {"s1": {"weight": 0.5}}}
        result = normalize_data_payload(data)
        result["position"]["s1"]["weight"] = 0.9
        assert data["position"]["s1"]["weight"] == 0.5


# ===================================================================
# compute_rebalance_funds
# ===================================================================


class TestComputeRebalanceFunds:
    def test_basic_rebalance(self):
        result = compute_rebalance_funds(
            total_balance=1_000_000,
            asset_value=300_000,
            total_update_weight=0.5,
            rebalance_safety_weight=0.2,
        )
        # liquid = min(700k, 500k) = 500k
        assert result["liquid_value"] == 500_000.0
        # safety = 500k * 0.2 = 100k
        assert result["rebalance_safety_fund"] == 100_000.0
        # cash = 200k, safety < cash so free = 500k
        assert result["free_value"] == 500_000.0

    def test_all_weight_one(self):
        result = compute_rebalance_funds(
            total_balance=1_000_000,
            asset_value=0,
            total_update_weight=1.0,
            rebalance_safety_weight=0.2,
        )
        # liquid_value = min(1_000_000, 1_000_000) = 1_000_000
        assert result["liquid_value"] == 1_000_000.0
        # rebalance_safety_fund = 1_000_000 * 0.2 = 200_000
        assert result["rebalance_safety_fund"] == 200_000.0
        # cash = 1_000_000 - 0 - 1_000_000 = 0
        # free_value = max(1_000_000 - max(0, 200_000 - 0), 0) = 800_000
        assert result["free_value"] == 800_000.0

    def test_zero_balance(self):
        result = compute_rebalance_funds(
            total_balance=0,
            asset_value=0,
            total_update_weight=1.0,
            rebalance_safety_weight=0.2,
        )
        assert result["liquid_value"] == 0.0
        assert result["rebalance_safety_fund"] == 0.0
        assert result["free_value"] == 0.0

    def test_high_asset_value_caps_liquid(self):
        result = compute_rebalance_funds(
            total_balance=1_000_000,
            asset_value=900_000,
            total_update_weight=0.5,
            rebalance_safety_weight=0.2,
        )
        # liquid_value = min(100_000, 500_000) = 100_000
        assert result["liquid_value"] == 100_000.0

    def test_safety_weight_zero(self):
        result = compute_rebalance_funds(
            total_balance=1_000_000,
            asset_value=0,
            total_update_weight=1.0,
            rebalance_safety_weight=0.0,
        )
        assert result["rebalance_safety_fund"] == 0.0
        assert result["free_value"] == 1_000_000.0

    def test_safety_exceeds_cash_reduces_free_value(self):
        # Scenario: safety fund is larger than available cash
        result = compute_rebalance_funds(
            total_balance=1_000_000,
            asset_value=600_000,
            total_update_weight=0.4,
            rebalance_safety_weight=0.5,
        )
        # liquid_value = min(400_000, 400_000) = 400_000
        assert result["liquid_value"] == 400_000.0
        # rebalance_safety_fund = 400_000 * 0.5 = 200_000
        assert result["rebalance_safety_fund"] == 200_000.0
        # cash = 1_000_000 - 600_000 - 400_000 = 0
        # free_value = max(400_000 - max(0, 200_000 - 0), 0) = 200_000
        assert result["free_value"] == 200_000.0


# ===================================================================
# compute_position_value
# ===================================================================


class TestComputePositionValue:
    def test_single_position(self):
        pos = [{"symbol": "2330", "stock_id": "2330", "quantity": 2}]
        prices = {"2330": 600.0}
        result = compute_position_value(pos, lot=1000, prices=prices)
        assert result == 2 * 600.0 * 1000

    def test_multiple_positions(self):
        pos = [
            {"symbol": "2330", "stock_id": "2330", "quantity": 1},
            {"symbol": "2317", "stock_id": "2317", "quantity": 3},
        ]
        prices = {"2330": 600.0, "2317": 100.0}
        result = compute_position_value(pos, lot=1000, prices=prices)
        assert result == 1 * 600.0 * 1000 + 3 * 100.0 * 1000

    def test_empty_position(self):
        result = compute_position_value([], lot=1000, prices={})
        assert result == 0.0

    def test_missing_symbol_raises(self):
        pos = [{"symbol": "9999", "stock_id": "9999", "quantity": 1}]
        with pytest.raises(ValueError, match="stock 9999 not found"):
            compute_position_value(pos, lot=1000, prices={"2330": 600.0})

    def test_lot_one(self):
        pos = [{"symbol": "AAPL", "stock_id": "AAPL", "quantity": 10}]
        prices = {"AAPL": 175.0}
        result = compute_position_value(pos, lot=1, prices=prices)
        assert result == 10 * 175.0

    def test_nan_price_skipped(self):
        pos = [
            {"symbol": "2330", "stock_id": "2330", "quantity": 1},
            {"symbol": "2317", "stock_id": "2317", "quantity": 2},
        ]
        prices = {"2330": float("nan"), "2317": 100.0}
        result = compute_position_value(pos, lot=1000, prices=prices)
        # nan entry skipped, only 2317 counted
        assert result == 2 * 100.0 * 1000

    def test_custom_resolver(self):
        pos = [{"id": "X", "quantity": 5}]
        prices = {"X": 10.0}
        result = compute_position_value(
            pos, lot=1, prices=prices, resolve_symbol=lambda p: p["id"]
        )
        assert result == 50.0

    def test_fallback_to_stock_id(self):
        # symbol key missing, should fall back to stock_id
        pos = [{"stock_id": "2330", "quantity": 3}]
        prices = {"2330": 200.0}
        result = compute_position_value(pos, lot=1, prices=prices)
        assert result == 3 * 200.0


# ===================================================================
# merge_margin_cash_adjustments
# ===================================================================


class TestMergeMarginCashAdjustments:
    def test_no_overlap_kept_as_is(self):
        diff = [
            {"symbol": "A", "stock_id": "A", "order_condition": 1, "quantity": 10},
            {"symbol": "B", "stock_id": "B", "order_condition": 2, "quantity": 5},
        ]
        result = merge_margin_cash_adjustments(diff)
        assert len(result) == 2

    def test_opposing_cash_positive_margin_negative(self):
        diff = [
            {"symbol": "A", "stock_id": "A", "order_condition": 1, "quantity": 10},
            {"symbol": "A", "stock_id": "A", "order_condition": 2, "quantity": -7},
        ]
        result = merge_margin_cash_adjustments(diff)
        by_oc = {r["order_condition"]: r["quantity"] for r in result}
        # reduce by min(10, 7) = 7
        assert by_oc[1] == 3  # 10 - 7
        assert 2 not in by_oc  # -7 + 7 = 0, removed

    def test_opposing_cash_negative_margin_positive(self):
        diff = [
            {"symbol": "A", "stock_id": "A", "order_condition": 1, "quantity": -5},
            {"symbol": "A", "stock_id": "A", "order_condition": 2, "quantity": 8},
        ]
        result = merge_margin_cash_adjustments(diff)
        by_oc = {r["order_condition"]: r["quantity"] for r in result}
        # reduce by min(5, 8) = 5
        assert by_oc[2] == 3  # 8 - 5
        assert 1 not in by_oc  # -5 + 5 = 0, removed

    def test_same_direction_no_cancellation(self):
        diff = [
            {"symbol": "A", "stock_id": "A", "order_condition": 1, "quantity": 5},
            {"symbol": "A", "stock_id": "A", "order_condition": 2, "quantity": 3},
        ]
        result = merge_margin_cash_adjustments(diff)
        assert len(result) == 2
        by_oc = {r["order_condition"]: r["quantity"] for r in result}
        assert by_oc[1] == 5
        assert by_oc[2] == 3

    def test_empty_input(self):
        assert merge_margin_cash_adjustments([]) == []

    def test_does_not_mutate_input(self):
        diff = [
            {"symbol": "A", "stock_id": "A", "order_condition": 1, "quantity": 10},
            {"symbol": "A", "stock_id": "A", "order_condition": 2, "quantity": -10},
        ]
        original_q = [d["quantity"] for d in diff]
        merge_margin_cash_adjustments(diff)
        assert [d["quantity"] for d in diff] == original_q

    def test_exact_cancellation(self):
        diff = [
            {"symbol": "A", "stock_id": "A", "order_condition": 1, "quantity": 5},
            {"symbol": "A", "stock_id": "A", "order_condition": 2, "quantity": -5},
        ]
        result = merge_margin_cash_adjustments(diff)
        assert result == []


# ===================================================================
# validate_weights
# ===================================================================


class TestValidateWeights:
    def test_valid_weights(self):
        errors = validate_weights({"A": 0.4, "B": 0.6})
        assert errors == []

    def test_negative_weight(self):
        errors = validate_weights({"A": -0.1, "B": 0.5})
        assert len(errors) == 1
        assert "negative" in errors[0]
        assert "A" in errors[0]

    def test_multiple_negative(self):
        errors = validate_weights({"A": -0.1, "B": -0.2})
        assert len(errors) == 2

    def test_total_exceeds_one(self):
        errors = validate_weights({"A": 0.6, "B": 0.6})
        assert any("exceeds 1.0" in e for e in errors)

    def test_exactly_one_is_valid(self):
        errors = validate_weights({"A": 0.5, "B": 0.5})
        assert errors == []

    def test_empty_dict(self):
        errors = validate_weights({})
        assert errors == []

    def test_single_position_full_weight(self):
        errors = validate_weights({"A": 1.0})
        assert errors == []

    def test_small_overshoot_within_tolerance(self):
        # 1.0 + 1e-10 should be within tolerance
        errors = validate_weights({"A": 1.0 + 1e-10})
        assert not any("exceeds" in e for e in errors)


# ===================================================================
# normalize_weights
# ===================================================================


class TestNormalizeWeights:
    def test_already_normalized(self):
        result = normalize_weights({"A": 0.5, "B": 0.5})
        assert result == pytest.approx({"A": 0.5, "B": 0.5})

    def test_unnormalized(self):
        result = normalize_weights({"A": 2.0, "B": 3.0})
        assert result == pytest.approx({"A": 0.4, "B": 0.6})

    def test_single_entry(self):
        result = normalize_weights({"A": 7.0})
        assert result == pytest.approx({"A": 1.0})

    def test_empty_returns_empty(self):
        result = normalize_weights({})
        assert result == {}

    def test_all_zeros_returns_zeros(self):
        result = normalize_weights({"A": 0.0, "B": 0.0})
        assert result == {"A": 0.0, "B": 0.0}

    def test_does_not_mutate_input(self):
        original = {"A": 2.0, "B": 8.0}
        normalize_weights(original)
        assert original == {"A": 2.0, "B": 8.0}
