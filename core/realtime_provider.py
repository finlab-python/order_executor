"""Realtime provider base class and callback orchestration."""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List
import logging

from .realtime_models import (
    BidAsk,
    ConnectionState,
    Fill,
    OrderUpdate,
    Tick,
)
from .realtime_balance import BalanceCallback, BalanceStreamMixin

logger = logging.getLogger(__name__)

TickCallback = Callable[[Tick], None]
TradeCallback = Callable[[Tick], None]
BidAskCallback = Callable[[BidAsk], None]
OrderUpdateCallback = Callable[[OrderUpdate], None]
FillCallback = Callable[[Fill], None]
ConnectionCallback = Callable[[ConnectionState, str], None]


class RealtimeProvider(BalanceStreamMixin, ABC):
    """Abstract base for realtime market data, order events, and connection state."""

    def _init_realtime(self):
        """Call from subclass __init__ to initialize realtime state."""
        self._tick_callbacks: List[TickCallback] = []
        self._trade_callbacks: List[TradeCallback] = []
        self._bidask_callbacks: List[BidAskCallback] = []
        self._order_update_callbacks: List[OrderUpdateCallback] = []
        self._fill_callbacks: List[FillCallback] = []
        self._connection_callbacks: List[ConnectionCallback] = []
        self._realtime_connected = False
        self._init_balance_stream()

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

    def subscribe_trades(self, stock_ids: List[str]) -> None:
        self.subscribe_ticks(stock_ids)

    def unsubscribe_trades(self, stock_ids: List[str]) -> None:
        self.unsubscribe_ticks(stock_ids)

    def backfill_ticks(
        self,
        stock_ids: List[str],
        start_time: Any = None,
        end_time: Any = None,
        emit: bool = True,
    ) -> Dict[str, List[Tick]]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support intraday tick backfill"
        )

    def subscribe_ticks_with_backfill(
        self,
        stock_ids: List[str],
        start_time: Any = None,
        end_time: Any = None,
        emit: bool = True,
    ) -> Dict[str, List[Tick]]:
        backfilled = self.backfill_ticks(
            stock_ids,
            start_time=start_time,
            end_time=end_time,
            emit=emit,
        )
        self.subscribe_ticks(stock_ids)
        return backfilled

    def get_bidask_snapshot(
        self,
        stock_ids: List[str],
        emit: bool = True,
    ) -> Dict[str, BidAsk]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support bidask snapshot"
        )

    def subscribe_bidask_with_snapshot(
        self,
        stock_ids: List[str],
        emit: bool = True,
    ) -> Dict[str, BidAsk]:
        snapshots = self.get_bidask_snapshot(stock_ids, emit=emit)
        self.subscribe_bidask(stock_ids)
        return snapshots

    def on_tick(self, callback: TickCallback) -> None:
        self._tick_callbacks.append(callback)

    def on_trade(self, callback: TradeCallback) -> None:
        self._trade_callbacks.append(callback)

    def on_bidask(self, callback: BidAskCallback) -> None:
        self._bidask_callbacks.append(callback)

    def on_order_update(self, callback: OrderUpdateCallback) -> None:
        self._order_update_callbacks.append(callback)

    def on_fill(self, callback: FillCallback) -> None:
        self._fill_callbacks.append(callback)

    def on_connection(self, callback: ConnectionCallback) -> None:
        self._connection_callbacks.append(callback)

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

    def _emit_connection(self, state: ConnectionState, message: str = ""):
        for cb in self._connection_callbacks:
            try:
                cb(state, message)
            except Exception:
                logger.exception("Error in connection callback")

    @abstractmethod
    def connect_realtime(self) -> None:
        """Initialize websocket/streaming connections and wire broker callbacks."""
        ...

    @abstractmethod
    def disconnect_realtime(self) -> None:
        """Tear down all streaming connections and clear subscriptions."""
        ...


__all__ = [
    "BalanceCallback",
    "BidAskCallback",
    "ConnectionCallback",
    "FillCallback",
    "OrderUpdateCallback",
    "RealtimeProvider",
    "TickCallback",
    "TradeCallback",
]
