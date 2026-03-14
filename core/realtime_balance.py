"""Balance streaming mixin for realtime providers."""

from __future__ import annotations

import datetime
import logging
import threading
from collections.abc import Callable

from .realtime_models import BalanceUpdate
from .realtime_normalizers import get_field_value, to_optional_float

logger = logging.getLogger(__name__)

BalanceCallback = Callable[[BalanceUpdate], None]


class BalanceStreamMixin:
    """Polling-based balance stream fallback shared across brokers."""

    def _init_balance_stream(self) -> None:
        self._balance_callbacks: list[BalanceCallback] = []
        self._balance_polling_thread: threading.Thread | None = None
        self._balance_polling_stop = threading.Event()
        self._balance_polling_interval = 3.0
        self._balance_emit_on_change = True
        self._balance_last_snapshot: tuple | None = None

    def subscribe_balances(
        self,
        poll_interval: float = 3.0,
        emit_on_change: bool = True,
    ) -> None:
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

    def _safe_call_number(self, method_name: str) -> float | None:
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
            account_obj = self.target_account
            account_id = get_field_value(account_obj, "account")
            if account_id:
                return str(account_id)
        for attr in ("account", "user_account", "national_id"):
            value = getattr(self, attr, None)
            if value:
                return str(value)
        return ""

    def _fetch_balance_update(self) -> BalanceUpdate | None:
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

    def on_balance(self, callback: BalanceCallback) -> None:
        self._balance_callbacks.append(callback)

    def _emit_balance(self, balance: BalanceUpdate) -> None:
        for cb in self._balance_callbacks:
            try:
                cb(balance)
            except Exception:
                logger.exception("Error in balance callback")


__all__ = [
    "BalanceCallback",
    "BalanceStreamMixin",
]
