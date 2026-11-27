from decimal import Decimal

from finlab_online.enums import OrderCondition
from finlab_online.order_executor import Position
from finlab_online.portfolio import PortfolioSyncManager


def test_margin_cash_position_combine_keeps_behavior_with_mixed_identifier_keys():
    account_position = Position.from_list(
        [
            {
                "stock_id": "2330",
                "quantity": Decimal(1),
                "order_condition": OrderCondition.CASH,
            }
        ]
    )
    ideal_position = Position.from_list(
        [
            {
                "symbol": "2330",
                "quantity": Decimal(1),
                "order_condition": OrderCondition.MARGIN_TRADING,
            }
        ]
    )

    merged = PortfolioSyncManager.margin_cash_position_combine(
        account_position, ideal_position
    )
    payload = merged.to_list()

    assert len(payload) == 1
    assert payload[0]["symbol"] == "2330"
    assert payload[0]["stock_id"] == "2330"
    assert payload[0]["order_condition"] == OrderCondition.CASH
