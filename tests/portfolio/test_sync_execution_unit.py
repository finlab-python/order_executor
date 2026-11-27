from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from finlab_online.portfolio.sync_execution import (
    build_order_executor,
    create_order_executor,
    sync_portfolio,
)

pytestmark = pytest.mark.unit


def test_build_order_executor_combines_margin_positions_when_requested() -> None:
    account = SimpleNamespace(get_position=lambda: "account-position")

    with (
        patch(
            "finlab_online.portfolio.sync_execution.get_position",
            return_value="ideal-position",
        ) as mock_get_position,
        patch(
            "finlab_online.portfolio.sync_execution.margin_cash_position_combine",
            return_value="combined-position",
        ) as mock_combine,
        patch(
            "finlab_online.portfolio.sync_execution.OrderExecutor",
            return_value="executor",
        ) as mock_executor,
    ):
        result = build_order_executor(
            data={"position": {}},
            account=account,
            at="open",
            consider_margin_as_asset=True,
            market_name="tw_stock",
        )

    assert result == "executor"
    mock_get_position.assert_called_once_with(
        {"position": {}}, market_name="tw_stock", at="open"
    )
    mock_combine.assert_called_once_with("account-position", "ideal-position")
    mock_executor.assert_called_once_with("combined-position", account)


def test_build_order_executor_skips_margin_combine_when_disabled() -> None:
    account = SimpleNamespace(get_position=lambda: "account-position")

    with (
        patch(
            "finlab_online.portfolio.sync_execution.get_position",
            return_value="ideal-position",
        ),
        patch(
            "finlab_online.portfolio.sync_execution.margin_cash_position_combine"
        ) as mock_combine,
        patch(
            "finlab_online.portfolio.sync_execution.OrderExecutor",
            return_value="executor",
        ) as mock_executor,
    ):
        result = build_order_executor(
            data={"position": {}},
            account=account,
            at="close",
            consider_margin_as_asset=False,
            market_name=None,
        )

    assert result == "executor"
    mock_combine.assert_not_called()
    mock_executor.assert_called_once_with("ideal-position", account)


def test_sync_portfolio_creates_orders_and_returns_executor() -> None:
    executor = SimpleNamespace(create_orders=lambda **kwargs: None)

    with patch(
        "finlab_online.portfolio.sync_execution.build_order_executor",
        return_value=executor,
    ) as mock_build:
        result = sync_portfolio(
            data={"position": {}},
            account=SimpleNamespace(),
            at="close",
            consider_margin_as_asset=False,
            market_name="us_stock",
            wait_for_fill=True,
        )

    assert result is executor
    mock_build.assert_called_once()


def test_sync_portfolio_forwards_kwargs_to_create_orders() -> None:
    called: dict[str, object] = {}

    class Executor:
        def create_orders(self, **kwargs: object) -> None:
            called.update(kwargs)

    with patch(
        "finlab_online.portfolio.sync_execution.build_order_executor",
        return_value=Executor(),
    ):
        sync_portfolio(
            data={"position": {}},
            account=SimpleNamespace(),
            dry_run=True,
            best_price_limit=3,
        )

    assert called == {"dry_run": True, "best_price_limit": 3}


def test_create_order_executor_uses_margin_disabled_default() -> None:
    account = SimpleNamespace()
    with patch(
        "finlab_online.portfolio.sync_execution.build_order_executor",
        return_value="executor",
    ) as mock_build:
        result = create_order_executor(
            data={"position": {}},
            account=account,
        )

    assert result == "executor"
    mock_build.assert_called_once_with(
        {"position": {}},
        account,
        "close",
        False,
        None,
    )
