"""Market-data helpers for ``PortfolioSyncManager`` runtime flows."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pandas as pd
    from finlab.portfolio.portfolio import PositionScheduler
    from finlab.schemas import PositionEntryDict, StrategyPositionDataDict

from finlab.compat import resolve_position_entry_symbol
from finlab.markets import get_market_by_name
from finlab.markets.tw import TWMarket

logger = logging.getLogger(__name__)

__all__ = [
    "calc_position_value",
    "compute_existing_asset_value",
    "fetch_portfolio_market_snapshot",
    "fetch_tw_market_snapshot",
    "get_position_lots",
]


def calc_position_value(
    position: list[PositionEntryDict], lot: float, price: pd.Series
) -> float:
    total = 0.0

    for entry in position:
        sid = resolve_position_entry_symbol(entry)
        if sid not in price:
            raise ValueError(f"stock {sid} not found")

        value = float(entry["quantity"]) * float(price[sid]) * lot
        if not math.isnan(value):
            total += value
        else:
            logger.warning(
                "price of %s is %s, quantity is %s",
                sid,
                price[sid],
                entry["quantity"],
            )

    return total


def compute_existing_asset_value(
    position_data: Mapping[str, StrategyPositionDataDict],
    portfolio: Mapping[str, PositionScheduler],
    updated_strategies: list[str],
) -> float:
    asset_value = 0.0

    for sid, info in position_data.items():
        if sid in updated_strategies:
            continue
        try:
            market_name = info.get("market")
            sid_market = (
                get_market_by_name(market_name)
                if isinstance(market_name, str)
                else None
            )
            if sid_market is None:
                sid_market = portfolio[sid].market if sid in portfolio else TWMarket()
        except (KeyError, ValueError, RuntimeError):
            sid_market = TWMarket()

        sid_lot = sid_market.get_odd_lot()
        sid_price = sid_market.get_price("close", adj=False).ffill().iloc[-1]
        asset_value += calc_position_value(
            info["position"], lot=sid_lot, price=sid_price
        )

    return asset_value


def fetch_tw_market_snapshot() -> tuple[
    dict[str, float], dict[str, float], dict[str, float]
]:
    market = TWMarket()
    ref_price = market.get_reference_price()
    close_price = market.get_price("close", adj=False).iloc[-1].to_dict()
    volume = market.get_price("volume", adj=False).iloc[-1].to_dict()
    return ref_price, close_price, volume


def fetch_portfolio_market_snapshot(
    position_data: Mapping[str, StrategyPositionDataDict], *, include_tw: bool = False
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Fetch each strategy's own market, retaining TW custom-position quotes."""
    symbols_by_market: dict[str, set[str]] = {}
    for info in position_data.values():
        symbols = symbols_by_market.setdefault(info.get("market", "tw_stock"), set())
        symbols.update(resolve_position_entry_symbol(p) for p in info["position"])

    snapshot = (
        fetch_tw_market_snapshot()
        if include_tw or not symbols_by_market or "tw_stock" in symbols_by_market
        else ({}, {}, {})
    )
    for name, symbols in symbols_by_market.items():
        if name == "tw_stock":
            continue
        market = get_market_by_name(name)
        market_snapshot = (
            market.get_reference_price(),
            market.get_price("close", adj=False).iloc[-1].to_dict(),
            market.get_price("volume", adj=False).iloc[-1].to_dict(),
        )
        for combined, quotes in zip(snapshot, market_snapshot, strict=True):
            combined.update(
                (symbol, quotes[symbol]) for symbol in symbols if symbol in quotes
            )
    return snapshot


def get_position_lots(
    position_data: Mapping[str, StrategyPositionDataDict],
) -> dict[str, int]:
    """Return shares per position unit; custom positions keep the TW default."""
    lots: dict[str, int] = {}
    for info in position_data.values():
        lot = get_market_by_name(info.get("market", "tw_stock")).get_odd_lot()
        lots.update(
            (resolve_position_entry_symbol(p), lot) for p in info.get("position", [])
        )
    return lots
