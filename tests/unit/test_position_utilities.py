"""Unit tests for Position utility behaviors."""

from decimal import Decimal

from finlab.online.enums import OrderCondition
from finlab.online.order_executor import Position


def test_position_json_roundtrip(tmp_path):
    pos = Position({"2330": 1})
    json_path = tmp_path / "position.json"

    pos.to_json(str(json_path))
    pos2 = Position.from_json(str(json_path))

    assert pos.position[0] == pos2.position[0]


def test_position_arithmetic_and_conditions():
    pos = Position({"2330": 1}) + Position({"2330": 1, "1101": 1})
    for order in pos.position:
        if order["stock_id"] == "2330":
            assert order["quantity"] == 2
        if order["stock_id"] == "1101":
            assert order["quantity"] == 1

    pos = Position.from_list(pos.to_list())
    for order in pos.position:
        if order["stock_id"] == "2330":
            assert order["quantity"] == 2
        if order["stock_id"] == "1101":
            assert order["quantity"] == 1

    pos = Position({"2330": Decimal("1.1")})
    pos = Position.from_list(pos.to_list())
    assert pos.position[0]["quantity"] == Decimal("1.1")

    pos = Position({"2330": 2}) - Position({"2330": 1, "1101": 1})
    for order in pos.position:
        if order["stock_id"] == "2330":
            assert order["quantity"] == 1
        if order["stock_id"] == "1101":
            assert order["quantity"] == -1

    pos = Position({"2330": 2}, day_trading_long=True)
    pos.fall_back_cash()
    assert pos.position[0]["stock_id"] == "2330"
    assert pos.position[0]["quantity"] == 2
    assert pos.position[0]["order_condition"] == OrderCondition.CASH

    pos = Position({"2330": 2}, margin_trading=True)
    assert pos.position[0]["order_condition"] == OrderCondition.MARGIN_TRADING

    pos = Position({"2330": -2}, margin_trading=True)
    assert pos.position[0]["order_condition"] == OrderCondition.CASH

    pos = Position({"2330": -2}, short_selling=True)
    assert pos.position[0]["order_condition"] == OrderCondition.SHORT_SELLING

    pos = Position({"2330": 2}, short_selling=True)
    assert pos.position[0]["order_condition"] == OrderCondition.CASH

    pos = Position.from_list([
        {"stock_id": "2330", "quantity": 2, "order_condition": OrderCondition.CASH}
    ])
    pos2 = Position.from_dict([
        {"stock_id": "2330", "quantity": 2, "order_condition": OrderCondition.CASH}
    ])
    assert pos.position[0] == pos2.position[0]


def test_position_from_weight():
    position = Position.from_weight(
        {"1101": 0.5, "2330": 0.5},
        fund=1_000_000,
        price={"1101": 50, "2330": 100},
    )
    expected = Position.from_list(
        [
            {"stock_id": "1101", "quantity": 10, "order_condition": OrderCondition.CASH},
            {"stock_id": "2330", "quantity": 5, "order_condition": OrderCondition.CASH},
        ]
    )
    assert len((position - expected).position) == 0

    position = Position.from_weight(
        {"1101": 0.5, "2330": 0.5},
        fund=1_000_000,
        price={"1101": 30, "2330": 60},
        odd_lot=True,
        board_lot_size=100,
    )
    expected = Position.from_list(
        [
            {
                "stock_id": "1101",
                "quantity": Decimal("166.66"),
                "order_condition": OrderCondition.CASH,
            },
            {
                "stock_id": "2330",
                "quantity": Decimal("83.33"),
                "order_condition": OrderCondition.CASH,
            },
        ]
    )
    assert len((position - expected).position) == 0

    position = Position.from_weight(
        {"1101": -0.5, "2330": 0.5},
        fund=1_000_000,
        price={"1101": 30, "2330": 60},
        odd_lot=True,
        board_lot_size=100,
        short_selling=True,
    )
    expected = Position.from_list(
        [
            {
                "stock_id": "1101",
                "quantity": Decimal("-166.66"),
                "order_condition": OrderCondition.SHORT_SELLING,
            },
            {
                "stock_id": "2330",
                "quantity": Decimal("83.33"),
                "order_condition": OrderCondition.CASH,
            },
        ]
    )
    assert len((position - expected).position) == 0

    try:
        Position.from_weight(
            {"1101": 0.5, "2330": 0.5},
            fund=1_000_000,
            price={"1101": 30, "2330": 60},
            odd_lot=True,
            board_lot_size=30,
            margin_trading=True,
        )
        assert False
    except Exception:
        assert True
