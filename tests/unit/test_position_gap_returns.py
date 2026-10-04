import pandas as pd
import pytest

from finlab.dataframe import FinlabDataFrame
from finlab.online.enums import OrderCondition
from finlab.online.order_executor import Position


@pytest.mark.parametrize("frame", [pd.DataFrame, FinlabDataFrame])
def test_margin_allocation_retains_gap_return(frame):
    history = frame(
        {
            "A": [float("nan"), 100, float("nan"), float("nan"), 200, 202, 204],
            "B": [100, 110, 100, 110, 100, 110, 100],
        },
        index=pd.date_range("2026-01-01", periods=7),
    )
    original = history.copy()

    def allocate(prices):
        return Position.from_weight(
            {"A": 0.5, "B": 0.5},
            fund=1000,
            price={"A": 100, "B": 100},
            price_history=prices,
            leverage=2,
            board_lot_size=1,
        ).to_list()

    actual = allocate(history)
    assert actual == allocate(history.ffill())
    margin = [
        p for p in actual if p["order_condition"] == OrderCondition.MARGIN_TRADING
    ]
    assert [(p["stock_id"], p["quantity"]) for p in margin] == [("B", "10")]
    pd.testing.assert_frame_equal(history, original)
