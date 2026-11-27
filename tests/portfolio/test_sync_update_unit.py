from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, patch

import pytest

from finlab_online.order_executor import Position
from finlab_online.portfolio.sync_update import (
    build_config_snapshot,
    extract_saved_update_params,
    normalize_portfolio_input,
    update_portfolio_state,
)

pytestmark = pytest.mark.unit


def test_normalize_portfolio_input_rejects_unknown_types() -> None:
    with pytest.raises(
        ValueError, match="portfolio should be Portfolio or Report object"
    ):
        normalize_portfolio_input(object())


def test_build_config_snapshot_normalizes_custom_position_and_excluded_symbols() -> (
    None
):
    allocation = SimpleNamespace(total_weight=0.7)

    config = build_config_snapshot(
        {"alpha": allocation},
        total_balance=100000,
        rebalance_safety_weight=0.2,
        smooth_transition=False,
        force_override_difference=True,
        custom_position=Position({"0050": 2}),
        excluded_stock_ids=None,
        excluded_symbols=["1101"],
        kwargs={"metrics_only": True},
    )

    assert config["weights"] == {"alpha": 0.7}
    assert config["params"]["kwargs"] == {"metrics_only": True}
    assert config["custom_position"][0]["symbol"] == "0050"
    assert config["excluded_stock_ids"] == ["1101"]


def test_extract_saved_update_params_flattens_nested_kwargs() -> None:
    data = {"config": {"params": {"total_balance": 10, "kwargs": {"slippage": 1}}}}
    assert extract_saved_update_params(data) == {"total_balance": 10, "slippage": 1}


def test_update_portfolio_state_prunes_removed_strategies_before_rebalance() -> None:
    data = {
        "position": {
            "legacy": {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "next_trading_time": "2026-01-02T00:00:00+00:00",
                "position": [],
                "allocation": 1000.0,
                "weight": 1.0,
                "entry_at": "close",
                "exit_at": "close",
                "stop": [],
                "stop_loss": None,
                "take_profit": None,
                "trail_stop": None,
                "market": "tw_stock",
            }
        },
        "history": {},
        "config": {},
    }

    with (
        patch(
            "finlab_online.portfolio.sync_update.normalize_portfolio_input",
            return_value={},
        ),
        patch(
            "finlab_online.portfolio.sync_update.identify_updated_strategies",
            return_value=[],
        ),
        patch(
            "finlab_online.portfolio.sync_update.compute_existing_asset_value",
            return_value=0.0,
        ),
        patch(
            "finlab_online.portfolio.sync_update.compute_rebalance_funds",
            return_value={
                "liquid_value": 0.0,
                "rebalance_safety_fund": 0.0,
                "free_value": 0.0,
            },
        ),
        patch("finlab_online.portfolio.sync_update._rebuild_updated_positions"),
        patch("finlab_online.portfolio.sync_update.apply_stop_triggers"),
    ):
        updated = update_portfolio_state(
            data,
            portfolio=object(),
            start_with_empty=True,
            total_balance=0,
        )

    assert updated["position"] == {}
    assert updated["history"]["legacy"][0]["allocation"] == 1000.0


def test_update_portfolio_state_wires_calls_and_auto_smooth_transition() -> None:
    data = {
        "position": {"alpha": {"weight": 1.0, "position": []}},
        "history": {},
        "config": {},
    }
    allocation = SimpleNamespace(total_weight=0.5)

    with (
        patch(
            "finlab_online.portfolio.sync_update.normalize_portfolio_input",
            return_value={"alpha": allocation},
        ),
        patch(
            "finlab_online.portfolio.sync_update.identify_updated_strategies",
            return_value=["alpha"],
        ) as mock_identify,
        patch(
            "finlab_online.portfolio.sync_update.compute_existing_asset_value",
            return_value=1200.0,
        ) as mock_asset_value,
        patch(
            "finlab_online.portfolio.sync_update.compute_rebalance_funds",
            return_value={
                "liquid_value": 4000.0,
                "rebalance_safety_fund": 500.0,
                "free_value": 3500.0,
            },
        ) as mock_funds,
        patch(
            "finlab_online.portfolio.sync_update._rebuild_updated_positions"
        ) as mock_rebuild,
        patch("finlab_online.portfolio.sync_update.apply_stop_triggers") as mock_stops,
    ):
        update_portfolio_state(
            data,
            portfolio=object(),
            start_with_empty=False,
            total_balance=5000,
            rebalance_safety_weight=0.1,
            force_override_difference=True,
        )

    assert data["config"]["weights"] == {"alpha": 0.5}
    mock_identify.assert_called_once_with(
        portfolio={"alpha": allocation},
        position=data["position"],
        smooth_transition=True,
        force_override_difference=True,
    )
    mock_asset_value.assert_called_once_with(
        data["position"], {"alpha": allocation}, ["alpha"]
    )
    mock_funds.assert_called_once_with(5000, 1200.0, 0.5, 0.1)
    mock_rebuild.assert_called_once_with(
        position=data["position"],
        history=data["history"],
        portfolio={"alpha": allocation},
        updated_strategies=["alpha"],
        free_value=3500.0,
        total_update_weight=0.5,
        now=ANY,
        build_kwargs={},
    )
    mock_stops.assert_called_once_with(
        position=data["position"],
        portfolio={"alpha": allocation},
        old_positions={"alpha": {"weight": 1.0, "position": []}},
        now=ANY,
    )
