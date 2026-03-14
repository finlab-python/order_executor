"""Shared helpers for real-order integration tests."""

from __future__ import annotations

import time
import unittest
from typing import Any

from finlab.online.base_account import Action
from finlab.online.core.account import Account
from finlab.online.enums import OrderStatus
from finlab.online.order_executor import OrderExecutor, Position


def verify_order_executor_flow(
    testcase: unittest.TestCase,
    order_executor: OrderExecutor,
    **create_order_kwargs: Any,
) -> None:
    """Create, inspect, execute, and validate orders for a target position."""
    view_orders = order_executor.create_orders(view_only=True)

    order_executor.cancel_orders()
    time.sleep(11)
    order_executor.create_orders(**create_order_kwargs)
    time.sleep(5)
    orders = order_executor.account.get_orders()

    expected_by_stock = {o["stock_id"]: o for o in view_orders}
    actual_quantity = {o.stock_id: 0 for _, o in orders.items()}

    for order in orders.values():
        if (
            order.status == OrderStatus.CANCEL
            or order.stock_id not in expected_by_stock
            or order.status == OrderStatus.FILLED
        ):
            continue

        stock_id = order.stock_id
        expected_action = (
            Action.BUY if expected_by_stock[stock_id]["quantity"] > 0 else Action.SELL
        )

        actual_quantity[stock_id] += order.quantity
        testcase.assertEqual(order.action, expected_action)
        testcase.assertEqual(
            order.order_condition, expected_by_stock[stock_id]["order_condition"]
        )

    for stock_id, quantity in actual_quantity.items():
        if quantity != 0:
            testcase.assertEqual(
                float(round(quantity, 4)),
                float(abs(expected_by_stock[stock_id]["quantity"])),
            )

    order_executor.cancel_orders()


def run_account_order_flow(
    testcase: unittest.TestCase, account: Account, odd_lot: bool = False
) -> None:
    """Run buy/sell/day-trading scenarios against a real account."""
    sid1 = "3661"
    sid2 = "1101"

    q_sid1, q_sid2 = (2.1, 1.1) if odd_lot else (2, 1)

    time.sleep(11)
    oe = OrderExecutor(Position({sid1: q_sid1, sid2: q_sid2}), account=account)
    verify_order_executor_flow(testcase, oe)

    q_sid1, q_sid2 = (2.1, -1.1) if odd_lot else (2, -1)

    time.sleep(11)
    oe = OrderExecutor(
        Position({sid1: q_sid1, sid2: q_sid2}, day_trading_short=True),
        account=account,
    )
    verify_order_executor_flow(testcase, oe)

    time.sleep(11)
    oe = OrderExecutor(
        Position({sid1: q_sid1, sid2: q_sid2}, day_trading_short=True),
        account=account,
    )
    verify_order_executor_flow(testcase, oe, market_order=True)


def run_account_update_price_flow(
    testcase: unittest.TestCase, account: Account, odd_lot: bool = False
) -> None:
    """Run update-order-price scenarios against a real account."""
    sid = "6016"
    quantity = 0.1 if odd_lot else 2

    oe = OrderExecutor(Position({sid: quantity}), account=account)
    view_orders = oe.create_orders(view_only=True)

    time.sleep(11)
    oe.create_orders()
    orders = oe.account.get_orders()

    active_order_ids = [
        order_id
        for order_id, order in orders.items()
        if order.status == OrderStatus.NEW
    ]

    time.sleep(11)
    oe.update_order_price(extra_bid_pct=0.05)
    time.sleep(1)

    orders_new = oe.account.get_orders()

    # Keep for parity with legacy test logic (ensures ID lookup does not crash)
    for order_id in active_order_ids:
        _ = orders_new.get(order_id)

    expected_by_stock = {o["stock_id"]: o for o in view_orders}
    actual_quantity = {o.stock_id: 0 for _, o in orders_new.items()}

    for order in orders_new.values():
        if (
            order.status == OrderStatus.CANCEL
            or order.stock_id not in expected_by_stock
            or order.stock_id != sid
            or order.status == OrderStatus.FILLED
        ):
            continue

        actual_quantity[sid] += order.quantity
        testcase.assertEqual(
            order.order_condition, expected_by_stock[sid]["order_condition"]
        )

    for stock_id, qty in actual_quantity.items():
        if qty != 0:
            testcase.assertEqual(
                float(round(qty, 4)), abs(expected_by_stock[stock_id]["quantity"])
            )

    oe.cancel_orders()
