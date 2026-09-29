"""greedy_allocation with short weights (finlab-python/finlab#230).

When a portfolio holds shorts, each side is re-normalised to sum to 1 and
given ``fund * side_weight``. Float rounding in those two steps used to make
the side's first round overshoot its budget by a few ulps and raise
"Insufficient funds" although the weights sum to less than 1.

Whatever the weights, an allocation that does not raise costs at most the
fund, up to float rounding in the allocator's bookkeeping.
"""

from __future__ import annotations

import collections
import math
import random
from decimal import Decimal
from fractions import Fraction

import pytest

from finlab.online.core.position import Position
from finlab.online.core.utils import _ROUNDING_TOLERANCE, greedy_allocation

pytestmark = pytest.mark.unit

FUND = 100_000
PRICE = 48.0
INSUFFICIENT = "exceeds 1"


def _prices(weights: dict[str, float], price: float = PRICE) -> dict[str, float]:
    return dict.fromkeys(weights, price)


def _mirror(weights: dict[str, float]) -> dict[str, float]:
    return {symbol: -weight for symbol, weight in weights.items()}


def _held(allocation: dict[str, int]) -> dict[str, int]:
    return {symbol: shares for symbol, shares in allocation.items() if shares}


def _assert_within_fund(
    allocation: dict[str, int], prices: dict[str, float], fund: float
) -> None:
    """The exact cost of the shares exceeds the fund by float rounding at most."""
    cost = sum(Fraction(abs(n)) * Fraction(prices[s]) for s, n in allocation.items())
    allowance = Fraction(fund) * Fraction(_ROUNDING_TOLERANCE)
    assert cost - Fraction(fund) <= allowance, (allocation, prices, fund)


@pytest.mark.parametrize(
    ("weights", "expected"),
    [
        (
            {"1101": -0.3, "1102": -0.3, "1103": -0.3},
            {"1101": -625, "1102": -625, "1103": -625},
        ),
        (
            {"1101": 0.3, "1102": 0.3, "1103": 0.3, "2330": -0.1},
            {"1101": 625, "1102": 625, "1103": 625, "2330": -208},
        ),
        (
            {"2330": 0.1, "1101": -0.3, "1102": -0.3, "1103": -0.3},
            {"2330": 208, "1101": -625, "1102": -625, "1103": -625},
        ),
    ],
    ids=["short_only", "long_side_of_long_short", "short_side_of_long_short"],
)
def test_side_weights_summing_just_below_one_are_allocated(weights, expected):
    allocation, _ = greedy_allocation(weights, _prices(weights), FUND)

    assert allocation == expected


def test_position_from_weight_short_selling_just_below_one():
    weights = {"1101": -0.3, "1102": -0.3, "1103": -0.3}

    position = Position.from_weight(
        weights, FUND, price=_prices(weights), odd_lot=True, short_selling=True
    )

    quantities = {p["symbol"]: Decimal(p["quantity"]) for p in position.to_list()}
    assert quantities == dict.fromkeys(weights, Decimal("-0.625"))


# Short-only inputs that raised "Insufficient funds" before the fix
# (order_executor 497b57b), found by random search.
PREVIOUSLY_FAILING_SHORTS = [
    ({"A": -0.3, "B": -0.3, "C": -0.3}, dict.fromkeys("ABC", PRICE), FUND),
    ({"A": -0.35, "B": -0.3}, {"A": 100.0, "B": 10.0}, 100_000),
    ({"A": -0.3, "B": -0.35}, {"A": 10.0, "B": 10.0}, 3_000_000),
    ({"A": -0.3, "B": -0.3, "C": -0.3}, {"A": 100.0, "B": 48.0, "C": 100.0}, 100_000),
    ({"A": -0.3, "B": -0.3, "C": -0.3}, {"A": 600.0, "B": 100.0, "C": 48.0}, 100_000),
    (
        dict.fromkeys("ABCDE", -0.18),
        {"A": 48.0, "B": 600.0, "C": 100.0, "D": 100.0, "E": 100.0},
        1_000_000,
    ),
    (
        dict.fromkeys("ABCDEF", -0.15),
        {"A": 600.0, "B": 48.0, "C": 10.0, "D": 48.0, "E": 48.0, "F": 600.0},
        1_000_000,
    ),
]


@pytest.mark.parametrize(("weights", "prices", "fund"), PREVIOUSLY_FAILING_SHORTS)
def test_previously_failing_shorts_get_the_long_mirror_shares(weights, prices, fund):
    short_allocation, _ = greedy_allocation(weights, prices, fund)
    long_allocation, _ = greedy_allocation(_mirror(weights), prices, fund)

    assert _mirror(short_allocation) == _held(long_allocation)


SIDES = ("long", "short", "long_short")
SEEDS = range(5)
CASES_PER_SEED = 200
# Exact totals are drawn with integer prices only: an order that spends the
# fund exactly can cost a few ulps more than the fund at a price that binary
# floats cannot represent (e.g. 9.1), and the funds check stays strict
# (finlab-python/finlab#234). 0.3 * 3 is the float sum of three 0.3 weights.
EXACT_TOTALS = (1.0, 0.9, 0.3 * 3)
TICKS = ((10, 0.01), (50, 0.05), (100, 0.1), (500, 0.5), (1000, 1), (math.inf, 5))
BOARD_LOT = 1000
# Round prices and funds divide evenly, which is where the float boundary sits.
ROUND_PRICES = (10, 20, 25, 40, 48, 50, 60, 75, 80, 100, 120, 150, 200, 250, 300, 600)
ROUND_FUNDS = (100_000, 300_000, 1_000_000, 3_000_000)
DECIMAL_WEIGHTS = (0.05, 0.1, 0.15, 0.2, 0.3, 1 / 3)
OVER_ALLOCATION = (1.0001, 2.0)


def _tw_price(rng: random.Random) -> float:
    price = rng.uniform(5, 1500)
    tick = next(tick for upper, tick in TICKS if price <= upper)
    return round(round(price / tick) * tick, 2)


def _price(rng: random.Random, exact_prices: bool) -> float:
    if rng.random() < 0.5:
        return float(rng.choice(ROUND_PRICES))
    if exact_prices:
        return float(round(_tw_price(rng) * BOARD_LOT))
    return _tw_price(rng)


def _magnitudes(rng: random.Random, n: int, total: float) -> list[float]:
    kind = rng.choice(("equal", "capped", "decimal", "random"))
    if kind == "equal":
        return [total / n] * n
    if kind == "capped":
        return [min(total / n, rng.choice(DECIMAL_WEIGHTS))] * n
    if kind == "decimal":
        weights: list[float] = []
        for weight in (rng.choice(DECIMAL_WEIGHTS) for _ in range(n)):
            if math.fsum((*weights, weight)) <= total:
                weights.append(weight)
        return weights or [total]
    raw = [rng.random() + 1e-3 for _ in range(n)]
    return [r / sum(raw) * total for r in raw]


def _signs(rng: random.Random, side: str, n: int) -> list[int]:
    if side == "long":
        return [1] * n
    if side == "short" or n == 1:
        return [-1] * n
    signs = [rng.choice((1, -1)) for _ in range(n)]
    if len(set(signs)) == 1:
        signs[0] = -signs[0]
    return signs


def _random_case(
    rng: random.Random, side: str, total: float, exact_prices: bool
) -> tuple[dict[str, float], dict[str, float], int]:
    magnitudes = _magnitudes(rng, rng.randint(1, 12), total)
    n = len(magnitudes)
    symbols = [f"S{i:02d}" for i in range(n)]
    weights = {
        s: sign * w
        for s, sign, w in zip(symbols, _signs(rng, side, n), magnitudes, strict=True)
    }
    shared_price = _price(rng, exact_prices) if rng.random() < 0.3 else None
    prices = {s: shared_price or _price(rng, exact_prices) for s in symbols}
    fund = rng.choice((*ROUND_FUNDS, rng.randint(10_000, 10_000_000)))
    return weights, prices, fund * rng.choice((1, BOARD_LOT))


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("side", SIDES)
def test_weights_summing_to_at_most_one_allocate_within_the_fund(side, seed):
    rng = random.Random(f"{side}-{seed}")
    for _ in range(CASES_PER_SEED):
        exact_prices = rng.random() < 0.5
        total = (
            rng.choice(EXACT_TOTALS)
            if exact_prices
            else rng.choice((1 - 1e-12, 0.99, rng.uniform(0.05, 0.99)))
        )
        weights, prices, fund = _random_case(rng, side, total, exact_prices)

        allocation, _ = greedy_allocation(weights, prices, fund)

        _assert_within_fund(allocation, prices, fund)
        assert all(
            (shares > 0) == (weights[s] > 0) for s, shares in _held(allocation).items()
        ), (weights, allocation)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("side", SIDES)
def test_weights_summing_to_more_than_one_raise_or_stay_within_the_fund(side, seed):
    rng = random.Random(f"over-{side}-{seed}")
    outcomes: collections.Counter[str] = collections.Counter()
    for _ in range(CASES_PER_SEED):
        weights, prices, fund = _random_case(
            rng, side, rng.uniform(*OVER_ALLOCATION), rng.random() < 0.5
        )
        if math.fsum(abs(w) for w in weights.values()) <= 1:
            continue  # capped weights can stay below the drawn total

        try:
            allocation, _ = greedy_allocation(weights, prices, fund)
        except ValueError as error:
            assert INSUFFICIENT in str(error)
            outcomes["raised"] += 1
            continue

        _assert_within_fund(allocation, prices, fund)
        outcomes["allocated"] += 1

    # Both outcomes occur, so neither assertion above is vacuous.
    assert outcomes["raised"] and outcomes["allocated"], outcomes


# Red team A, round 1: the first round fits in the fund, but each side's second
# round spent up to its own budget, and with weights over 1 the budgets add up
# to more than the fund (costs 1,200 against a fund of 1,000).
@pytest.mark.parametrize(
    ("weights", "price"),
    [
        ({"A": 0.35, "B": 0.25, "C": -0.35, "D": -0.25}, 200.0),
        ({"C": -0.7, "D": -0.5}, 200.0),
        ({"A": -0.1, "B": -1.1}, 600.0),
    ],
    ids=["long_short", "short_only", "smallest_short_only"],
)
def test_second_round_past_the_fund_raises(weights, price):
    with pytest.raises(ValueError, match=INSUFFICIENT):
        greedy_allocation(weights, _prices(weights, price), 1_000)


# Weights over 1 whose shares still fit in the fund keep the allocation and
# leftover they had before the fix (order_executor 497b57b), like long-only
# weights over 1 do.
@pytest.mark.parametrize(
    ("weights", "price", "expected"),
    [
        ({"A": -0.6, "B": -0.6}, 700.0, ({"A": -1}, 500.0)),
        (
            {"A": 0.7, "B": 0.2, "C": -0.3},
            300.0,
            ({"A": 2, "C": -1}, 299.9999999999999),
        ),
    ],
    ids=["short_only", "long_short"],
)
def test_weights_over_one_that_fit_the_fund_are_allocated(weights, price, expected):
    assert greedy_allocation(weights, _prices(weights, price), 1_000) == expected


def test_side_budgets_rounding_over_the_fund_are_allocated():
    """Red team A MINOR-1: weights summing to exactly 1 whose two float budgets
    add up to a few ulps more than the fund, each spent in full."""
    weights = {"L": 0.9, "S": -(1 - 0.9)}
    prices = {"L": 260869579.20000002, "S": 28985508.799999993}

    assert greedy_allocation(weights, prices, 289_855_088) == ({"L": 1, "S": -1}, 0)


def test_rounding_past_the_fund_is_not_an_overspend():
    """Weights one ulp over 1 whose budgets are spent in full cost 2e-13 more
    than the fund. That is float rounding, so they keep the allocation they
    had before the fix instead of raising."""
    weights = {"L": 0.5000000000000002, "S": -0.5}
    prices = {"L": 1_000 * 0.5000000000000002, "S": 500.0}

    assert greedy_allocation(weights, prices, 1_000) == ({"L": 1, "S": -1}, 0)


@pytest.mark.parametrize(
    ("weights", "expected"),
    [
        ({"A": 0.6, "B": -0.4}, {"A": 600, "B": -400}),
        ({"A": -0.6, "B": -0.4}, {"A": -600, "B": -400}),
    ],
    ids=["long_short", "short_only"],
)
def test_weights_spending_the_whole_fund_are_allocated(weights, expected):
    allocation, leftover = greedy_allocation(weights, _prices(weights, 1.0), 1_000)

    assert (allocation, leftover) == (expected, 0)


@pytest.mark.parametrize(
    "weights",
    [{"A": 0.6, "B": -0.401}, {"A": -0.6, "B": -0.401}],
    ids=["long_short", "short_only"],
)
def test_weights_one_share_over_the_fund_raise(weights):
    with pytest.raises(ValueError, match=INSUFFICIENT):
        greedy_allocation(weights, _prices(weights, 1.0), 1_000)
