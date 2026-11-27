"""Validation and data sanitization helpers for PortfolioSyncManager.

Extracted from portfolio_sync_manager.py to isolate pure-function
validation logic that carries no broker or state dependencies.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .validation import replace_inf_nan

if TYPE_CHECKING:
    from collections.abc import MutableMapping

logger = logging.getLogger(__name__)

__all__ = ["position_type_check", "replace_inf_nan"]

_EXPECTED_FIELD_TYPES: list[tuple[str, tuple[type, ...], bool]] = [
    ("timestamp", (str,), True),
    ("next_trading_time", (str,), True),
    ("position", (list,), True),
    ("allocation", (float, int), True),
    ("weight", (float, int), True),
    ("entry_at", (str,), True),
    ("exit_at", (str,), True),
    ("stop", (list,), True),
    ("stop_loss", (float, int), False),
    ("take_profit", (float, int), False),
    ("trail_stop", (float, int), False),
    ("applied_signal_at", (str,), False),
]


def position_type_check(position_name: str, data: MutableMapping[str, object]) -> None:
    """Warn when position dict fields have unexpected types.

    Also applies a default market value when missing.
    """
    for field, types, required in _EXPECTED_FIELD_TYPES:
        value = data.get(field)
        if not required and value is None:
            continue
        if not isinstance(value, types):
            logger.warning(
                "%s: %s must be %s, got %s instead",
                position_name,
                field,
                " or ".join(t.__name__ for t in types),
                type(value).__name__,
            )

    if data.get("market") is None:
        data["market"] = "tw_stock"
