"""State and position-aggregation helpers for ``PortfolioSyncManager``."""

from __future__ import annotations

from typing import Any

from finlab.compat import resolve_position_entry_symbol
from finlab.markets import get_market_by_name

from ..core.position import Position
from .validation import normalize_data_payload

__all__ = [
    "clear_state",
    "get_last_market_timestamp",
    "get_position",
    "get_strategy_position",
]


def clear_state() -> dict[str, Any]:
    return normalize_data_payload(None)


def get_last_market_timestamp(data: dict[str, Any]) -> str | None:
    timestamps = [
        sdata.get("last_market_timestamp")
        for sdata in data["position"].values()
        if "last_market_timestamp" in sdata
    ]
    if not timestamps:
        return None
    return max(timestamps)


def get_strategy_position(
    data: dict[str, Any], strategy_name: str, at: str
) -> list[dict[str, Any]]:
    strategy_position = data["position"].get(strategy_name, {})

    if strategy_position.get("entry_at", "close") != strategy_position.get(
        "exit_at", "close"
    ):
        raise ValueError("entry_at and exit_at difference is not supported")

    market = get_market_by_name(strategy_position["market"])

    has_market_timestamp = strategy_position.get("last_market_timestamp") is not None
    is_trade_at_open = strategy_position["entry_at"] == "open"

    latest_market_timestamp = get_last_market_timestamp(data)

    use_previous_position = (
        (at == "open")
        and has_market_timestamp
        and not is_trade_at_open
        # Last: loads the market's close table, which only this check needs.
        and strategy_position.get("last_market_timestamp")
        == market.market_close_at_timestamp(
            market.get_price("close").index[-1]
        ).isoformat()
    ) or (
        (at == "prev_close")
        and (latest_market_timestamp == strategy_position.get("last_market_timestamp"))
    )

    if not use_previous_position:
        return strategy_position["position"]

    strategy_history = data["history"].get(strategy_name, [])
    if not strategy_history:
        return strategy_position["position"]

    if strategy_history[-1].get("last_market_timestamp") == strategy_position.get(
        "last_market_timestamp"
    ):
        if len(strategy_history) >= 2:
            return strategy_history[-2]["position"]
        return strategy_position["position"]
    return strategy_history[-1]["position"]


def get_position(
    data: dict[str, Any], at: str = "close", market_name: str | None = None
) -> Position:
    positions = {
        pname: Position.from_list(get_strategy_position(data, pname, at))
        for pname, sdata in data["position"].items()
        if market_name is None or sdata["market"] == market_name
    }

    for pname, pos in positions.items():
        for p in pos:
            if "weight" in p and p["weight"] is not None:
                p["weight"] *= data["position"][pname]["weight"]
            else:
                p["weight"] = 1 / len(pos.position) * data["position"][pname]["weight"]

    result = sum(list(positions.values()), Position({}))

    if "custom_position" in data["config"]:
        result += Position.from_list(data["config"]["custom_position"])

    if "excluded_stock_ids" in data["config"]:
        excluded = data["config"]["excluded_stock_ids"]
        filtered_position: list[Any] = []
        for p in result.position:
            p_sid = resolve_position_entry_symbol(p)
            if p_sid not in excluded:
                filtered_position.append(p)
        result = Position.from_list(filtered_position)

    return result
