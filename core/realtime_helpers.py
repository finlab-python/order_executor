"""Broker-facing helpers for intraday backfill and snapshot normalization."""

from __future__ import annotations

import datetime
from typing import Any

from .realtime_models import BidAsk, Tick
from .realtime_normalizers import (
    finalize_backfilled_ticks,
    get_field_value,
    get_first_valid_float,
    is_within_backfill_window,
    normalize_backfill_window,
    to_optional_datetime,
    to_optional_float,
    to_optional_int,
)


def build_ticks_from_intraday_trade_rows(
    stock_id: str,
    rows: list[Any],
    session_date: datetime.date | None = None,
    prev_close: Any = None,
    pct_change: Any = None,
    start_time: Any = None,
    end_time: Any = None,
) -> list[Tick]:
    """Normalize REST intraday trade rows into unified Tick objects."""
    session_date = session_date or datetime.date.today()
    start_filter, end_filter = normalize_backfill_window(start_time, end_time)
    prev_close_value = to_optional_float(prev_close)
    pct_change_value = to_optional_float(pct_change)
    seen_keys = set()
    ticks: list[Tick] = []

    for row in list(rows or []):
        trade_time = to_optional_datetime(
            get_field_value(row, "time"),
            default_date=session_date,
        )
        if trade_time is None or not is_within_backfill_window(
            trade_time,
            start_time=start_filter,
            end_time=end_filter,
        ):
            continue

        price = get_first_valid_float(
            row,
            "price",
            "close",
            "closePrice",
            "lastPrice",
        )
        if price is None:
            continue

        volume = to_optional_int(get_field_value(row, "size")) or 0
        total_volume = to_optional_int(get_field_value(row, "volume")) or 0
        serial = get_field_value(row, "serial")
        dedupe_key = (
            ("serial", serial)
            if serial not in (None, "")
            else ("trade", trade_time, price, volume, total_volume)
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        ticks.append(
            Tick(
                stock_id=stock_id,
                price=price,
                volume=volume,
                total_volume=total_volume,
                time=trade_time,
                prev_close=prev_close_value,
                pct_change=pct_change_value,
                source="trade",
            )
        )

    return finalize_backfilled_ticks(ticks)


def build_bidask_from_quote(
    stock_id: str,
    quote: Any,
    default_time: datetime.datetime | None = None,
) -> BidAsk:
    """Normalize a quote payload carrying bid/ask ladders into BidAsk."""
    bids = get_field_value(quote, "bids") or []
    asks = get_field_value(quote, "asks") or []
    quote_time = (
        to_optional_datetime(get_field_value(quote, "time"))
        or to_optional_datetime(get_field_value(quote, "lastUpdated"))
        or default_time
        or datetime.datetime.now()
    )
    return BidAsk(
        stock_id=stock_id,
        bid_prices=[get_field_value(level, "price") or 0.0 for level in bids],
        bid_volumes=[get_field_value(level, "size") or 0 for level in bids],
        ask_prices=[get_field_value(level, "price") or 0.0 for level in asks],
        ask_volumes=[get_field_value(level, "size") or 0 for level in asks],
        time=quote_time,
    )


__all__ = [
    "build_bidask_from_quote",
    "build_ticks_from_intraday_trade_rows",
]
