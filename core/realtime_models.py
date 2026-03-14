"""Unified realtime event models."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from finlab.online.core.enums import Action, OrderCondition, OrderStatus

from .realtime_normalizers import (
    BOOK_DEPTH,
    calculate_tick_pct_change,
    normalize_book_side,
    pad_levels,
    to_optional_float,
)


@dataclass
class Tick:
    """A single trade tick from the exchange."""

    stock_id: str
    price: float
    volume: int
    total_volume: int
    time: datetime.datetime
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    avg_price: float = 0.0
    tick_type: int = 0
    prev_close: float | None = None
    pct_change: float | None = None
    source: str = "trade"

    def __post_init__(self) -> None:
        self.prev_close = to_optional_float(self.prev_close)
        native_pct_change = to_optional_float(self.pct_change)
        self.pct_change = (
            native_pct_change
            if native_pct_change is not None
            else calculate_tick_pct_change(
                price=self.price,
                prev_close=self.prev_close,
            )
        )
        if not isinstance(self.source, str):
            self.source = "unknown"
        self.source = self.source.lower()


@dataclass
class BookLevel:
    """Single order-book level."""

    price: float
    volume: int


@dataclass
class BidAsk:
    """Order book snapshot (supports multi-level bid/ask)."""

    stock_id: str
    bid_prices: list[float]
    bid_volumes: list[int]
    ask_prices: list[float]
    ask_volumes: list[int]
    time: datetime.datetime

    def __post_init__(self) -> None:
        self.bid_prices, self.bid_volumes = normalize_book_side(
            self.bid_prices, self.bid_volumes, depth=BOOK_DEPTH
        )
        self.ask_prices, self.ask_volumes = normalize_book_side(
            self.ask_prices, self.ask_volumes, depth=BOOK_DEPTH
        )

    @property
    def bid_levels(self) -> list[BookLevel]:
        return [
            BookLevel(price=p, volume=v)
            for p, v in zip(self.bid_prices, self.bid_volumes)
        ]

    @property
    def ask_levels(self) -> list[BookLevel]:
        return [
            BookLevel(price=p, volume=v)
            for p, v in zip(self.ask_prices, self.ask_volumes)
        ]

    @property
    def bid_prices_top5(self) -> list[float]:
        return pad_levels(self.bid_prices, BOOK_DEPTH, 0.0)

    @property
    def bid_volumes_top5(self) -> list[int]:
        return pad_levels(self.bid_volumes, BOOK_DEPTH, 0)

    @property
    def ask_prices_top5(self) -> list[float]:
        return pad_levels(self.ask_prices, BOOK_DEPTH, 0.0)

    @property
    def ask_volumes_top5(self) -> list[int]:
        return pad_levels(self.ask_volumes, BOOK_DEPTH, 0)


@dataclass
class OrderUpdate:
    """Broker-pushed order status change."""

    order_id: str
    stock_id: str
    action: Action
    price: float
    quantity: float
    filled_quantity: float
    status: OrderStatus
    order_condition: OrderCondition
    time: datetime.datetime
    operation: str = ""
    org_event: Any = None


@dataclass
class Fill:
    """A single fill/deal execution."""

    order_id: str
    stock_id: str
    action: Action
    price: float
    quantity: float
    time: datetime.datetime
    org_event: Any = None


@dataclass
class BalanceUpdate:
    """Realtime account balance snapshot."""

    account_id: str
    broker: str
    available_balance: float | None = None
    reserved_amount: float | None = None
    dedicated_account_balance: float | None = None
    cash: float | None = None
    settlement: float | None = None
    total_balance: float | None = None
    currency: str = "TWD"
    time: datetime.datetime = field(default_factory=datetime.datetime.now)
    org_event: Any = None

    def __post_init__(self) -> None:
        self.available_balance = to_optional_float(self.available_balance)
        self.reserved_amount = to_optional_float(self.reserved_amount)
        self.dedicated_account_balance = to_optional_float(
            self.dedicated_account_balance
        )
        self.cash = to_optional_float(self.cash)
        self.settlement = to_optional_float(self.settlement)
        self.total_balance = to_optional_float(self.total_balance)
        if not isinstance(self.time, datetime.datetime):
            self.time = datetime.datetime.now()

    def snapshot_key(self) -> tuple:
        return (
            self.available_balance,
            self.reserved_amount,
            self.dedicated_account_balance,
            self.cash,
            self.settlement,
            self.total_balance,
            self.currency,
        )


class ConnectionState(Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


__all__ = [
    "BalanceUpdate",
    "BidAsk",
    "BookLevel",
    "ConnectionState",
    "Fill",
    "OrderUpdate",
    "Tick",
]
