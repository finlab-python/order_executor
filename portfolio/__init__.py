"""Keep a finlab ``Portfolio`` in sync with a broker account.

``finlab.portfolio.PortfolioSyncManager`` and the old ``finlab.portfolio`` module
paths (``finlab.portfolio.portfolio_sync_manager``, ``finlab.portfolio.sync_*`` ...)
load these modules, so existing code keeps working unchanged.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .portfolio_sync_manager import PortfolioSyncManager

__all__ = ["PortfolioSyncManager"]


def __getattr__(name: str) -> Any:
    # Lazy, so importing one submodule (e.g. broker_history for
    # TradeReview.from_account) does not load the whole sync stack.
    if name == "PortfolioSyncManager":
        return importlib.import_module(
            f"{__name__}.portfolio_sync_manager"
        ).PortfolioSyncManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
