"""Margin / cash position combining logic for PortfolioSyncManager.

Extracted from portfolio_sync_manager.py so that the cross-order-condition
reconciliation can be tested and reasoned about independently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from finlab.compat import resolve_position_entry_symbol

from ..core.enums import OrderCondition
from ..core.position import Position

__all__ = ["margin_cash_position_combine"]

if TYPE_CHECKING:
    from decimal import Decimal


def _quantity(entry: dict[str, object]) -> Decimal:
    return cast("Decimal", entry["quantity"])


def margin_cash_position_combine(acp: Position, idp: Position) -> Position:
    """Merge cash and margin-trading positions to avoid redundant orders.

    When the diff between the ideal and account positions contains
    opposing quantities for the same symbol across CASH and
    MARGIN_TRADING conditions, the opposing amounts cancel out so
    that only the net difference is traded.

    Args:
        acp: Current account position.
        idp: Ideal (target) position.

    Returns:
        Adjusted ideal position with cancelled cross-condition quantities.
    """
    diff = idp - acp

    cash = {
        resolve_position_entry_symbol(p): p.copy()
        for p in diff.position
        if p["order_condition"] == OrderCondition.CASH
    }
    margin_trading = {
        resolve_position_entry_symbol(p): p.copy()
        for p in diff.position
        if p["order_condition"] == OrderCondition.MARGIN_TRADING
    }

    for sid in cash.keys() & margin_trading.keys():
        cash_entry = cash[sid]
        margin_entry = margin_trading[sid]
        cash_quantity = _quantity(cash_entry)
        margin_quantity = _quantity(margin_entry)

        if cash_quantity * margin_quantity >= 0:
            continue

        reduce_amount = min(abs(cash_quantity), abs(margin_quantity))

        if cash_quantity > 0:
            cash_entry["quantity"] = cash_quantity - reduce_amount
            margin_entry["quantity"] = margin_quantity + reduce_amount
        else:
            cash_entry["quantity"] = cash_quantity + reduce_amount
            margin_entry["quantity"] = margin_quantity - reduce_amount

    newdiff_items = [p for p in cash.values() if p["quantity"] != 0] + [
        p for p in margin_trading.values() if p["quantity"] != 0
    ]
    newdiff = Position.from_list(newdiff_items)
    return idp - diff + newdiff
