import datetime
import time

from finlab.online.core.realtime import BidAsk, RealtimeProvider, Tick


class _DummyRealtimeProvider(RealtimeProvider):
    def __init__(self):
        self.cash = 100.0
        self.settlement = 10.0
        self._init_realtime()

    def subscribe_ticks(self, stock_ids):
        return None

    def unsubscribe_ticks(self, stock_ids):
        return None

    def subscribe_bidask(self, stock_ids):
        return None

    def unsubscribe_bidask(self, stock_ids):
        return None

    def connect_realtime(self):
        self._realtime_connected = True

    def disconnect_realtime(self):
        self.unsubscribe_balances()
        self._realtime_connected = False

    def get_cash(self):
        return self.cash

    def get_settlement(self):
        return self.settlement

    def get_total_balance(self):
        return self.cash + self.settlement


def _wait_until(predicate, timeout=1.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_bidask_normalizes_to_top5_and_top5_properties():
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


def test_bidask_preserves_missing_level_alignment():
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


def test_trade_callback_ignores_aggregate_ticks():
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


def test_balance_polling_emits_only_on_change():
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
