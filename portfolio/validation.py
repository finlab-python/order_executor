"""Pure validation and computation helpers for portfolio sync management.

All functions in this module are side-effect-free: they take explicit inputs
and return explicit outputs (or raise explicit exceptions).  This enables
offline unit testing without broker connections, authentication, or market
data downloads.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from finlab.exceptions import PortfolioError

# ---------------------------------------------------------------------------
# Position field validation
# ---------------------------------------------------------------------------

_REQUIRED_STRING_FIELDS: tuple[str, ...] = (
    "timestamp",
    "next_trading_time",
    "entry_at",
    "exit_at",
)

_REQUIRED_NUMERIC_FIELDS: tuple[str, ...] = (
    "allocation",
    "weight",
)

_OPTIONAL_NUMERIC_FIELDS: tuple[str, ...] = (
    "stop_loss",
    "take_profit",
    "trail_stop",
)


def validate_position_fields(position_name: str, data: dict[str, Any]) -> list[str]:
    """Return a list of human-readable validation error strings.

    Each entry describes one field that violates its expected type.  An empty
    list means the position data is valid.

    Unlike the legacy ``position_type_check`` this function is *pure*: it
    never mutates *data* and never emits warnings.
    """
    errors: list[str] = [
        f"{position_name}: {field} must be a string, "
        f"got {type(data.get(field)).__name__}"
        for field in _REQUIRED_STRING_FIELDS
        if not isinstance(data.get(field), str)
    ]

    if not isinstance(data.get("position"), list):
        errors.append(
            f"{position_name}: position must be a list, "
            f"got {type(data.get('position')).__name__}"
        )

    errors.extend(
        f"{position_name}: {field} must be a float or int, "
        f"got {type(data.get(field)).__name__}"
        for field in _REQUIRED_NUMERIC_FIELDS
        if not isinstance(data.get(field), (float, int))
    )

    if not isinstance(data.get("stop"), list):
        errors.append(
            f"{position_name}: stop must be a list, "
            f"got {type(data.get('stop')).__name__}"
        )

    errors.extend(
        f"{position_name}: {field} must be a float or int, "
        f"got {type(data.get(field)).__name__}"
        for field in _OPTIONAL_NUMERIC_FIELDS
        if data.get(field) is not None and not isinstance(data.get(field), (float, int))
    )

    if not isinstance(data.get("market"), str) and data.get("market") is not None:
        errors.append(
            f"{position_name}: market must be a string or None, "
            f"got {type(data.get('market')).__name__}"
        )

    return errors


def check_position_needs_market_default(data: dict[str, Any]) -> bool:
    """Return True when *data* lacks a string ``market`` and has ``None``."""
    return not isinstance(data.get("market"), str) and data.get("market") is None


# ---------------------------------------------------------------------------
# Inf / NaN sanitisation
# ---------------------------------------------------------------------------


def replace_inf_nan(data: Any) -> Any:
    """Recursively replace ``inf`` and ``nan`` floats with ``None``.

    Works on arbitrarily nested combinations of *dict*, *list*, *tuple*,
    and *set*.
    """
    if isinstance(data, float):
        if math.isinf(data) or math.isnan(data):
            return None
        return data
    if isinstance(data, dict):
        return {k: replace_inf_nan(v) for k, v in data.items()}
    if isinstance(data, list):
        return [replace_inf_nan(item) for item in data]
    if isinstance(data, tuple):
        return tuple(replace_inf_nan(item) for item in data)
    if isinstance(data, set):
        return {replace_inf_nan(item) for item in data}
    return data


# ---------------------------------------------------------------------------
# Data payload normalisation
# ---------------------------------------------------------------------------


def normalize_data_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    """Return a deep copy of *data* with all required top-level keys present.

    If *data* is ``None`` an empty skeleton is returned.
    """
    if data is None:
        return {"position": {}, "history": {}, "market": None, "config": {}}

    payload = copy.deepcopy(data)
    payload.setdefault("position", {})
    payload.setdefault("history", {})
    payload.setdefault("config", {})
    return payload


# ---------------------------------------------------------------------------
# Rebalance fund computation
# ---------------------------------------------------------------------------

# One millionth of a currency unit: well below a cent, but above the
# representation noise from decimal prices such as 3 * 100.01. An absolute
# tolerance avoids forgiving larger shortfalls as portfolio value grows.
_REBALANCE_BALANCE_ABS_TOL = 1e-6


def validate_rebalance_balance(total_balance: float, asset_value: float) -> None:
    """Reject unfunded positive-weight rebuilds before any state is written.

    The caller must only invoke this when this update actually rebuilds a
    positive-weight sleeve. Equality and either side of floating-point noise
    are treated as no usable capital, rather than rebuilding an empty target.
    An explicitly zero budget with no retained assets keeps its old semantics.
    """
    if total_balance == asset_value == 0:
        return
    if total_balance - asset_value <= _REBALANCE_BALANCE_ABS_TOL:
        minimum_whole_balance = math.floor(asset_value + _REBALANCE_BALANCE_ABS_TOL) + 1
        raise PortfolioError(
            f"total_balance ({total_balance}) leaves no usable rebuild capital "
            f"after the existing holdings' market value in sleeves not being "
            f"updated ({asset_value}); absolute tolerance is "
            f"{_REBALANCE_BALANCE_ABS_TOL}. Increase total_balance to strictly "
            f"above {asset_value + _REBALANCE_BALANCE_ABS_TOL!r} "
            f"(at least {minimum_whole_balance} in whole currency units), "
            "and allow sufficient funding for target securities and the safety "
            "reserve; this lower bound alone does not guarantee a tradable lot. "
            "This update is aborted without state changes, sleeve removals, "
            "position rebuilds or any sleeve's stop-loss/take-profit processing. "
            "Correct total_balance and retry update() before saving or syncing."
        )


def validate_sleeve_weights(weights: dict[str, float]) -> None:
    """Reject negative weights on the sleeves being rebuilt.

    A negative sleeve weight would be allocated negative capital and push
    the other sleeves above the available funds.
    """
    negative = [f"{sid}: {weight:g}" for sid, weight in weights.items() if weight < 0]
    if negative:
        raise PortfolioError(
            f"Strategy weights must not be negative ({', '.join(negative)}). Set "
            "the weight to 0 or remove the strategy from the Portfolio, then "
            "retry update(). This update is aborted without state changes."
        )


def compute_rebalance_funds(
    total_balance: float,
    asset_value: float,
    total_update_weight: float,
    rebalance_safety_weight: float,
) -> dict[str, float]:
    """Compute fund allocation for a rebalance operation.

    Returns a dict with keys:
    - ``liquid_value``: capital freed by selling updated strategies
    - ``rebalance_safety_fund``: cash reserved as safety buffer
    - ``free_value``: capital actually available for new purchases
    """
    liquid_value = min(total_balance - asset_value, total_update_weight * total_balance)
    rebalance_safety_fund = liquid_value * rebalance_safety_weight
    cash = total_balance - asset_value - liquid_value
    free_value = max(liquid_value - max(0, rebalance_safety_fund - cash), 0)

    return {
        "liquid_value": liquid_value,
        "rebalance_safety_fund": rebalance_safety_fund,
        "free_value": free_value,
    }


# ---------------------------------------------------------------------------
# Position value computation
# ---------------------------------------------------------------------------


def compute_position_value(
    position: list[dict[str, Any]],
    lot: float,
    prices: dict[str, float],
    resolve_symbol: Any = None,
) -> float:
    """Compute the total monetary value of *position*.

    Parameters
    ----------
    position:
        List of position entry dicts, each having ``quantity`` and either
        ``symbol`` or ``stock_id``.
    lot:
        Lot multiplier (e.g. 1000 for TW stocks, 1 for odd-lot markets).
    prices:
        Mapping from symbol to latest price.
    resolve_symbol:
        Optional callable ``(dict) -> str`` to extract the symbol key from
        a position entry.  Defaults to ``lambda p: p.get('symbol') or p['stock_id']``.

    Returns
    -------
    float
        Sum of ``quantity * price * lot`` across all entries.

    Raises
    ------
    ValueError
        If a symbol is not found in *prices*.
    """
    if resolve_symbol is None:

        def resolve_symbol(p: dict[str, Any]) -> str:
            return p.get("symbol") or p["stock_id"]

    total = 0.0
    for p in position:
        sid = resolve_symbol(p)
        if sid not in prices:
            raise ValueError(f"stock {sid} not found")
        value = float(p["quantity"]) * float(prices[sid]) * lot
        if not math.isnan(value):
            total += value
    return total


# ---------------------------------------------------------------------------
# Margin / cash position adjustment
# ---------------------------------------------------------------------------

# OrderCondition integer values used by core.enums
_ORDER_CONDITION_CASH = 1
_ORDER_CONDITION_MARGIN_TRADING = 2


def merge_margin_cash_adjustments(
    diff_positions: list[dict[str, Any]],
    resolve_symbol: Any = None,
) -> list[dict[str, Any]]:
    """Cancel opposing cash / margin-trading quantities for the same symbol.

    Given a list of position-diff entries (each with ``order_condition`` and
    ``quantity``), this function reduces redundant cross-condition quantities.

    Parameters
    ----------
    diff_positions:
        Shallow-copied position entries from the diff between ideal and
        account positions.
    resolve_symbol:
        Optional callable ``(dict) -> str``.  Defaults to
        ``lambda p: p.get('symbol') or p['stock_id']``.

    Returns
    -------
    list[dict[str, Any]]
        Adjusted position entries with zero-quantity entries removed.
    """
    if resolve_symbol is None:

        def resolve_symbol(p: dict[str, Any]) -> str:
            return p.get("symbol") or p["stock_id"]

    cash: dict[str, dict[str, Any]] = {}
    margin: dict[str, dict[str, Any]] = {}

    for p in diff_positions:
        entry = p.copy()
        sid = resolve_symbol(entry)
        oc = entry.get("order_condition")
        if oc == _ORDER_CONDITION_CASH:
            cash[sid] = entry
        elif oc == _ORDER_CONDITION_MARGIN_TRADING:
            margin[sid] = entry

    sids = cash.keys() | margin.keys()
    for sid in sids:
        if sid not in cash or sid not in margin:
            continue

        if cash[sid]["quantity"] * margin[sid]["quantity"] < 0:
            reduce_amount = min(
                abs(cash[sid]["quantity"]), abs(margin[sid]["quantity"])
            )
            if cash[sid]["quantity"] > 0:
                cash[sid]["quantity"] -= reduce_amount
                margin[sid]["quantity"] += reduce_amount
            else:
                cash[sid]["quantity"] += reduce_amount
                margin[sid]["quantity"] -= reduce_amount

    return [
        p for p in list(cash.values()) + list(margin.values()) if p["quantity"] != 0
    ]


# ---------------------------------------------------------------------------
# Weight / position sanity checks
# ---------------------------------------------------------------------------


def validate_weights(weights: dict[str, float]) -> list[str]:
    """Validate a symbol-to-weight mapping for common issues.

    Returns a list of error strings (empty when valid).

    Checks performed:
    - No negative weights
    - Total weight does not exceed 1.0 (with a small tolerance of 1e-9)
    """
    errors: list[str] = []
    for symbol, w in weights.items():
        if w < 0:
            errors.append(f"{symbol}: weight {w} is negative")

    total = sum(weights.values())
    if total > 1.0 + 1e-9:
        errors.append(f"total weight {total:.6f} exceeds 1.0")

    return errors


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Scale *weights* so they sum to exactly 1.0.

    If all weights are zero (or the dict is empty), returns the input
    unchanged (no division by zero).
    """
    total = sum(weights.values())
    if total == 0:
        return dict(weights)
    return {k: v / total for k, v in weights.items()}
