"""Stop-loss / take-profit trigger processing for PortfolioSyncManager.

Extracted from the ``update`` method to isolate the stop-trigger
decision logic from portfolio rebalancing orchestration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from finlab.compat import resolve_position_entry_symbol

if TYPE_CHECKING:
    import datetime
    from collections.abc import Mapping

    from finlab.portfolio.portfolio import PositionScheduler
    from finlab.schemas import PositionEntryDict, StrategyPositionDataDict

logger = logging.getLogger(__name__)

__all__ = ["apply_stop_triggers"]

_IMMEDIATE_STOP_ACTIONS = frozenset({"sl_", "tp_", "sl", "tp"})
_DEFERRED_STOP_ACTIONS = frozenset({"sl_enter", "tp_enter"})


def _zero_matching_new_positions(
    position_entries: list[PositionEntryDict],
    symbol: str,
) -> None:
    """Set ``quantity`` to 0 for all entries matching *symbol* in-place."""
    for entry in position_entries:
        if resolve_position_entry_symbol(entry) == symbol:
            entry["quantity"] = 0


def _record_stop_entries(
    *,
    allocation: PositionScheduler,
    old_pos: list[PositionEntryDict],
    position_record: StrategyPositionDataDict,
    action_filter: frozenset[str],
    now: datetime.datetime,
    strategy_id: str,
) -> None:
    """Scan *allocation.actions* for matching stop signals and record them."""
    matching_actions = allocation.actions[allocation.actions.isin(action_filter)]
    for action_label in matching_actions.index.tolist():
        symbol = action_label.split(" ")[0]
        for p in old_pos:
            p_sid = resolve_position_entry_symbol(p)
            if p_sid == symbol and p["quantity"] != 0:
                logger.info(
                    "%s %s has a %s signal, position set to zero",
                    strategy_id,
                    action_label,
                    allocation.actions[action_label],
                )
                stop_entry: dict[str, object] = dict(p)
                stop_entry["timestamp"] = now.isoformat()
                stop_entry["reason"] = allocation.actions.to_dict().get(action_label)
                position_record["stop"].append(stop_entry)
                _zero_matching_new_positions(position_record["position"], symbol)


def apply_stop_triggers(
    *,
    position: dict[str, StrategyPositionDataDict],
    portfolio: Mapping[str, PositionScheduler],
    old_positions: dict[str, StrategyPositionDataDict],
    now: datetime.datetime,
) -> None:
    """Process stop-loss and take-profit triggers across all strategies.

    Mutates *position* in-place by appending stop records and zeroing out
    triggered entries.
    """
    for sid, allocation in portfolio.items():
        if sid not in position:
            continue

        old_pos = old_positions.get(sid, {}).get("position")
        if old_pos is None:
            old_pos = position[sid].get("position", [])

        # Immediate stop triggers (sl_, tp_, sl, tp)
        if allocation.is_stop_triggered():
            _record_stop_entries(
                allocation=allocation,
                old_pos=old_pos,
                position_record=position[sid],
                action_filter=_IMMEDIATE_STOP_ACTIONS,
                now=now,
                strategy_id=sid,
            )

        # Deferred stop triggers (sl_enter, tp_enter) exit now and re-enter at
        # the next rebalance, so they only apply until that rebalance starts.
        if allocation.actions.isin(
            _DEFERRED_STOP_ACTIONS
        ).any() and not allocation.uses_next_weights(now):
            _record_stop_entries(
                allocation=allocation,
                old_pos=old_pos,
                position_record=position[sid],
                action_filter=_DEFERRED_STOP_ACTIONS,
                now=now,
                strategy_id=sid,
            )
