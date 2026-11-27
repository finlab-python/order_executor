"""Update orchestration for ``PortfolioSyncManager``."""

from __future__ import annotations

import copy
import datetime
import logging
from typing import Any

from finlab.core.report import Report
from finlab.portfolio.portfolio import Portfolio, PositionScheduler
from finlab.rebalance import signal_label

from ..core.position import Position
from .sync_decisions import identify_updated_strategies
from .sync_market_data import compute_existing_asset_value
from .sync_stops import apply_stop_triggers
from .validation import (
    compute_rebalance_funds,
    validate_rebalance_balance,
    validate_sleeve_weights,
)

logger = logging.getLogger(__name__)

__all__ = [
    "build_config_snapshot",
    "extract_saved_update_params",
    "update_portfolio_state",
]


def normalize_portfolio_input(portfolio: Portfolio | Report | Any) -> dict[str, Any]:
    """Normalize public portfolio/report inputs to an execution-map dict."""
    if not isinstance(portfolio, Portfolio):
        if isinstance(portfolio, Report):
            portfolio = Portfolio(portfolio)
        else:
            raise ValueError(
                f"portfolio should be Portfolio or Report object, got {type(portfolio)}"
            )

    if hasattr(portfolio, "position_schedulers"):
        execution_map = portfolio.position_schedulers
    elif hasattr(portfolio, "execution"):
        execution_map = portfolio.execution
    else:
        execution_map = {}

    if not isinstance(execution_map, dict):
        execution_map = {"strategy": execution_map}

    return execution_map


def _normalize_custom_position(
    custom_position: Position | dict[str, Any] | None,
) -> list[dict[str, Any]] | None:
    if not custom_position:
        return None
    if isinstance(custom_position, dict):
        return Position(custom_position).to_list()
    if isinstance(custom_position, Position):
        return custom_position.to_list()
    raise ValueError(
        f"custom_position should be Position or dict object, got {type(custom_position)}"
    )


def build_config_snapshot(
    execution_map: dict[str, Any],
    *,
    total_balance: float,
    rebalance_safety_weight: float,
    smooth_transition: bool | None,
    force_override_difference: bool,
    custom_position: Position | dict[str, Any] | None,
    excluded_stock_ids: list[str] | None,
    excluded_symbols: list[str] | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Build the persisted config payload for the current update call."""
    config: dict[str, Any] = {
        "weights": {
            key.split("|")[0]: value.total_weight
            for key, value in execution_map.items()
        },
        "params": {
            "total_balance": total_balance,
            "rebalance_safety_weight": rebalance_safety_weight,
            "smooth_transition": smooth_transition,
            "force_override_difference": force_override_difference,
            "kwargs": kwargs,
        },
    }

    normalized_custom_position = _normalize_custom_position(custom_position)
    if normalized_custom_position is not None:
        config["custom_position"] = normalized_custom_position

    excluded = excluded_symbols or excluded_stock_ids
    if excluded:
        config["excluded_stock_ids"] = excluded

    return config


def extract_saved_update_params(data: dict[str, Any]) -> dict[str, Any]:
    """Return saved ``update()`` params merged with stored kwargs."""
    if "config" not in data:
        raise ValueError("config not found")

    params = copy.deepcopy(data["config"].get("params", {}))
    extra_kwargs = params.pop("kwargs", {})
    params.update(extra_kwargs)
    return params


def _resolve_smooth_transition(
    position: dict[str, Any],
    history: dict[str, Any],
    start_with_empty: bool,
    smooth_transition: bool | None,
) -> bool:
    if smooth_transition is not None:
        return smooth_transition
    return bool(position or history or start_with_empty)


def _prune_removed_strategies(
    position: dict[str, Any],
    history: dict[str, Any],
    portfolio: dict[str, Any],
) -> None:
    removed_position: list[str] = []

    for sid in position:
        if sid not in portfolio or portfolio[sid].total_weight == 0:
            logger.info("remove %s from portfolio", sid)
            removed_position.append(sid)

    for sid in removed_position:
        history.setdefault(sid, []).append(position[sid])
        position.pop(sid)


def _total_update_weight(
    portfolio: dict[str, Any], updated_strategies: list[str]
) -> float:
    return sum(portfolio[sid].total_weight for sid in updated_strategies)


def _log_fund_plan(
    total_balance: float, asset_value: float, funds: dict[str, float]
) -> None:
    display_info = {
        "投資總額": total_balance,
        "預計股票價值": asset_value,
        "預計賣出後流動資金": funds["liquid_value"],
        "預計保留現金": funds["rebalance_safety_fund"],
        "預計可買入金額": funds["free_value"],
    }

    for key, value in display_info.items():
        pct = (value / total_balance * 100) if total_balance else 0
        logger.info("%s: %d (%.2f%%)", key, int(value), pct)


def _snapshot_old_positions(
    position: dict[str, Any], updated_strategies: list[str]
) -> dict[str, Any]:
    old_positions = {
        sid: position[sid].copy() for sid in updated_strategies if sid in position
    }
    for pos in old_positions.values():
        pos["position"] = [p.copy() for p in pos.get("position", [])]
    return old_positions


def _rebuild_updated_positions(
    *,
    position: dict[str, Any],
    history: dict[str, Any],
    portfolio: dict[str, Any],
    updated_strategies: list[str],
    free_value: float,
    total_update_weight: float,
    now: datetime.datetime,
    build_kwargs: dict[str, Any],
) -> None:
    for sid in updated_strategies:
        allocation = portfolio[sid]

        if not isinstance(allocation, PositionScheduler):
            raise ValueError(
                f"portfolio[{sid}] should be PositionScheduler, got {type(allocation)}"
            )

        weight = allocation.total_weight
        fund = int(
            free_value * weight / total_update_weight if total_update_weight != 0 else 0
        )

        next_trading_time = allocation.market.market_close_at_timestamp(
            allocation.next_trading_date
        )

        market = allocation.market
        last_market_timestamp = market.market_close_at_timestamp(
            market.get_price("close").index[-1]
        )

        # Position.from_report follows the same rule to pick its target.
        applied = signal_label(
            allocation.next_weights.name
            if allocation.uses_next_weights()
            else allocation.weights.name
        )

        try:
            pos = Position.from_report(allocation, fund, **build_kwargs).to_list()
        except AssertionError as error:
            logger.warning(
                "Cannot create position for %s, because %sSet the position to zero.",
                sid,
                error,
            )
            pos = []

        if sid in position:
            history[sid] = history.get(sid, [])

            while (
                history[sid]
                and history[sid][-1]["next_trading_time"]
                == next_trading_time.isoformat()
            ):
                history[sid].pop()

            history[sid].append(position[sid])

        position[sid] = {
            "timestamp": now.isoformat(),
            "next_trading_time": next_trading_time.isoformat(),
            "position": pos,
            "allocation": fund,
            "weight": weight,
            "entry_at": allocation.trade_at
            if isinstance(allocation.trade_at, str)
            else "close",
            "exit_at": allocation.trade_at
            if isinstance(allocation.trade_at, str)
            else "close",
            "stop": [],
            "stop_loss": allocation.stop_loss,
            "take_profit": allocation.take_profit
            if allocation.take_profit == allocation.take_profit
            else None,
            "trail_stop": allocation.trail_stop
            if allocation.trail_stop == allocation.trail_stop
            else None,
            "market": allocation.market.get_name(),
            "last_market_timestamp": last_market_timestamp.isoformat(),
        }
        if applied is not None:
            position[sid]["applied_signal_at"] = applied.isoformat()
        logger.info("update position %s", sid)


def update_portfolio_state(
    data: dict[str, Any],
    portfolio: Portfolio | Report | Any,
    *,
    start_with_empty: bool,
    total_balance: float = 0,
    rebalance_safety_weight: float = 0.2,
    smooth_transition: bool | None = None,
    force_override_difference: bool = False,
    custom_position: Position | dict[str, Any] | None = None,
    excluded_stock_ids: list[str] | None = None,
    excluded_symbols: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Mutate and return portfolio sync state for one update cycle."""
    execution_map = normalize_portfolio_input(portfolio)
    config = build_config_snapshot(
        execution_map,
        total_balance=total_balance,
        rebalance_safety_weight=rebalance_safety_weight,
        smooth_transition=smooth_transition,
        force_override_difference=force_override_difference,
        custom_position=custom_position,
        excluded_stock_ids=excluded_stock_ids,
        excluded_symbols=excluded_symbols,
        kwargs=kwargs,
    )

    position = data["position"]
    history = data["history"]
    now = datetime.datetime.now().astimezone()
    smooth_transition = _resolve_smooth_transition(
        position, history, start_with_empty, smooth_transition
    )

    # Plan against the holdings that would remain after pruning, without
    # changing config, positions or history until the balance is validated.
    retained_position = {
        sid: info
        for sid, info in position.items()
        if sid in execution_map and execution_map[sid].total_weight != 0
    }

    updated_strategies = identify_updated_strategies(
        portfolio=execution_map,
        position=retained_position,
        smooth_transition=smooth_transition,
        force_override_difference=force_override_difference,
    )

    asset_value = compute_existing_asset_value(
        retained_position,
        execution_map,
        updated_strategies,
    )
    total_update_weight = _total_update_weight(execution_map, updated_strategies)

    # Unused funds must not block daily stop processing or removal-only calls.
    # Inspect the selected sleeves themselves: a zero aggregate weight does
    # not necessarily mean that no positive-weight sleeve will be rebuilt.
    if any(execution_map[sid].total_weight > 0 for sid in updated_strategies):
        validate_rebalance_balance(total_balance, asset_value)

    validate_sleeve_weights(
        {sid: execution_map[sid].total_weight for sid in updated_strategies}
    )

    funds = compute_rebalance_funds(
        total_balance, asset_value, total_update_weight, rebalance_safety_weight
    )
    data["config"] = config
    _prune_removed_strategies(position, history, execution_map)
    _log_fund_plan(total_balance, asset_value, funds)

    old_positions = _snapshot_old_positions(position, updated_strategies)
    _rebuild_updated_positions(
        position=position,
        history=history,
        portfolio=execution_map,
        updated_strategies=updated_strategies,
        free_value=funds["free_value"],
        total_update_weight=total_update_weight,
        now=now,
        build_kwargs=kwargs,
    )

    apply_stop_triggers(
        position=position,
        portfolio=execution_map,
        old_positions=old_positions,
        now=now,
    )

    return data
