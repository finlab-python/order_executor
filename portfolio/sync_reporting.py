"""Reporting helpers for ``PortfolioSyncManager`` display methods."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pandas as pd

from .sync_display import build_position_dataframe, build_strategy_info_dataframe
from .sync_market_data import DEFAULT_LOT, get_position_lots

if TYPE_CHECKING:
    from finlab.schemas import PortfolioConfigDataDict, StrategyPositionDataDict

    from ..core.position import Position
    from .sync_storage import DataPayload

__all__ = [
    "build_total_position_dataframe",
    "format_portfolio_repr",
]


def _total_allocation(data: DataPayload) -> float:
    position = cast("dict[str, StrategyPositionDataDict]", data["position"])
    return sum(v["allocation"] for v in position.values())


def build_total_position_dataframe(
    data: DataPayload,
    position: Position,
    ref_price: dict[str, float],
    close_price: dict[str, float],
    volume: dict[str, float],
) -> pd.DataFrame:
    position_data = cast("dict[str, StrategyPositionDataDict]", data["position"])
    config = cast("PortfolioConfigDataDict", data["config"])
    return build_position_dataframe(
        position=position,
        position_data=position_data,
        config=config,
        ref_price=ref_price,
        close_price=close_price,
        volume=volume,
        total_allocation=_total_allocation(data),
    )


def format_portfolio_repr(
    data: DataPayload,
    position: Position,
    ref_price: dict[str, float],
    close_price: dict[str, float],
    volume: dict[str, float],
) -> str:
    pd.set_option("display.max_rows", None)
    pd.set_option("display.float_format", "{:.2f}".format)

    df = build_total_position_dataframe(data, position, ref_price, close_price, volume)

    if len(df) != 0:
        lots = get_position_lots(data["position"])
        estimated_value = (
            df.price.astype(float)
            * df.quantity.astype(float)
            * df.index.map(lambda symbol: lots.get(symbol, DEFAULT_LOT))
        ).sum()
        result = f"Estimate value {int(estimated_value)}"
    else:
        result = "Position"

    position_data = cast("dict[str, StrategyPositionDataDict]", data["position"])
    config = cast("PortfolioConfigDataDict", data["config"])
    params = config.get("params", {})
    total_balance = params.get("total_balance", 0)
    strategy_df = build_strategy_info_dataframe(
        position_data,
        total_balance if isinstance(total_balance, (float, int)) else 0,
    )

    result = (
        result
        + "\n\n"
        + df.to_string()
        + "\n\n\n"
        + "strategy\n\n"
        + strategy_df.to_string()
    )
    pd.reset_option("display.max_rows")
    pd.reset_option("display.float_format")
    return result
