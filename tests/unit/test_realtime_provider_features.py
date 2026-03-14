from __future__ import annotations

import datetime
import time
from collections.abc import Callable

from finlab.online.core.realtime_helpers import build_ticks_from_intraday_trade_rows
from finlab.online.core.realtime_models import BidAsk, Tick
from finlab.online.core.realtime_provider import RealtimeProvider


class _DummyRealtimeProvider(RealtimeProvider):
    def __init__(self) -> None:
        self.cash = 100.0
        self.settlement = 10.0
        self._init_realtime()

    def subscribe_ticks(self, stock_ids: list[str]) -> None:
        return None

    def unsubscribe_ticks(self, stock_ids: list[str]) -> None:
        return None

    def subscribe_bidask(self, stock_ids: list[str]) -> None:
        return None

    def unsubscribe_bidask(self, stock_ids: list[str]) -> None:
        return None

    def connect_realtime(self) -> None:
        self._realtime_connected = True

    def disconnect_realtime(self) -> None:
        self.unsubscribe_balances()
        self._realtime_connected = False

    def get_cash(self) -> float:
        return self.cash

    def get_settlement(self) -> float:
        return self.settlement

    def get_total_balance(self) -> float:
        return self.cash + self.settlement


class _BackfillRealtimeProvider(_DummyRealtimeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.backfill_calls: list[tuple[list[str], str | None, str | None, bool]] = []
        self.snapshot_calls: list[tuple[list[str], bool]] = []
        self.subscribe_calls: list[list[str]] = []
        self.subscribe_bidask_calls: list[list[str]] = []

    def backfill_ticks(
        self,
        stock_ids: list[str],
        start_time: str | None = None,
        end_time: str | None = None,
        emit: bool = True,
    ) -> dict[str, list[Tick]]:
        self.backfill_calls.append((stock_ids, start_time, end_time, emit))
        return {
            stock_id: [
                Tick(
                    stock_id=stock_id,
                    price=100.0,
                    volume=1,
                    total_volume=1,
                    time=datetime.datetime(2026, 3, 5, 9, 0, 0),
                    source="trade",
                )
            ]
            for stock_id in stock_ids
        }

    def subscribe_ticks(self, stock_ids: list[str]) -> None:
        self.subscribe_calls.append(stock_ids)

    def get_bidask_snapshot(
        self, stock_ids: list[str], emit: bool = True
    ) -> dict[str, BidAsk]:
        self.snapshot_calls.append((stock_ids, emit))
        return {
            stock_id: BidAsk(
                stock_id=stock_id,
                bid_prices=[100.0],
                bid_volumes=[10],
                ask_prices=[101.0],
                ask_volumes=[11],
                time=datetime.datetime(2026, 3, 5, 9, 0, 0),
            )
            for stock_id in stock_ids
        }

    def subscribe_bidask(self, stock_ids: list[str]) -> None:
        self.subscribe_bidask_calls.append(stock_ids)


def _wait_until(
    predicate: Callable[[], bool], timeout: float = 1.0, interval: float = 0.02
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_bidask_normalizes_to_top5_and_top5_properties() -> None:
    bidask = BidAsk(
        stock_id="2330",
        bid_prices=[100, 99, 98, 97, 96, 95],
        bid_volumes=[10, 20, 30, 40, 50, 60],
        ask_prices=[101, 102, 103],
        ask_volumes=[11, 22, 33],
        time=datetime.datetime(2026, 3, 5, 9, 0, 0),
    )

    assert len(bidask.bid_prices) == 5
    assert len(bidask.ask_prices) == 3
    assert bidask.bid_prices_top5 == [100.0, 99.0, 98.0, 97.0, 96.0]
    assert bidask.ask_prices_top5 == [101.0, 102.0, 103.0, 0.0, 0.0]
    assert bidask.ask_volumes_top5 == [11, 22, 33, 0, 0]


def test_bidask_preserves_missing_level_alignment() -> None:
    bidask = BidAsk(
        stock_id="2330",
        bid_prices=[100.0, None, 98.0],
        bid_volumes=[10, None, 30],
        ask_prices=[101.0, None, 103.0],
        ask_volumes=[11, None, 33],
        time=datetime.datetime(2026, 3, 5, 9, 0, 0),
    )

    assert bidask.bid_prices == [100.0, 0.0, 98.0]
    assert bidask.bid_volumes == [10, 0, 30]
    assert bidask.ask_prices == [101.0, 0.0, 103.0]
    assert bidask.ask_volumes == [11, 0, 33]
    assert bidask.bid_prices_top5 == [100.0, 0.0, 98.0, 0.0, 0.0]
    assert bidask.ask_volumes_top5 == [11, 0, 33, 0, 0]


def test_trade_callback_ignores_aggregate_ticks() -> None:
    provider = _DummyRealtimeProvider()
    trades = []
    provider.on_trade(trades.append)

    provider._emit_tick(
        Tick(
            stock_id="2330",
            price=100.0,
            volume=1,
            total_volume=1,
            time=datetime.datetime.now(),
            source="aggregate",
        )
    )
    provider._emit_tick(
        Tick(
            stock_id="2330",
            price=101.0,
            volume=2,
            total_volume=3,
            time=datetime.datetime.now(),
            source="trade",
        )
    )

    assert len(trades) == 1
    assert trades[0].price == 101.0


def test_build_ticks_from_intraday_trade_rows_sorts_filters_and_repairs_total_volume() -> (
    None
):
    ticks = build_ticks_from_intraday_trade_rows(
        stock_id="2330",
        rows=[
            {"serial": 3, "price": 101.0, "size": 2, "time": "09:01:00.000000"},
            {
                "serial": 1,
                "price": 100.0,
                "size": 1,
                "time": "09:00:00.000000",
                "volume": 1,
            },
            {"serial": 2, "price": 100.5, "size": 3, "time": "09:00:30.000000"},
        ],
        session_date=datetime.date(2026, 3, 5),
        prev_close=99.0,
        pct_change=2.0,
        start_time="09:00:15",
    )

    assert [tick.price for tick in ticks] == [100.5, 101.0]
    assert [tick.total_volume for tick in ticks] == [3, 5]
    assert all(tick.prev_close == 99.0 for tick in ticks)
    assert all(tick.pct_change == 2.0 for tick in ticks)


def test_subscribe_ticks_with_backfill_calls_backfill_before_subscribe() -> None:
    provider = _BackfillRealtimeProvider()

    backfilled = provider.subscribe_ticks_with_backfill(
        ["2330", "2317"],
        start_time="09:00:00",
        end_time="09:05:00",
        emit=False,
    )

    assert list(backfilled) == ["2330", "2317"]
    assert provider.backfill_calls == [
        (["2330", "2317"], "09:00:00", "09:05:00", False)
    ]
    assert provider.subscribe_calls == [["2330", "2317"]]


def test_subscribe_bidask_with_snapshot_calls_snapshot_before_subscribe() -> None:
    provider = _BackfillRealtimeProvider()

    snapshots = provider.subscribe_bidask_with_snapshot(["2330", "2317"], emit=False)

    assert list(snapshots) == ["2330", "2317"]
    assert provider.snapshot_calls == [(["2330", "2317"], False)]
    assert provider.subscribe_bidask_calls == [["2330", "2317"]]


def test_balance_polling_emits_only_on_change() -> None:
    provider = _DummyRealtimeProvider()
    balances = []
    provider.on_balance(balances.append)

    try:
        provider.subscribe_balances(poll_interval=0.05, emit_on_change=True)
        assert _wait_until(lambda: len(balances) >= 1)
        first_count = len(balances)

        # No balance changes: callback count should stay stable.
        time.sleep(0.2)
        assert len(balances) == first_count

        # Change cash and confirm a new balance snapshot is emitted.
        provider.cash = 150.0
        assert _wait_until(lambda: len(balances) > first_count)
        assert balances[-1].available_balance == 150.0
        assert balances[-1].total_balance == 160.0
    finally:
        provider.unsubscribe_balances()
