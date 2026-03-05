"""Unit tests for calculate_price_with_extra_bid."""

from finlab.online.base_account import Action
from finlab.online.order_executor import calculate_price_with_extra_bid


def test_calculate_price_with_extra_bid_cases():
    test_data = {
        "test_1": {
            "price": 5.2,
            "extra_bid_pct": 0.06,
            "action": Action.BUY,
            "expected_result": 5.51,
        },
        "test_2": {
            "price": 7.4,
            "extra_bid_pct": 0.02,
            "action": Action.SELL,
            "expected_result": 7.26,
        },
        "test_3": {
            "price": 25.65,
            "extra_bid_pct": 0.1,
            "action": Action.BUY,
            "expected_result": 28.20,
        },
        "test_4": {
            "price": 11.05,
            "extra_bid_pct": 0.1,
            "action": Action.SELL,
            "expected_result": 9.95,
        },
        "test_5": {
            "price": 87.0,
            "extra_bid_pct": 0.04,
            "action": Action.BUY,
            "expected_result": 90.4,
        },
        "test_6": {
            "price": 73.0,
            "extra_bid_pct": 0.06,
            "action": Action.SELL,
            "expected_result": 68.7,
        },
        "test_7": {
            "price": 234.0,
            "extra_bid_pct": 0.08,
            "action": Action.BUY,
            "expected_result": 252.5,
        },
        "test_8": {
            "price": 234.0,
            "extra_bid_pct": 0.08,
            "action": Action.SELL,
            "expected_result": 215.5,
        },
        "test_9": {
            "price": 650.0,
            "extra_bid_pct": 0.05,
            "action": Action.BUY,
            "expected_result": 682,
        },
        "test_10": {
            "price": 756.0,
            "extra_bid_pct": 0.055,
            "action": Action.SELL,
            "expected_result": 715,
        },
        "test_11": {
            "price": 1990.0,
            "extra_bid_pct": 0.035,
            "action": Action.BUY,
            "expected_result": 2055,
        },
        "test_12": {
            "price": 1455.0,
            "extra_bid_pct": 0.088,
            "action": Action.SELL,
            "expected_result": 1330,
        },
    }

    for _, test_case in test_data.items():
        price = test_case["price"]
        extra_bid_pct = test_case["extra_bid_pct"]
        action = test_case["action"]
        expected_result = test_case["expected_result"]

        result = calculate_price_with_extra_bid(
            price,
            extra_bid_pct if action == Action.BUY else -extra_bid_pct,
        )
        assert result == expected_result


def test_extra_bid_and_up_down_limit():
    action = Action.BUY
    last_close = 68
    now_price = 73
    extra_bid_pct = 0.08
    up_down_limit = calculate_price_with_extra_bid(last_close, 0.1)
    price = calculate_price_with_extra_bid(now_price, extra_bid_pct)

    if (action == Action.BUY and price > up_down_limit) or (
        action == Action.SELL and price < up_down_limit
    ):
        price = up_down_limit

    assert price == 74.8
