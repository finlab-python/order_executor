"""Unified real-time streaming interface for broker accounts.

Defines the abstract RealtimeProvider mixin and unified event dataclasses
(Tick, BidAsk, OrderUpdate, Fill) that normalize data from different brokers.

Brokers that support streaming inherit RealtimeProvider alongside Account.
"""

from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Any, Callable, List, Optional
from enum import Enum
import datetime
import logging
import math

from finlab.online.core.enums import Action, OrderCondition, OrderStatus

logger = logging.getLogger(__name__)


# ── Unified event dataclasses ────────────────────────────────────────


def to_optional_float(value: Any) -> Optional[float]:
    """Convert values from broker payloads to finite float, else None."""
    if value is None:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(converted):
        return None
    return converted


def get_field_value(source: Any, field_name: str) -> Any:
    """Read a field from either dict-like or object-like broker payloads."""
    if isinstance(source, dict):
        return source.get(field_name)
    return getattr(source, field_name, None)


def get_first_valid_float(source: Any, *field_names: str) -> Optional[float]:
    """Return first field that can be parsed as a finite float."""
    for name in field_names:
        value = get_field_value(source, name)
        converted = to_optional_float(value)
        if converted is not None:
            return converted
    return None


def calculate_tick_pct_change(
    price: Any,
    prev_close: Any = None,
) -> Optional[float]:
    """Resolve tick pct change by priority: prev_close only."""
    p = to_optional_float(price)
    if p is None:
        return None

    prev = to_optional_float(prev_close)
    if prev not in (None, 0):
        return (p / prev - 1) * 100

    return None


@dataclass
class Tick:
    """A single trade tick from the exchange.

    `pct_change` is today's percent change.
    Priority: broker native value > (price/prev_close-1)*100.
    """
    stock_id: str
    price: float
    volume: int
    total_volume: int
    time: datetime.datetime
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    avg_price: float = 0.0
    tick_type: int = 0  # 1=buy, 2=sell, 0=unknown
    prev_close: Optional[float] = None
    pct_change: Optional[float] = None

    def __post_init__(self):
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


@dataclass
class BidAsk:
    """Order book snapshot (supports multi-level bid/ask)."""
    stock_id: str
    bid_prices: List[float]
    bid_volumes: List[int]
    ask_prices: List[float]
    ask_volumes: List[int]
    time: datetime.datetime


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
    operation: str = ""  # "new", "update_price", "update_qty", "cancel"
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


class ConnectionState(Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


# ── Callback type aliases ────────────────────────────────────────────

TickCallback = Callable[[Tick], None]
BidAskCallback = Callable[[BidAsk], None]
OrderUpdateCallback = Callable[[OrderUpdate], None]
FillCallback = Callable[[Fill], None]
ConnectionCallback = Callable[[ConnectionState, str], None]


# ── Abstract streaming mixin ────────────────────────────────────────

class RealtimeProvider(ABC):
    """Abstract mixin for real-time market data and order event streaming.

    Inherit alongside Account to add streaming support. Not all methods need
    real implementations — brokers without quote streaming can raise
    NotImplementedError for subscribe_ticks/subscribe_bidask while still
    supporting order/fill events.

    Usage::

        account = SinopacAccount(...)
        account.on_tick(my_tick_handler)
        account.on_fill(my_fill_handler)
        account.connect_realtime()
        account.subscribe_ticks(["2330", "2317"])
        # ... later
        account.unsubscribe_ticks(["2330"])
        account.disconnect_realtime()
    """

    def _init_realtime(self):
        """Call from subclass __init__ to initialize callback lists."""
        self._tick_callbacks: List[TickCallback] = []
        self._bidask_callbacks: List[BidAskCallback] = []
        self._order_update_callbacks: List[OrderUpdateCallback] = []
        self._fill_callbacks: List[FillCallback] = []
        self._connection_callbacks: List[ConnectionCallback] = []
        self._realtime_connected = False

    # ── Market data subscriptions ────────────────────────────

    @abstractmethod
    def subscribe_ticks(self, stock_ids: List[str]) -> None:
        """Start receiving Tick events for the given symbols."""
        ...

    @abstractmethod
    def unsubscribe_ticks(self, stock_ids: List[str]) -> None:
        """Stop receiving Tick events for the given symbols."""
        ...

    @abstractmethod
    def subscribe_bidask(self, stock_ids: List[str]) -> None:
        """Start receiving BidAsk events for the given symbols."""
        ...

    @abstractmethod
    def unsubscribe_bidask(self, stock_ids: List[str]) -> None:
        """Stop receiving BidAsk events for the given symbols."""
        ...

    # ── Callback registration ────────────────────────────────

    def on_tick(self, callback: TickCallback) -> None:
        """Register a handler for tick events. Can be called multiple times."""
        self._tick_callbacks.append(callback)

    def on_bidask(self, callback: BidAskCallback) -> None:
        """Register a handler for bid/ask events."""
        self._bidask_callbacks.append(callback)

    def on_order_update(self, callback: OrderUpdateCallback) -> None:
        """Register a handler for order status changes."""
        self._order_update_callbacks.append(callback)

    def on_fill(self, callback: FillCallback) -> None:
        """Register a handler for fill/deal executions."""
        self._fill_callbacks.append(callback)

    def on_connection(self, callback: ConnectionCallback) -> None:
        """Register a handler for connection state changes."""
        self._connection_callbacks.append(callback)

    # ── Dispatch helpers (for subclass use) ──────────────────

    def _emit_tick(self, tick: Tick):
        for cb in self._tick_callbacks:
            try:
                cb(tick)
            except Exception:
                logger.exception("Error in tick callback")

    def _emit_bidask(self, bidask: BidAsk):
        for cb in self._bidask_callbacks:
            try:
                cb(bidask)
            except Exception:
                logger.exception("Error in bidask callback")

    def _emit_order_update(self, update: OrderUpdate):
        for cb in self._order_update_callbacks:
            try:
                cb(update)
            except Exception:
                logger.exception("Error in order_update callback")

    def _emit_fill(self, fill: Fill):
        for cb in self._fill_callbacks:
            try:
                cb(fill)
            except Exception:
                logger.exception("Error in fill callback")

    def _emit_connection(self, state: ConnectionState, message: str = ""):
        for cb in self._connection_callbacks:
            try:
                cb(state, message)
            except Exception:
                logger.exception("Error in connection callback")

    # ── Lifecycle ────────────────────────────────────────────

    @abstractmethod
    def connect_realtime(self) -> None:
        """Initialize websocket/streaming connections and wire broker callbacks.

        Must be called before subscribing to ticks/bidask.
        """
        ...

    @abstractmethod
    def disconnect_realtime(self) -> None:
        """Tear down all streaming connections and clear subscriptions."""
        ...
