from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from finlab_online.portfolio.sync_market_data import (
    calc_position_value,
    compute_existing_asset_value,
    fetch_tw_market_snapshot,
)

pytestmark = pytest.mark.unit


def _market_stub(
    *, lot: float = 1000, close: dict[str, float] | None = None
) -> SimpleNamespace:
    if close is None:
        close = {"2330": 600.0}
    close_frame = pd.DataFrame(
        [close], index=pd.DatetimeIndex([pd.Timestamp("2026-01-02")])
    )
    return SimpleNamespace(
        get_odd_lot=lambda: lot,
        get_price=lambda _field, adj=False: close_frame,
    )


def test_calc_position_value_raises_on_missing_symbol() -> None:
    with pytest.raises(ValueError, match=r"stock 2330 not found"):
        calc_position_value(
            [{"symbol": "2330", "quantity": 1}],
            lot=1000,
            price=pd.Series({"1101": 10.0}),
        )


def test_calc_position_value_skips_nan_prices(caplog: pytest.LogCaptureFixture) -> None:
    total = calc_position_value(
        [{"symbol": "2330", "quantity": 2}],
        lot=1000,
        price=pd.Series({"2330": float("nan")}),
    )

    assert total == 0.0
    assert "price of 2330 is nan" in caplog.text


def test_compute_existing_asset_value_skips_updated_strategies_and_falls_back_to_tw_market() -> (
    None
):
    position_data = {
        "keep": {
            "position": [{"symbol": "2330", "quantity": 1}],
            "market": "broken_market",
        },
        "updated": {
            "position": [{"symbol": "1101", "quantity": 999}],
            "market": "tw_stock",
        },
    }

    with (
        patch(
            "finlab_online.portfolio.sync_market_data.get_market_by_name",
            side_effect=ValueError("bad market"),
        ),
        patch(
            "finlab_online.portfolio.sync_market_data.TWMarket",
            return_value=_market_stub(close={"2330": 50.0}),
        ) as mock_tw_market,
    ):
        total = compute_existing_asset_value(
            position_data,
            portfolio={},
            updated_strategies=["updated"],
        )

    assert total == 50000.0
    mock_tw_market.assert_called_once()


def test_compute_existing_asset_value_prefers_portfolio_market_when_info_missing() -> (
    None
):
    portfolio_market = _market_stub(lot=1, close={"2330": 12.5})
    total = compute_existing_asset_value(
        {"alpha": {"position": [{"symbol": "2330", "quantity": 4}]}},
        {"alpha": SimpleNamespace(market=portfolio_market)},
        updated_strategies=[],
    )
    assert total == 50.0


def test_fetch_tw_market_snapshot_returns_three_dicts() -> None:
    market = SimpleNamespace(
        get_reference_price=lambda: {"2330": 610.0},
        get_price=lambda field, adj=False: pd.DataFrame(
            [{"2330": 600.0 if field == "close" else 10000.0}],
            index=pd.DatetimeIndex([pd.Timestamp("2026-01-02")]),
        ),
    )

    with patch(
        "finlab_online.portfolio.sync_market_data.TWMarket", return_value=market
    ):
        ref_price, close_price, volume = fetch_tw_market_snapshot()

    assert ref_price == {"2330": 610.0}
    assert close_price == {"2330": 600.0}
    assert volume == {"2330": 10000.0}


@pytest.mark.parametrize(
    "markets",
    [("us_stock",), ("us_fund",), ("tw_stock",), ("tw_stock", "us_stock", "us_fund")],
)
def test_portfolio_display_uses_strategy_market_prices_and_lots(monkeypatch, markets):
    from finlab.markets import get_market_by_name
    from finlab.markets.tw import TWMarket

    from finlab_online.portfolio import PortfolioSyncManager

    quotes = {
        "tw_stock": ("2330", 600.0, 10000.0),
        "us_stock": ("AAPL", 200.0, 50000.0),
        "us_fund": ("SPY", 500.0, 30000.0),
    }
    tables = {get_market_by_name(name)._price_table: name for name in quotes}
    tables.update(price="tw_stock", etl="tw_stock")

    def get_data(key):
        table, field = key.split(":")
        symbol, price, volume = quotes[tables[table]]
        # Unrelated symbols must not overwrite another strategy's own market.
        row = {q[0]: 1.0 for q in quotes.values()}
        row[symbol] = volume if field in ("volume", "成交股數") else price
        return pd.DataFrame([row], index=pd.to_datetime(["2026-10-27"]))

    monkeypatch.setattr("finlab.data.get", get_data)
    monkeypatch.setattr(TWMarket, "get_reference_price", lambda self: {"2330": 610.0})
    positions = {}
    expected_value = 0
    for name in markets:
        symbol, price, _ = quotes[name]
        lot = get_market_by_name(name).get_odd_lot()
        positions[name] = {
            "position": [{"symbol": symbol, "quantity": 2, "order_condition": 1}],
            "market": name,
            "allocation": 1000000,
            "weight": 1 / len(markets),
            "entry_at": "close",
            "exit_at": "close",
            "stop": [],
            "stop_loss": 1,
            "take_profit": None,
            "trail_stop": None,
            "timestamp": "2026-10-27T00:00:00Z",
            "next_trading_time": "2026-10-28T00:00:00Z",
        }
        expected_value += (610.0 if name == "tw_stock" else price) * 2 * lot
    pm = PortfolioSyncManager({"position": positions, "config": {}})
    frame = pm.get_total_position()
    for name in markets:
        symbol, price, volume = quotes[name]
        lot = get_market_by_name(name).get_odd_lot()
        assert frame.loc[symbol, "quantity"] == 2
        assert frame.loc[symbol, "price"] == (610.0 if name == "tw_stock" else price)
        assert frame.loc[symbol, "close_price"] == price
        assert frame.loc[symbol, "volume"] == volume / lot
        assert frame.loc[symbol, "weight"] == pytest.approx(
            price * 2 * lot / (1000000 * len(markets))
        )
    assert repr(pm).startswith(f"Estimate value {int(expected_value)}\n")
