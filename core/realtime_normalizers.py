"""Shared normalization helpers for realtime broker payloads."""

from typing import Any, List, Optional
import datetime
import math


BOOK_DEPTH = 5


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


def to_optional_datetime(
    value: Any,
    default_date: Optional[datetime.date] = None,
) -> Optional[datetime.datetime]:
    """Best-effort conversion for broker timestamps and HH:MM:SS strings."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time())

    if not isinstance(value, str):
        numeric = to_optional_float(value)
        if numeric is not None:
            timestamp = numeric
            magnitude = abs(numeric)
            if magnitude >= 10**17:
                timestamp = numeric / 1_000_000_000
            elif magnitude >= 10**14:
                timestamp = numeric / 1_000_000
            elif magnitude >= 10**11:
                timestamp = numeric / 1_000
            try:
                return datetime.datetime.fromtimestamp(timestamp)
            except (OSError, OverflowError, ValueError):
                return None

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        pass

    if default_date is not None:
        for fmt in ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M"):
            try:
                parsed_time = datetime.datetime.strptime(text, fmt).time()
                return datetime.datetime.combine(default_date, parsed_time)
            except ValueError:
                continue

    for fmt in (
        "%Y/%m/%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def normalize_time_filter(
    value: Any,
    field_name: str,
) -> Optional[datetime.time]:
    """Normalize backfill filter inputs to `datetime.time`."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.time()
    if isinstance(value, datetime.time):
        return value
    if isinstance(value, str):
        parsed = to_optional_datetime(value, default_date=datetime.date.today())
        if parsed is not None:
            return parsed.time()
    raise ValueError(
        f"{field_name} must be datetime.time, datetime, HH:MM[:SS[.ffffff]], or None"
    )


def normalize_backfill_window(
    start_time: Any = None,
    end_time: Any = None,
) -> tuple[Optional[datetime.time], Optional[datetime.time]]:
    """Normalize and validate same-day intraday backfill time filters."""
    start = normalize_time_filter(start_time, "start_time")
    end = normalize_time_filter(end_time, "end_time")
    if start is not None and end is not None and start > end:
        raise ValueError("start_time must be earlier than or equal to end_time")
    return start, end


def is_within_backfill_window(
    value: datetime.datetime,
    start_time: Optional[datetime.time] = None,
    end_time: Optional[datetime.time] = None,
) -> bool:
    """Return whether `value` falls inside the requested time window."""
    current = value.time()
    if start_time is not None and current < start_time:
        return False
    if end_time is not None and current > end_time:
        return False
    return True


def finalize_backfilled_ticks(ticks: List[Any]) -> List[Any]:
    """Sort backfilled ticks and repair missing cumulative volume values."""
    ordered = sorted(
        ticks,
        key=lambda tick: (tick.time, tick.total_volume, tick.volume, tick.price),
    )
    running_total = 0
    for tick in ordered:
        if tick.total_volume > 0:
            running_total = max(running_total, tick.total_volume)
        else:
            running_total += max(tick.volume, 0)
            tick.total_volume = running_total
    return ordered


__all__ = [
    "BOOK_DEPTH",
    "calculate_tick_pct_change",
    "finalize_backfilled_ticks",
    "get_field_value",
    "get_first_valid_float",
    "is_within_backfill_window",
    "normalize_backfill_window",
    "normalize_book_side",
    "normalize_time_filter",
    "pad_levels",
    "to_optional_datetime",
    "to_optional_float",
    "to_optional_int",
]
