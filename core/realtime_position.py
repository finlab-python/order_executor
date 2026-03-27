"""Position streaming mixin for realtime providers.

Hybrid approach: seeds from get_position(), applies Fill deltas for
immediate updates, and periodically reconciles via get_position().
"""

from __future__ import annotations

import datetime
import logging
import threading
from collections.abc import Callable
from typing import Any

from .enums import Action, OrderCondition
from .realtime_models import Fill, PositionUpdate

logger = logging.getLogger(__name__)

PositionCallback = Callable[[PositionUpdate], None]


def _apply_fill_to_position(position: Any, fill: Fill) -> Any:
    """Return a new Position with the fill quantity applied.

    BUY fills increase the holding; SELL fills decrease it.
    Falls back to OrderCondition.CASH when the originating order
    condition is unknown.
    """
    from .position import Position, _make_entry

    entries: list[dict[str, Any]] = [e.copy() for e in position.position]

    delta = fill.quantity
    if fill.action == Action.SELL:
        delta = -delta

    oc = OrderCondition.CASH
    # Try to resolve order_condition from order context
    if hasattr(fill, "order_condition") and fill.order_condition is not None:
        oc = fill.order_condition

    # Find existing entry with matching stock_id + order_condition
    matched = False
    for entry in entries:
        sid = entry.get("stock_id") or entry.get("symbol", "")
        if sid == fill.stock_id and entry.get("order_condition") == oc:
            entry["quantity"] = entry["quantity"] + delta
            matched = True
            break

    if not matched:
        if delta != 0:
            entries.append(_make_entry(fill.stock_id, delta, oc))

    # Remove zero-quantity entries
    entries = [e for e in entries if e.get("quantity", 0) != 0]

    return Position.from_list(entries)


class PositionStreamMixin:
    """Hybrid position stream: fill-driven deltas + periodic polling reconciliation."""

    def _init_position_stream(self) -> None:
        self._position_callbacks: list[PositionCallback] = []
        self._position_polling_thread: threading.Thread | None = None
        self._position_polling_stop = threading.Event()
        self._position_polling_interval = 30.0
        self._position_last_snapshot: tuple | None = None
        self._position_current: Any | None = None  # Current Position object
        self._position_lock = threading.Lock()
        self._position_fill_wired = False

    def subscribe_positions(
        self,
        poll_interval: float = 30.0,
    ) -> None:
        """Start position streaming with hybrid fill + polling updates.

        Args:
            poll_interval: Seconds between reconciliation polls (default 30s
                to respect broker rate limits like Fugle's 10s throttle).
        """
        if poll_interval <= 0:
            raise ValueError("poll_interval must be > 0")

        self._position_polling_interval = poll_interval

        # Seed initial position
        self._position_reconcile(source="poll")

        # Wire fill-driven updates (once)
        if not self._position_fill_wired:
            on_fill = getattr(self, "on_fill", None)
            if callable(on_fill):
                on_fill(self._on_fill_position_update)
                self._position_fill_wired = True

        # Start reconciliation polling thread
        if (
            self._position_polling_thread is not None
            and self._position_polling_thread.is_alive()
        ):
            return

        self._position_polling_stop.clear()
        self._position_polling_thread = threading.Thread(
            target=self._position_polling_loop,
            name=f"{self.__class__.__name__}PositionPolling",
            daemon=True,
        )
        self._position_polling_thread.start()

    def unsubscribe_positions(self) -> None:
        """Stop position streaming and clean up."""
        self._position_polling_stop.set()
        thread = self._position_polling_thread
        if (
            thread is not None
            and thread.is_alive()
            and threading.current_thread() is not thread
        ):
            thread.join(timeout=2.0)
        self._position_polling_thread = None
        with self._position_lock:
            self._position_last_snapshot = None
            self._position_current = None

    def _position_polling_loop(self) -> None:
        while not self._position_polling_stop.is_set():
            self._position_polling_stop.wait(self._position_polling_interval)
            if self._position_polling_stop.is_set():
                break
            try:
                self._position_reconcile(source="poll")
            except Exception:
                logger.exception("Error while polling realtime positions")

    def _position_reconcile(self, source: str = "poll") -> None:
        """Fetch position from broker and emit if changed."""
        get_position = getattr(self, "get_position", None)
        if not callable(get_position):
            return

        position = get_position()
        if position is None:
            return

        update = PositionUpdate(
            account_id=self._resolve_realtime_account_id(),
            broker=self.__class__.__name__,
            position=position,
            time=datetime.datetime.now(),
            source=source,
        )

        with self._position_lock:
            current_key = update.snapshot_key()
            if current_key != self._position_last_snapshot:
                self._position_last_snapshot = current_key
                self._position_current = position
                self._emit_position(update)

    def _on_fill_position_update(self, fill: Fill) -> None:
        """Apply a fill event as an immediate position delta."""
        with self._position_lock:
            if self._position_current is None:
                return

            new_position = _apply_fill_to_position(self._position_current, fill)

            update = PositionUpdate(
                account_id=self._resolve_realtime_account_id(),
                broker=self.__class__.__name__,
                position=new_position,
                time=datetime.datetime.now(),
                source="fill",
            )

            current_key = update.snapshot_key()
            if current_key != self._position_last_snapshot:
                self._position_last_snapshot = current_key
                self._position_current = new_position
                self._emit_position(update)

    def on_position(self, callback: PositionCallback) -> None:
        self._position_callbacks.append(callback)

    def _emit_position(self, update: PositionUpdate) -> None:
        for cb in self._position_callbacks:
            try:
                cb(update)
            except Exception:
                logger.exception("Error in position callback")


__all__ = [
    "PositionCallback",
    "PositionStreamMixin",
]
