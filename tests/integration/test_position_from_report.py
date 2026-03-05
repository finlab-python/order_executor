"""Integration tests for Position.from_report workflow."""

import os

import pytest

from finlab import auth, data
from finlab.online.order_executor import Position

sim = pytest.importorskip(
    "finlab.backtest",
    reason="finlab.backtest dependencies are unavailable in this environment",
    exc_type=ImportError,
).sim

pytestmark = [pytest.mark.slow]

_HAS_AUTH = bool(os.environ.get("FINLAB_API_TOKEN")) or auth.get_session() is not None
if not _HAS_AUTH:
    pytestmark.append(
        pytest.mark.skip(reason="FinLab auth session/token is required for data.get/backtest integration tests")
    )


def _check_action_and_position(report):
    report.actions.index = report.actions.index.map(lambda x: x[:4])
    _ = Position.from_report(report, 50000, odd_lot=True).position

    close = data.get("price:收盤價").iloc[-1].to_dict()
    position = Position.from_report(report, 50000, odd_lot=True, price=close).position

    check_sl_tp = report.actions.isin(["sl_", "tp_", "sl", "tp"])
    for p in position:
        assert p["stock_id"] not in check_sl_tp[check_sl_tp].index


def test_strategy1_from_report():
    close = data.get("price:收盤價")
    vol = data.get("price:成交股數")
    vol_ma = vol.average(10)
    rev = data.get("monthly_revenue:當月營收")
    rev_year_growth = data.get("monthly_revenue:去年同月增減(%)")
    rev_month_growth = data.get("monthly_revenue:上月比較增減(%)")

    cond1 = close == close.rolling(250).max()
    cond2 = ~(rev_year_growth < -10).sustain(3)
    cond3 = ~(rev_year_growth > 60).sustain(12, 8)
    cond4 = (rev.rolling(12).min() / rev < 0.8).sustain(3)
    cond5 = (rev_month_growth > -40).sustain(3)
    cond6 = vol_ma > 200 * 1000

    buy = cond1 & cond2 & cond3 & cond4 & cond5 & cond6
    buy = vol_ma * buy
    buy = buy[buy > 0]
    buy = buy.is_smallest(5)

    report = sim(
        buy,
        resample="M",
        upload=False,
        position_limit=1 / 3,
        fee_ratio=1.425 / 1000 / 3,
        stop_loss=0.08,
        trade_at_price="open",
        name="藏獒",
    )
    _check_action_and_position(report)


def test_strategy2_from_report():
    close = data.get("price:收盤價")
    vol = data.get("price:成交股數")
    rev = data.get("monthly_revenue:當月營收")
    rev_yoy_growth = data.get("monthly_revenue:去年同月增減(%)")
    rev_ma = rev.average(2)

    condition1 = rev_ma == rev_ma.rolling(12, min_periods=6).max()
    condition2 = (close == close.rolling(200).max()).sustain(5, 2)
    condition3 = vol.average(5) > 500 * 1000

    conditions = condition1 & condition2 & condition3
    position = rev_yoy_growth * conditions
    position = position[position > 0].is_largest(10).reindex(
        rev.index_str_to_date().index,
        method="ffill",
    )

    report = sim(
        position,
        upload=False,
        stop_loss=0.2,
        take_profit=0.8,
        position_limit=0.25,
        fee_ratio=1.425 / 1000 * 0.3,
        name="營收股價雙渦輪",
    )
    _check_action_and_position(report)
