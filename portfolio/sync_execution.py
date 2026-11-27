"""Execution helpers for ``PortfolioSyncManager``."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from ..core.executor import OrderExecutor
from .sync_margin import margin_cash_position_combine
from .sync_state import get_position

if TYPE_CHECKING:
    from typing_extensions import Unpack

    from ..core.account import Account
    from .sync_storage import DataPayload


class CreateOrderKwargs(TypedDict, total=False):
    market_order: bool
    best_price_limit: bool
    view_only: bool
    extra_bid_pct: float
    progress: float
    progress_precision: int
    buy_only: bool
    sell_only: bool


__all__ = [
    "CreateOrderKwargs",
    "build_order_executor",
    "create_order_executor",
    "sync_portfolio",
]


def build_order_executor(
    data: DataPayload,
    account: Account,
    at: str,
    consider_margin_as_asset: bool,
    market_name: str | None,
) -> OrderExecutor:
    account_position = account.get_position()
    ideal_position = get_position(data, market_name=market_name, at=at)

    if consider_margin_as_asset:
        ideal_position = margin_cash_position_combine(account_position, ideal_position)

    return OrderExecutor(ideal_position, account)


def sync_portfolio(
    data: DataPayload,
    account: Account,
    at: str = "close",
    consider_margin_as_asset: bool = True,
    market_name: str | None = None,
    **kwargs: Unpack[CreateOrderKwargs],
) -> OrderExecutor:
    order_executor = build_order_executor(
        data, account, at, consider_margin_as_asset, market_name
    )
    order_executor.create_orders(**kwargs)
    return order_executor


def create_order_executor(
    data: DataPayload,
    account: Account,
    at: str = "close",
    consider_margin_as_asset: bool = False,
    market_name: str | None = None,
) -> OrderExecutor:
    return build_order_executor(
        data, account, at, consider_margin_as_asset, market_name
    )
