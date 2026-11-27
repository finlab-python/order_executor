from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

__all__ = ["AccountRecord", "PortfolioAnalyzer", "ScheduleRecord"]

if TYPE_CHECKING:
    from ..core.account import Account, Order
    from ..core.position import Position
    from .portfolio_sync_manager import PortfolioSyncManager


@dataclass(slots=True)
class ScheduleRecord:
    time: str

    # scheduled position
    open_position: Position
    close_position: Position


@dataclass(slots=True)
class AccountRecord:
    time: str
    position: Position
    daily_orders: list[Order]


class PortfolioAnalyzer:
    def __init__(self) -> None:
        self.records: list[ScheduleRecord | AccountRecord] = []
        self.data: dict[str, object] = {}

    def record_portfolio(self, manager: PortfolioSyncManager) -> None:
        pass

    def record_account(self, account: Account) -> None:
        pass
