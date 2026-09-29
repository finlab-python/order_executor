from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

# Float bookkeeping (side budgets, first-round costs, second-round subtractions)
# puts the exact cost of an allocation within a few ulps of the fund per stock,
# around 1e-15 of it. Exceeding the fund by less than this share of it is that
# rounding, not money spent beyond the fund.
_ROUNDING_TOLERANCE = 1e-12


def greedy_allocation(
    weights: Mapping[str, float] | pd.Series,
    latest_prices: Mapping[str, float] | pd.Series,
    total_portfolio_value: float = 10000,
) -> tuple[dict[str, int], float]:
    """
    original source code: PyPortfolioOpt
    https://pypi.org/project/pyportfolioopt/

    Raises:
        ValueError: The absolute weights sum to more than 1 and the shares
            would cost more than ``total_portfolio_value``.
    """

    weights = pd.Series(weights)

    weights.index = weights.index.to_series().astype(str).str.split(" ").str[0]
    latest_prices = pd.Series(latest_prices)
    latest_prices.index = (
        latest_prices.index.to_series().astype(str).str.split(" ").str[0]
    )

    weights = weights.loc[weights.index.isin(latest_prices.index)]
    weights = weights.loc[
        latest_prices.loc[weights.index].replace([np.inf, -np.inf, 0], np.nan).notna()
    ]
    weights = list(weights.items())

    if len(weights) == 0:
        return {}, total_portfolio_value

    """
    Convert continuous weights into a discrete portfolio allocation
    using a greedy iterative approach.

    :param reinvest: whether or not to reinvest cash gained from shorting
    :type reinvest: bool, defaults to False
    :return: the number of shares of each ticker that should be purchased,
             along with the amount of funds leftover.
    :rtype: (dict, float)
    """
    # Sort in descending order of weight
    weights.sort(key=lambda x: x[1], reverse=True)

    if weights[-1][1] < 0:
        return _allocate_long_short(weights, latest_prices, total_portfolio_value)

    return _allocate_long_only(weights, latest_prices, total_portfolio_value)


def _allocate_long_only(
    weights: list[tuple[str, float]],
    latest_prices: pd.Series,
    total_portfolio_value: float,
) -> tuple[dict[str, int], float]:
    shares, costs = _buy_floor_shares(weights, latest_prices, total_portfolio_value)
    # As weights are all > 0 (long only) we always round down n_shares
    # so the cost is always <= simple weighted share of portfolio value,
    # so we can not run out of funds just here unless the weights sum to > 1.
    available_funds = _remaining_funds(total_portfolio_value, costs)
    if available_funds < 0:
        raise _insufficient_funds(weights)

    shares, available_funds = _top_up(weights, latest_prices, shares, available_funds)
    tickers = [ticker for ticker, _ in weights]
    return dict(zip(tickers, shares, strict=True)), available_funds


def _allocate_long_short(
    weights: list[tuple[str, float]],
    latest_prices: pd.Series,
    total_portfolio_value: float,
) -> tuple[dict[str, int], float]:
    """Allocate each side like a long-only book of its own.

    A side's weights are re-normalised to sum to 1 and its budget is
    ``total_portfolio_value * side_weight``, so a side spends its budget at
    most, up to float rounding. That rounding can put a side's first round a
    few ulps over its budget (finlab#230), so no side checks its own budget.
    The budgets add up to more than the fund only when the absolute weights
    sum to more than 1, and only then is the allocation checked against the
    whole fund.
    """
    allocation: dict[str, int] = {}
    leftovers = []
    for sign, side in (
        (1, {t: w for t, w in weights if w > 0}),
        (-1, {t: -w for t, w in weights if w < 0}),
    ):
        side_total_weight = sum(side.values())
        side_weights = [(t, w / side_total_weight) for t, w in side.items()]
        side_weights.sort(key=lambda x: x[1], reverse=True)
        budget = total_portfolio_value * side_total_weight
        shares, costs = _buy_floor_shares(side_weights, latest_prices, budget)
        shares, side_leftover = _top_up(
            side_weights, latest_prices, shares, _remaining_funds(budget, costs)
        )
        allocation.update(
            {t: sign * n for (t, _), n in zip(side_weights, shares, strict=True)}
        )
        leftovers.append(side_leftover)

    allocation = {t: n for t, n in allocation.items() if n != 0}
    if math.fsum(abs(w) for _, w in weights) > 1 and _exceeds_fund(
        allocation, latest_prices, total_portfolio_value
    ):
        raise _insufficient_funds(weights)

    long_leftover, short_leftover = leftovers
    return allocation, long_leftover + short_leftover


def _buy_floor_shares(
    weights: list[tuple[str, float]],
    latest_prices: pd.Series,
    total_portfolio_value: float,
) -> tuple[list[int], list[float]]:
    """First round: the lower integer number of shares of each asset (maybe zero)."""
    shares = []
    costs = []
    for ticker, weight in weights:
        price = latest_prices[ticker]
        n_shares = int(weight * total_portfolio_value / price)
        shares.append(n_shares)
        costs.append(n_shares * price)
    return shares, costs


def _exceeds_fund(
    allocation: dict[str, int],
    latest_prices: pd.Series,
    total_portfolio_value: float,
) -> bool:
    cost = math.fsum(abs(n) * latest_prices[t] for t, n in allocation.items())
    return cost > total_portfolio_value * (1 + _ROUNDING_TOLERANCE)


def _remaining_funds(funds: float, costs: list[float]) -> float:
    for cost in costs:
        funds -= cost
    return funds


def _insufficient_funds(weights: list[tuple[str, float]]) -> ValueError:
    total_weight = sum(abs(w) for _, w in weights)
    return ValueError(
        f"Insufficient funds: weights sum to {total_weight:.6g}, which exceeds 1. "
        "Scale the weights so that their total is at most 1."
    )


def _top_up(
    weights: list[tuple[str, float]],
    latest_prices: pd.Series,
    shares: list[int],
    available_funds: float,
) -> tuple[list[int], float]:
    """Second round: buy one share at a time of the most under-weighted asset."""
    shares_bought = list(shares)
    buy_prices = [latest_prices[ticker] for ticker, _ in weights]

    while available_funds > 0:
        # Calculate the equivalent continuous weights of the shares that
        # have already been bought
        current_weights = np.array(buy_prices) * np.array(shares_bought)
        wsum = current_weights.sum()
        if wsum != 0:
            current_weights = current_weights / wsum
        ideal_weights = np.array([i[1] for i in weights])
        deficit = ideal_weights - current_weights

        # Attempt to buy the asset whose current weights deviate the most
        idx = np.argmax(deficit)
        ticker, _ = weights[idx]
        price = latest_prices[ticker]

        # If we can't afford this asset, search for the next highest deficit that we
        # can purchase.
        counter = 0
        while price > available_funds:
            deficit[idx] = 0  # we can no longer purchase the asset at idx
            idx = np.argmax(deficit)  # find the next most deviant asset

            # If either of these conditions is met, we break out of both while loops
            # hence the repeated statement below
            if deficit[idx] < 0 or counter == 10:
                break

            ticker, _ = weights[idx]
            price = latest_prices[ticker]
            counter += 1

        if deficit[idx] <= 0 or counter == 10:  # pragma: no cover
            # Dirty solution to break out of both loops
            break

        # Buy one share at a time
        shares_bought[idx] += 1
        available_funds -= price

    return shares_bought, available_funds


def _round_to_tick(price: float, direction: str = "floor") -> float:
    """Round price to Taiwan tick boundary.

    Tick-size tiers: 0.01 (<=10), 0.05 (<=50), 0.1 (<=100),
    0.5 (<=500), 1 (<=1000), 5 (>1000).

    Args:
        price: The price to round.
        direction: "floor" to round down, "ceil" to round up.
    """
    fn = math.floor if direction == "floor" else math.ceil
    if price <= 10:
        return fn(round(price, 3) * 100) / 100
    elif price <= 50:
        return fn(price * 20) / 20
    elif price <= 100:
        return fn(price * 10) / 10
    elif price <= 500:
        return fn(price * 2) / 2
    elif price <= 1000:
        return fn(price)
    else:
        return fn(price / 5) * 5


def round_tw_price(price: float) -> float:
    """Round tw price to the nearest tick size. Asserts the price is already
    on a tick boundary (floor == ceil)."""
    result = _round_to_tick(price, "floor")
    result2 = _round_to_tick(price, "ceil")
    assert result == result2
    return result


def estimate_stock_price(cost_per_quantity: float) -> float:

    stock_price_org = cost_per_quantity / (1 + 1.425 / 1000) / 1000
    stock_price_2 = (cost_per_quantity + 1) / (1 + 1.425 / 1000) / 1000

    c1 = round_tw_price(stock_price_org)
    c2 = round_tw_price(stock_price_2)

    if abs(stock_price_org - c1) > abs(stock_price_org - c2):
        return c2
    return c1
