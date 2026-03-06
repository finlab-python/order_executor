"""Unified real-time streaming interface for broker accounts.

Defines the abstract RealtimeProvider mixin and unified event dataclasses
(Tick, BidAsk, OrderUpdate, Fill, BalanceUpdate) that normalize data from
different brokers.

Brokers that support streaming inherit RealtimeProvider alongside Account.
"""

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any, Callable, List, Optional
from enum import Enum
import datetime
import logging
import math
import threading

from finlab.online.core.enums import Action, OrderCondition, OrderStatus

logger = logging.getLogger(__name__)
BOOK_DEPTH = 5


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


def to_optional_int(value: Any) -> Optional[int]:
    """Convert values from broker payloads to finite int, else None."""
    converted = to_optional_float(value)
    if converted is None:
        return None
    return int(converted)


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


def normalize_book_side(
    prices: Optional[List[Any]],
    volumes: Optional[List[Any]],
    depth: int = BOOK_DEPTH,
) -> tuple[List[float], List[int]]:
    """Normalize book side values, preserving level alignment up to `depth`."""
    if depth <= 0:
        return [], []

    prices = list(prices or [])
    volumes = list(volumes or [])
    last_meaningful_idx = -1
    for idx in range(depth):
        price = to_optional_float(prices[idx]) if idx < len(prices) else None
        volume = to_optional_int(volumes[idx]) if idx < len(volumes) else None
        if price is not None or volume is not None:
            last_meaningful_idx = idx

    if last_meaningful_idx < 0:
        return [], []

    normalized_prices: List[float] = []
    normalized_volumes: List[int] = []

    for idx in range(last_meaningful_idx + 1):
        price = to_optional_float(prices[idx]) if idx < len(prices) else None
        volume = to_optional_int(volumes[idx]) if idx < len(volumes) else None
        normalized_prices.append(price if price is not None else 0.0)
        normalized_volumes.append(volume if volume is not None else 0)

    return normalized_prices, normalized_volumes


def pad_levels(levels: List[Any], depth: int, fill_value: Any) -> List[Any]:
    """Return a fixed-length list without mutating source list."""
    if len(levels) >= depth:
        return list(levels[:depth])
    return list(levels) + [fill_value] * (depth - len(levels))


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
    source: str = "trade"  # trade | aggregate | unknown

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
    bid_prices: List[float]
    bid_volumes: List[int]
    ask_prices: List[float]
    ask_volumes: List[int]
    time: datetime.datetime

    def __post_init__(self):
        self.bid_prices, self.bid_volumes = normalize_book_side(
            self.bid_prices, self.bid_volumes, depth=BOOK_DEPTH
        )
        self.ask_prices, self.ask_volumes = normalize_book_side(
            self.ask_prices, self.ask_volumes, depth=BOOK_DEPTH
        )

    @property
    def bid_levels(self) -> List[BookLevel]:
        return [
            BookLevel(price=p, volume=v)
            for p, v in zip(self.bid_prices, self.bid_volumes)
        ]

    @property
    def ask_levels(self) -> List[BookLevel]:
        return [
            BookLevel(price=p, volume=v)
            for p, v in zip(self.ask_prices, self.ask_volumes)
        ]

    @property
    def bid_prices_top5(self) -> List[float]:
        return pad_levels(self.bid_prices, BOOK_DEPTH, 0.0)

    @property
    def bid_volumes_top5(self) -> List[int]:
        return pad_levels(self.bid_volumes, BOOK_DEPTH, 0)

    @property
    def ask_prices_top5(self) -> List[float]:
        return pad_levels(self.ask_prices, BOOK_DEPTH, 0.0)

    @property
    def ask_volumes_top5(self) -> List[int]:
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


@dataclass
class BalanceUpdate:
    """Realtime account balance snapshot."""
    account_id: str
    broker: str
    available_balance: Optional[float] = None
    reserved_amount: Optional[float] = None
    dedicated_account_balance: Optional[float] = None
    cash: Optional[float] = None
    settlement: Optional[float] = None
    total_balance: Optional[float] = None
    currency: str = "TWD"
    time: datetime.datetime = field(default_factory=datetime.datetime.now)
    org_event: Any = None

    def __post_init__(self):
        self.available_balance = to_optional_float(self.available_balance)
        self.reserved_amount = to_optional_float(self.reserved_amount)
        self.dedicated_account_balance = to_optional_float(self.dedicated_account_balance)
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


# ── Callback type aliases ────────────────────────────────────────────

TickCallback = Callable[[Tick], None]
TradeCallback = Callable[[Tick], None]
BidAskCallback = Callable[[BidAsk], None]
OrderUpdateCallback = Callable[[OrderUpdate], None]
FillCallback = Callable[[Fill], None]
BalanceCallback = Callable[[BalanceUpdate], None]
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
        self._trade_callbacks: List[TradeCallback] = []
        self._bidask_callbacks: List[BidAskCallback] = []
        self._order_update_callbacks: List[OrderUpdateCallback] = []
        self._fill_callbacks: List[FillCallback] = []
        self._balance_callbacks: List[BalanceCallback] = []
        self._connection_callbacks: List[ConnectionCallback] = []
        self._realtime_connected = False
        self._balance_polling_thread: Optional[threading.Thread] = None
        self._balance_polling_stop = threading.Event()
        self._balance_polling_interval = 3.0
        self._balance_emit_on_change = True
        self._balance_last_snapshot: Optional[tuple] = None

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

    # Optional aliases for clearer API naming.
    def subscribe_trades(self, stock_ids: List[str]) -> None:
        """Alias for subscribe_ticks for brokers where tick == trade."""
        self.subscribe_ticks(stock_ids)

    def unsubscribe_trades(self, stock_ids: List[str]) -> None:
        """Alias for unsubscribe_ticks for brokers where tick == trade."""
        self.unsubscribe_ticks(stock_ids)

    def subscribe_balances(
        self,
        poll_interval: float = 3.0,
        emit_on_change: bool = True,
    ) -> None:
        """Start realtime balance stream via polling fallback."""
        if poll_interval <= 0:
            raise ValueError("poll_interval must be > 0")

        self._balance_polling_interval = poll_interval
        self._balance_emit_on_change = emit_on_change

        if (
            self._balance_polling_thread is not None
            and self._balance_polling_thread.is_alive()
        ):
            return

        self._balance_polling_stop.clear()
        self._balance_polling_thread = threading.Thread(
            target=self._balance_polling_loop,
            name=f"{self.__class__.__name__}BalancePolling",
            daemon=True,
        )
        self._balance_polling_thread.start()

    def unsubscribe_balances(self) -> None:
        """Stop realtime balance stream."""
        self._balance_polling_stop.set()
        thread = self._balance_polling_thread
        if (
            thread is not None
            and thread.is_alive()
            and threading.current_thread() is not thread
        ):
            thread.join(timeout=1.0)
        self._balance_polling_thread = None
        self._balance_last_snapshot = None

    def _balance_polling_loop(self) -> None:
        while not self._balance_polling_stop.is_set():
            try:
                update = self._fetch_balance_update()
                if update is not None:
                    current_snapshot = update.snapshot_key()
                    if (
                        not self._balance_emit_on_change
                        or current_snapshot != self._balance_last_snapshot
                    ):
                        self._balance_last_snapshot = current_snapshot
                        self._emit_balance(update)
            except Exception:
                logger.exception("Error while polling realtime balances")
            self._balance_polling_stop.wait(self._balance_polling_interval)

    def _safe_call_number(self, method_name: str) -> Optional[float]:
        method = getattr(self, method_name, None)
        if method is None or not callable(method):
            return None
        try:
            return to_optional_float(method())
        except Exception:
            logger.exception("Error calling %s for realtime balance", method_name)
            return None

    def _resolve_realtime_account_id(self) -> str:
        if hasattr(self, "target_account"):
            account_obj = getattr(self, "target_account")
            account_id = get_field_value(account_obj, "account")
            if account_id:
                return str(account_id)
        for attr in ("account", "user_account", "national_id"):
            value = getattr(self, attr, None)
            if value:
                return str(value)
        return ""

    def _fetch_balance_update(self) -> Optional[BalanceUpdate]:
        # Allow broker adapters to provide richer payload mapping.
        broker_mapper = getattr(self, "_get_realtime_balance", None)
        if callable(broker_mapper):
            custom = broker_mapper()
            if isinstance(custom, BalanceUpdate):
                return custom

        cash = self._safe_call_number("get_cash")
        settlement = self._safe_call_number("get_settlement")
        total_balance = self._safe_call_number("get_total_balance")
        if cash is None and settlement is None and total_balance is None:
            return None

        return BalanceUpdate(
            account_id=self._resolve_realtime_account_id(),
            broker=self.__class__.__name__,
            available_balance=cash,
            cash=cash,
            settlement=settlement,
            total_balance=total_balance,
            time=datetime.datetime.now(),
        )

    # ── Callback registration ────────────────────────────────

    def on_tick(self, callback: TickCallback) -> None:
        """Register a handler for tick events. Can be called multiple times."""
        self._tick_callbacks.append(callback)

    def on_trade(self, callback: TradeCallback) -> None:
        """Register a handler for trade events."""
        self._trade_callbacks.append(callback)

    def on_bidask(self, callback: BidAskCallback) -> None:
        """Register a handler for bid/ask events."""
        self._bidask_callbacks.append(callback)

    def on_order_update(self, callback: OrderUpdateCallback) -> None:
        """Register a handler for order status changes."""
        self._order_update_callbacks.append(callback)

    def on_fill(self, callback: FillCallback) -> None:
        """Register a handler for fill/deal executions."""
        self._fill_callbacks.append(callback)

    def on_balance(self, callback: BalanceCallback) -> None:
        """Register a handler for realtime account balances."""
        self._balance_callbacks.append(callback)

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
        if tick.source != "aggregate":
            for cb in self._trade_callbacks:
                try:
                    cb(tick)
                except Exception:
                    logger.exception("Error in trade callback")

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

    def _emit_balance(self, balance: BalanceUpdate):
        for cb in self._balance_callbacks:
            try:
                cb(balance)
            except Exception:
                logger.exception("Error in balance callback")

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
