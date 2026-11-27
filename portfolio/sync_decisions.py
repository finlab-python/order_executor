"""Strategy-update decision logic for PortfolioSyncManager.update().

Extracted from portfolio_sync_manager.py so that the pure decision
paths -- which strategies need rebalancing, which have drifted, etc. --
can be tested without broker or market dependencies.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from finlab.compat import resolve_position_entry_symbol
from finlab.rebalance import execution_session_for, signal_label

if TYPE_CHECKING:
    import pandas as pd
    from finlab.portfolio.portfolio import PositionScheduler
    from finlab.schemas import StrategyPositionDataDict

logger = logging.getLogger(__name__)

__all__ = ["identify_updated_strategies"]


def _is_later_rebalance(
    allocation: PositionScheduler, boundary: pd.Timestamp, applied: pd.Timestamp
) -> bool:
    """Whether ``boundary`` trades after the target built for ``applied``.

    TW daily signals compare execution sessions, so a weekend or holiday label
    executing on the same session as a weekday label is the same rebalance.
    """
    if allocation.uses_trading_calendar():
        boundary_session = execution_session_for(boundary)
        applied_session = execution_session_for(applied)
        if boundary_session is not None and applied_session is not None:
            return boundary_session > applied_session
    market = allocation.market
    return market.market_close_at_timestamp(
        boundary
    ) > market.market_close_at_timestamp(applied)


def _missed_rebalance(
    sid: str,
    allocation: PositionScheduler,
    record: StrategyPositionDataDict | None,
) -> bool:
    """Log and return True when the stored position skipped a rebalance.

    ``allocation.weights.name`` labels the latest target already in force in
    the report. ``record["applied_signal_at"]`` labels the target the PM last
    built. A later report label means the rebalance window closed without an
    ``update()`` call, so the PM still holds an old target. Records written
    before ``applied_signal_at`` existed compare the stored boundary close.
    A malformed record is logged and skipped so it cannot stop other updates.
    """
    boundary = signal_label(allocation.weights.name)
    if record is None or boundary is None:
        return False
    try:
        applied = signal_label(record.get("applied_signal_at"))
        if applied is not None:
            missed = _is_later_rebalance(allocation, boundary, applied)
            held = applied.isoformat()
        else:
            promoted = datetime.datetime.fromisoformat(record["next_trading_time"])
            missed = allocation.market.market_close_at_timestamp(boundary) > promoted
            held = promoted.isoformat()
    except (KeyError, TypeError, ValueError) as error:
        logger.warning("%s: cannot check for a missed rebalance: %s", sid, error)
        return False
    if missed:
        logger.warning(
            "%s missed the rebalance for the signal at %s: the portfolio still "
            "holds the target built for %s. Catching up to the report's current "
            "target now.",
            sid,
            boundary.isoformat(),
            held,
        )
    return missed


def identify_updated_strategies(
    *,
    portfolio: dict[str, PositionScheduler],
    position: dict[str, StrategyPositionDataDict],
    smooth_transition: bool,
    force_override_difference: bool,
) -> list[str]:
    """Return the list of strategy IDs that should be rebalanced.

    This encapsulates two decision passes:

    1. **Rebalance triggers** -- a strategy is marked for update when its
       rebalance date has arrived or when its weight changed (unless
       *smooth_transition* suppresses the latter).
    2. **Stock-list drift** -- if a strategy's current position contains
       symbols no longer present in its report, it is also marked (only
       when *force_override_difference* is True).
    """
    updated: list[str] = []

    # --- Pass 1: rebalance / weight triggers ---
    for sid, allocation in portfolio.items():
        weight = allocation.total_weight

        if weight == 0 and sid not in position:
            continue

        weight_is_updated = sid not in position or weight != position[sid]["weight"]
        is_trading_date = allocation.is_rebalance_due()
        missed_rebalance = _missed_rebalance(sid, allocation, position.get(sid))

        update_conditions = [
            (is_trading_date, "today is trading date"),
            (missed_rebalance, "missed rebalance catch-up"),
            (
                not smooth_transition and weight_is_updated,
                "weight changed (set smooth_transition=True to avoid this)",
            ),
        ]

        if any(flag for flag, _ in update_conditions):
            logger.info(
                "%s should be updated because: %s",
                sid,
                ", ".join(reason for (flag, reason) in update_conditions if flag),
            )
            updated.append(sid)

        if smooth_transition and weight_is_updated:
            logger.info(
                "%s weight changed, but not updated because "
                "smooth_transition is enabled. It will be updated when "
                "next rebalance date comes.",
                sid,
            )
            logger.info(
                "If you want to update the weight immediately, "
                "set smooth_transition=False"
            )

    # --- Pass 2: stock-list drift detection ---
    for sid, info in position.items():
        if sid in updated:
            continue
        if sid not in portfolio:
            logger.warning("%s not in portfolio", sid)
            continue

        position_sids = sorted(
            resolve_position_entry_symbol(p) for p in info["position"]
        )
        report = portfolio[sid]
        report_ids = [s.split(" ")[0] for s in sorted(report.weights.index.tolist())]

        if not all(s in report_ids for s in position_sids):
            logger.warning("%s has changed stock list", sid)
            logger.warning("current: %s", position_sids)
            logger.warning("report: %s", report_ids)

            if force_override_difference:
                logger.warning("force override")
                updated.append(sid)
            else:
                logger.warning("please set force_override_difference=True to override")

    return updated
