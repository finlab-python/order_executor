"""Keep a finlab ``Portfolio`` in sync with a broker account.

``finlab.portfolio.PortfolioSyncManager`` and the old ``finlab.portfolio`` module
paths (``finlab.portfolio.portfolio_sync_manager``, ``finlab.portfolio.sync_*`` ...)
load these modules, so existing code keeps working unchanged.
"""

from __future__ import annotations

from .portfolio_sync_manager import PortfolioSyncManager

__all__ = ["PortfolioSyncManager"]
