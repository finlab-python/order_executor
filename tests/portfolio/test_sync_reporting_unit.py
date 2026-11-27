from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from finlab_online.portfolio.sync_reporting import (
    build_total_position_dataframe,
    format_portfolio_repr,
)

pytestmark = pytest.mark.unit


def _position_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "quantity": [2.0],
            "price": [50.0],
            "weight": [0.1],
            "close_price": [52.0],
            "volume": [10.0],
            "strategy": ["alpha"],
            "type": ["CASH"],
        },
        index=pd.Index(["2330"], name="symbol"),
    )


def test_build_total_position_dataframe_passes_total_allocation_to_display_builder() -> (
    None
):
    data = {
        "position": {
            "alpha": {"allocation": 100.0},
            "beta": {"allocation": 250.0},
        },
        "config": {"excluded_stock_ids": ["1101"]},
    }

    with patch(
        "finlab_online.portfolio.sync_reporting.build_position_dataframe",
        return_value=pd.DataFrame(),
    ) as mock_build:
        build_total_position_dataframe(
            data,
            position=SimpleNamespace(),
            ref_price={"2330": 50.0},
            close_price={"2330": 52.0},
            volume={"2330": 1000.0},
        )

    assert mock_build.call_args.kwargs["position_data"] == data["position"]
    assert mock_build.call_args.kwargs["config"] == data["config"]
    assert mock_build.call_args.kwargs["total_allocation"] == 350.0


def test_format_portfolio_repr_includes_estimated_value_and_strategy_block() -> None:
    data = {
        "position": {"alpha": {"allocation": 100.0}},
        "config": {"params": {"total_balance": 1000}},
    }
    strategy_df = pd.DataFrame({"weight": ["10.00%/10.00%"]}, index=["alpha"])

    with (
        patch(
            "finlab_online.portfolio.sync_reporting.build_total_position_dataframe",
            return_value=_position_frame(),
        ),
        patch(
            "finlab_online.portfolio.sync_reporting.build_strategy_info_dataframe",
            return_value=strategy_df,
        ) as mock_strategy_df,
    ):
        result = format_portfolio_repr(
            data,
            position=SimpleNamespace(),
            ref_price={"2330": 50.0},
            close_price={"2330": 52.0},
            volume={"2330": 1000.0},
        )

    assert result.startswith("Estimate value 100000")
    assert "strategy" in result
    assert "alpha" in result
    mock_strategy_df.assert_called_once_with(data["position"], 1000)


def test_format_portfolio_repr_handles_empty_position_frame() -> None:
    empty_df = pd.DataFrame()
    strategy_df = pd.DataFrame({"weight": []})

    with (
        patch(
            "finlab_online.portfolio.sync_reporting.build_total_position_dataframe",
            return_value=empty_df,
        ),
        patch(
            "finlab_online.portfolio.sync_reporting.build_strategy_info_dataframe",
            return_value=strategy_df,
        ),
    ):
        result = format_portfolio_repr(
            {"position": {}, "config": {}},
            position=SimpleNamespace(),
            ref_price={},
            close_price={},
            volume={},
        )

    assert result.startswith("Position")
    assert "strategy" in result


def test_format_portfolio_repr_resets_pandas_display_options() -> None:
    original_rows = pd.get_option("display.max_rows")
    original_float = pd.get_option("display.float_format")

    with (
        patch(
            "finlab_online.portfolio.sync_reporting.build_total_position_dataframe",
            return_value=pd.DataFrame(),
        ),
        patch(
            "finlab_online.portfolio.sync_reporting.build_strategy_info_dataframe",
            return_value=pd.DataFrame(),
        ),
    ):
        format_portfolio_repr(
            {"position": {}, "config": {}},
            position=SimpleNamespace(),
            ref_price={},
            close_price={},
            volume={},
        )

    assert pd.get_option("display.max_rows") == original_rows
    assert pd.get_option("display.float_format") == original_float
