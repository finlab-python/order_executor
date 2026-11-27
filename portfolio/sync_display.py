"""Display / reporting helpers for PortfolioSyncManager.

Extracted from portfolio_sync_manager.py to consolidate the duplicated
DataFrame-building logic that was shared between ``get_total_position``
and ``__repr__``.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Final, cast

import pandas as pd
from finlab.compat import resolve_position_entry_symbol

from ..core.enums import OrderCondition
from .sync_market_data import DEFAULT_LOT, get_position_lots

if TYPE_CHECKING:
    from finlab.schemas import PortfolioConfigDataDict, StrategyPositionDataDict

    from ..core.position import Position

_ODD_LOT_TOLERANCE: Final[float] = 1e-5


def _build_strategy_map(
    position_data: dict[str, StrategyPositionDataDict],
    config: PortfolioConfigDataDict,
) -> dict[tuple[str, object], str]:
    """Map ``(symbol, order_condition)`` to a comma-separated strategy string."""
    sources = [(name, info["position"]) for name, info in position_data.items()]
    if "custom_position" in config:
        sources.append(("custom", config["custom_position"]))

    has_strategy: dict[tuple[str, object], str] = {}
    for name, stocks in sources:
        for stock in stocks:
            key = (resolve_position_entry_symbol(stock), stock["order_condition"])
            has_strategy[key] = (
                f"{has_strategy[key]},{name}" if key in has_strategy else name
            )

    return has_strategy


def build_position_dataframe(
    position: Position,
    position_data: dict[str, StrategyPositionDataDict],
    config: PortfolioConfigDataDict,
    ref_price: dict[str, float],
    close_price: dict[str, float],
    volume: dict[str, float],
    total_allocation: float,
) -> pd.DataFrame:
    """Build a position-summary DataFrame used by both display paths.

    Returns an empty ``DataFrame`` when *position* contains no entries.
    """
    if not position.position:
        return pd.DataFrame()

    has_strategy = _build_strategy_map(position_data, config)
    lots = get_position_lots(position_data)

    df = (
        pd.DataFrame(position.position)
        .assign(
            lot=lambda df: df.symbol.map(lambda symbol: lots.get(symbol, DEFAULT_LOT)),
            strategy=lambda df: df.apply(
                lambda r: has_strategy.get(
                    (resolve_position_entry_symbol(r), r.order_condition), ""
                ),
                axis=1,
            ),
            type=lambda df: df.order_condition.map(lambda v: OrderCondition(v).name),
            price=lambda df: df.symbol.map(lambda i: ref_price.get(i, 0)),
            close_price=lambda df: df.symbol.map(lambda i: close_price.get(i, 0)),
            weight=lambda df: df.close_price * df.quantity / total_allocation * df.lot,
            volume=lambda df: df.symbol.map(lambda i: volume.get(i, 0)) / df.lot,
        )[
            [
                "symbol",
                "quantity",
                "price",
                "weight",
                "close_price",
                "volume",
                "strategy",
                "type",
            ]
        ]
        .sort_values("symbol")
        .set_index("symbol")
    )

    has_odd_lot = (
        df["quantity"].round(0) - df["quantity"]
    ).abs().sum() > _ODD_LOT_TOLERANCE
    if has_odd_lot:
        df["quantity"] = df["quantity"].map(lambda x: f"{x:.3f}")

    return df


def build_strategy_info_dataframe(
    position_data: dict[str, StrategyPositionDataDict],
    total_balance: float,
) -> pd.DataFrame:
    """Build strategy-level summary for ``__repr__``."""
    pos = copy.deepcopy(position_data)
    strategy_info: dict[str, dict[str, object]] = {}

    for name, raw_strategy in pos.items():
        strategy = cast("dict[str, object]", raw_strategy)
        strategy.pop("position", None)

        strategy["updated"] = strategy.pop("timestamp", "")
        strategy["rebalance_after"] = strategy.pop("next_trading_time", "")

        strategy["stop_loss"] = (
            strategy["stop_loss"] if strategy.get("stop_loss") != 1 else "None"
        )
        strategy["take_profit"] = (
            strategy["take_profit"]
            if strategy.get("take_profit") != float("inf")
            else "None"
        )
        strategy["trail_stop"] = (
            strategy["trail_stop"]
            if strategy.get("trail_stop") != float("inf")
            else "None"
        )

        strategy["updated"] = pd.to_datetime(strategy["updated"]).strftime(
            "%Y-%m-%d %H:%M"
        )
        strategy["rebalance_after"] = pd.to_datetime(
            strategy["rebalance_after"]
        ).strftime("%Y-%m-%d %H:%M")

        allocation = strategy.get("allocation", 0)
        strategy["allocation"] = (
            int(allocation) if isinstance(allocation, (float, int)) else 0
        )
        strategy_info[name] = strategy

    if not strategy_info:
        return pd.DataFrame()

    df2 = (
        pd.DataFrame(strategy_info)
        .loc[
            [
                "allocation",
                "weight",
                "updated",
                "stop_loss",
                "take_profit",
                "trail_stop",
                "entry_at",
                "exit_at",
            ]
        ]
        .T
    )

    alloc_sum = total_balance
    df2["weight"] = (
        (df2.allocation / alloc_sum).map("{:.2%}".format)
        + "/"
        + df2["weight"].map("{:.2%}".format)
        if alloc_sum != 0
        else "0.00%"
    )

    return df2
