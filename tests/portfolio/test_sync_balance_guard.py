"""Offline regression for a partial rebalance with an understated balance."""

from __future__ import annotations

import datetime
import hashlib
import json
import socket
from copy import deepcopy
from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest
from finlab.backtest.sim import sim
from finlab.exceptions import PortfolioError
from finlab.portfolio import Portfolio

import finlab_online.portfolio.sync_market_data as market_data_module
from finlab_online.order_executor import OrderExecutor, Position
from finlab_online.portfolio import PortfolioSyncManager

from .offline_sim import (
    RealDateTimeMeta,
    TaipeiSyntheticMarket,
    patched_datetime,
    use_market,
)

pytestmark = pytest.mark.unit

NOW = pd.Timestamp("2024-06-03 20:00", tz="Asia/Taipei")


class FixedMarket(TaipeiSyntheticMarket):
    def __init__(self, end="2024-06-03"):
        super().__init__(pd.Timestamp(end))
        for symbol, price in {"1101": 100.0, "2330": 200.0, "2454": 600.0}.items():
            self._close[symbol] = price


def _frozen_clock(now=NOW):
    class FrozenDateTime(datetime.datetime, metaclass=RealDateTimeMeta):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(now.timestamp(), tz=tz or now.tzinfo)

        def astimezone(self, tz=None):
            return super().astimezone(tz or NOW.tzinfo)

    return patched_datetime(FrozenDateTime)


@pytest.fixture
def scenario(monkeypatch, offline_sim):
    def forbidden(*args, **kwargs):
        pytest.fail("Network/authentication is forbidden in balance guard tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr("finlab.login", forbidden)
    monkeypatch.setattr("finlab.get_token", forbidden)
    market = FixedMarket()
    use_market(monkeypatch, market)

    close = market.get_price("close")
    updated_signal = pd.DataFrame(False, index=close.index, columns=close.columns)
    updated_signal.loc[:"2024-05-15", "1101"] = True
    updated_signal.loc["2024-05-16":, "2330"] = True
    retained_signal = updated_signal * False
    retained_signal["2454"] = True
    # Month-end rebalance dates follow the clock and are saved in pm.data.
    end = close.index[-1]
    options = {"resample": "M", "market": market, "upload": False, "end_date": end}
    updated_report = sim(updated_signal, **options)
    retained_report = sim(retained_signal, **options)
    return Portfolio(
        {"updated": (updated_report, 0.2), "retained": (retained_report, 0.8)}
    )


def _record(symbol, quantity, weight, applied="2024-05-31"):
    return {
        "timestamp": "2024-04-30T20:00:00+08:00",
        "next_trading_time": "2024-05-31T15:00:00+08:00",
        "last_market_timestamp": "2024-06-03T15:00:00+08:00",
        "applied_signal_at": applied,
        "position": Position({symbol: quantity}, weights={symbol: 1.0}).to_list(),
        "allocation": 123456,
        "weight": weight,
        "entry_at": "close",
        "exit_at": "close",
        "stop": [],
        "stop_loss": 1,
        "take_profit": None,
        "trail_stop": None,
        "market": "synthetic",
    }


def _manager(*, missed=False):
    return PortfolioSyncManager(
        {
            "position": {
                "updated": _record(
                    "1101",
                    1000,
                    0.2 if missed else 0.1,
                    "2024-04-30" if missed else "2024-05-31",
                ),
                "retained": _record("2454", 1000, 0.8),
            },
            "history": {"updated": [_record("1101", 900, 0.1)]},
            "config": {
                "params": {
                    "total_balance": 500000,
                    "rebalance_safety_weight": 0.1,
                    "smooth_transition": False,
                    "kwargs": {},
                }
            },
        }
    )


def _orders(pm, account):
    return pm.create_order_executor(account).generate_orders()


def _track_writes(pm):  # noqa: C901 - instrument each mutating container operation
    """Observe even transient mutations of the actual persistent containers."""
    writes = []

    class TrackedDict(dict):
        def __deepcopy__(self, memo):
            # Copies of saved params are not persistent state writes.
            return {key: deepcopy(value, memo) for key, value in self.items()}

        def __setitem__(self, key, value):
            writes.append(("set", key))
            super().__setitem__(key, value)

        def __delitem__(self, key):
            writes.append(("delete", key))
            super().__delitem__(key)

        def pop(self, key, *args):
            writes.append(("pop", key))
            return super().pop(key, *args)

        def setdefault(self, key, *args):
            writes.append(("setdefault", key))
            return super().setdefault(key, *args)

        def update(self, *args, **kwargs):
            writes.append(("update",))
            return super().update(*args, **kwargs)

        def clear(self):
            writes.append(("clear",))
            return super().clear()

    class TrackedList(list):
        def __deepcopy__(self, memo):
            return [deepcopy(value, memo) for value in self]

        def __setitem__(self, key, value):
            writes.append(("list-set", key))
            super().__setitem__(key, value)

        def __delitem__(self, key):
            writes.append(("list-delete", key))
            super().__delitem__(key)

        def append(self, value):
            writes.append(("append",))
            return super().append(value)

        def pop(self, *args):
            writes.append(("list-pop",))
            return super().pop(*args)

        def extend(self, values):
            writes.append(("extend",))
            return super().extend(values)

    def track(value):
        if isinstance(value, dict):
            return TrackedDict({key: track(item) for key, item in value.items()})
        if isinstance(value, list):
            return TrackedList(track(item) for item in value)
        return value

    pm.data = track(pm.data)
    return writes


@pytest.mark.parametrize(
    "trigger", ["weight-change", "missed", "legacy-missed", "same-config"]
)
@pytest.mark.parametrize("removed", [None, "absent", "zero-weight"])
def test_update_rejects_balance_below_existing_holdings(
    scenario, trigger, removed, caplog
):
    pm = _manager(missed=trigger in {"missed", "legacy-missed"})
    if trigger == "legacy-missed":
        del pm.data["position"]["updated"]["applied_signal_at"]
        pm.data["position"]["updated"]["next_trading_time"] = (
            "2024-04-30T15:00:00+08:00"
        )
    if removed is not None:
        pm.data["position"]["removed"] = _record("2330", 10, 0.3)
        pm.data["history"]["removed"] = [_record("2330", 5, 0.3)]
        if removed == "zero-weight":
            scenario.position_schedulers["removed"] = scenario.position_schedulers[
                "updated"
            ]._replace(total_weight=0)
    # Both normal reports are outside their due window: the missed variants
    # must be selected by the real catch-up decision introduced in PR #185.
    with _frozen_clock():
        assert all(
            not s.is_rebalance_due() for s in scenario.position_schedulers.values()
        )
    before = deepcopy(pm.data)
    writes = _track_writes(pm)
    data_before = pm.data
    account = SimpleNamespace(
        get_position=lambda: Position.from_list(
            [p for info in before["position"].values() for p in info["position"]]
        )
    )
    orders_before = _orders(pm, account)
    with (
        _frozen_clock(),
        mock.patch.object(
            Position, "from_report", wraps=Position.from_report
        ) as rebuild,
        mock.patch.object(OrderExecutor, "create_orders") as create_orders,
    ):
        try:
            if trigger == "same-config":
                pm.update_same_config(scenario)
            else:
                pm.update(
                    scenario,
                    total_balance=500000,
                    rebalance_safety_weight=0.1,
                    smooth_transition=trigger != "weight-change",
                )
        except PortfolioError as error:
            message = str(error)
        else:
            pytest.fail(
                "update() returned without an exception: "
                f"updated.position={pm.data['position']['updated']['position']}, "
                f"updated.allocation={pm.data['position']['updated']['allocation']}, "
                f"orders={_orders(pm, account)}"
            )
    assert "500000" in message and "600000" in message
    assert "Increase total_balance" in message
    assert "at least 600001" in message
    assert "stop-loss/take-profit" in message
    assert "rebalance those sleeves in the same update" not in message
    rebuild.assert_not_called()
    create_orders.assert_not_called()
    if trigger in {"missed", "legacy-missed"}:
        assert "missed the rebalance" in caplog.text
    assert pm.data is data_before
    assert pm.data == before
    assert writes == []
    assert _orders(pm, account) == orders_before == []


def test_sufficient_balance_matches_main(scenario):
    pm = _manager()
    retained = deepcopy(pm.data["position"]["retained"])
    with _frozen_clock():
        pm.update(
            scenario,
            total_balance=1000000,
            rebalance_safety_weight=0.1,
            smooth_transition=False,
        )
    updated = pm.data["position"]["updated"]
    assert updated["allocation"] == 200000
    assert updated["position"] == Position({"2330": 1000}).to_list()
    assert pm.data["position"]["retained"] == retained
    # Captured from origin/main d127e7df9f93dd7b672649bf39366d8b842ef5f6.
    # JSON round-trips finite floats exactly, so this checks every saved field.
    digest = hashlib.sha256(json.dumps(pm.data, sort_keys=True).encode()).hexdigest()
    assert digest == "bb06e21db4d09c8c1ab6a37303155d86b76a42dc09ac18c77d7c554b831908a4"


def _account(pm):
    held = Position.from_list(
        [p for info in pm.data["position"].values() for p in info["position"]]
    )
    return SimpleNamespace(get_position=lambda: held)


def _order_diff(pm, account):
    return [(o["symbol"], o["quantity"]) for o in _orders(pm, account)]


@pytest.fixture
def daily_scenario(monkeypatch, offline_sim):
    def make(day, *, exit_kind=None, appreciated=False):
        market = FixedMarket(day)
        if appreciated:
            market._close.loc["2024-06-12":, "2454"] = 1200
            market._close.loc["2024-06-12":, "1101"] = (
                80 if exit_kind == "stop_loss" else 115
            )
        use_market(monkeypatch, market)
        reports = {}
        for sid, symbol in {"updated": "1101", "retained": "2454"}.items():
            signal = market._close * False
            signal[symbol] = True
            kwargs = {exit_kind: 0.1} if exit_kind and sid == "updated" else {}
            reports[sid] = (
                sim(signal, resample="M", market=market, upload=False, **kwargs),
                0.5,
            )
        return Portfolio(reports)

    return make


@pytest.mark.parametrize("same_config", [False, True])
@pytest.mark.parametrize("exit_kind", [None, "stop_loss", "take_profit"])
@pytest.mark.parametrize("day", ["2024-06-12", "2024-06-13"])
def test_appreciation_without_rebuild_allows_stops(
    daily_scenario, same_config, exit_kind, day
):
    pm = PortfolioSyncManager()
    with _frozen_clock(pd.Timestamp("2024-06-05 20:00", tz="Asia/Taipei")):
        pm.update(
            daily_scenario("2024-06-05", exit_kind=exit_kind),
            total_balance=1000000,
            rebalance_safety_weight=0,
        )
    account = _account(pm)
    retained = deepcopy(pm.data["position"]["retained"])
    port = daily_scenario(day, exit_kind=exit_kind, appreciated=True)
    with (
        _frozen_clock(pd.Timestamp(f"{day} 20:00", tz="Asia/Taipei")),
        mock.patch.object(
            Position, "from_report", wraps=Position.from_report
        ) as rebuild,
        mock.patch.object(OrderExecutor, "create_orders") as create_orders,
    ):
        assert all(not s.is_rebalance_due() for s in port.position_schedulers.values())
        assert (
            market_data_module.compute_existing_asset_value(
                pm.data["position"], port.position_schedulers, []
            )
            > 1000000
        )
        if same_config:
            pm.update_same_config(port)
        else:
            pm.update(port, total_balance=1000000, rebalance_safety_weight=0)
        rebuild.assert_not_called()
        create_orders.assert_not_called()
    assert pm.data["position"]["retained"] == retained
    if exit_kind:
        assert _order_diff(pm, account) == [("1101", -5000.0)]
        assert len(pm.data["position"]["updated"]["stop"]) == 1
    else:
        assert _order_diff(pm, account) == []


@pytest.mark.parametrize("removed", ["absent", "zero-weight", "same-config"])
def test_remove_only_with_appreciated_retained_holdings(daily_scenario, removed):
    pm = PortfolioSyncManager()
    with _frozen_clock(pd.Timestamp("2024-06-05 20:00", tz="Asia/Taipei")):
        pm.update(
            daily_scenario("2024-06-05"),
            total_balance=1000000,
            rebalance_safety_weight=0,
        )
    account = _account(pm)
    original = deepcopy(pm.data["position"])
    port = daily_scenario("2024-06-12", appreciated=True)
    if removed == "zero-weight":
        port.position_schedulers["updated"] = port.position_schedulers[
            "updated"
        ]._replace(total_weight=0)
    else:
        del port.position_schedulers["updated"]
    if removed == "same-config":
        pm.data["config"]["params"]["total_balance"] = 500000
    with (
        _frozen_clock(pd.Timestamp("2024-06-12 20:00", tz="Asia/Taipei")),
        mock.patch.object(
            Position, "from_report", wraps=Position.from_report
        ) as rebuild,
        mock.patch.object(OrderExecutor, "create_orders") as create_orders,
    ):
        if removed == "same-config":
            pm.update_same_config(port)
        else:
            pm.update(port, total_balance=500000, rebalance_safety_weight=0)
        rebuild.assert_not_called()
        create_orders.assert_not_called()
    assert list(pm.data["position"]) == ["retained"]
    assert pm.data["position"]["retained"] == original["retained"]
    assert pm.data["history"]["updated"][-1] == original["updated"]
    assert _order_diff(pm, account) == [("1101", -5000.0)]


@pytest.mark.parametrize("offset", [-1.0, -1e-8, 0.0, 1e-8])
@pytest.mark.parametrize("price, quantity", [(600.0, 1000), (100.01, 3)])
def test_rebuild_rejects_equal_balance_and_float_noise(
    scenario, offset, price, quantity
):
    pm = _manager()
    # True decimal equality: the real valuation is 3 * 100.01, represented
    # as 300.03000000000003 rather than the literal balance 300.03.
    market = scenario.position_schedulers["retained"].market
    market._close["2454"] = price
    pm.data["position"]["retained"] = _record("2454", quantity, 0.8)
    before = deepcopy(pm.data)
    writes = _track_writes(pm)
    data_before = pm.data
    account = _account(pm)
    with (
        _frozen_clock(),
        mock.patch.object(
            Position, "from_report", wraps=Position.from_report
        ) as rebuild,
        mock.patch.object(OrderExecutor, "create_orders") as create_orders,
        pytest.raises(PortfolioError),
    ):
        pm.update(
            scenario,
            total_balance=round(price * quantity, 2) + offset,
            rebalance_safety_weight=0.1,
            smooth_transition=False,
        )
    rebuild.assert_not_called()
    create_orders.assert_not_called()
    assert pm.data is data_before
    assert pm.data == before
    assert writes == []
    assert _order_diff(pm, account) == []


@pytest.mark.parametrize("offset", [-1e-8, 0.0, 1e-8])
def test_no_rebuild_allows_equal_balance_and_float_noise(scenario, offset):
    pm = _manager()
    pm.data["position"]["updated"] = _record("2330", 1000, 0.2)
    scenario.position_schedulers["retained"].market._close["2454"] = 100.01
    pm.data["position"]["retained"] = _record("2454", 3, 0.8)
    positions = deepcopy(pm.data["position"])
    account = _account(pm)
    with (
        _frozen_clock(),
        mock.patch.object(
            Position, "from_report", wraps=Position.from_report
        ) as rebuild,
    ):
        pm.update(scenario, total_balance=200300.03 + offset)
    rebuild.assert_not_called()
    assert pm.data["position"] == positions
    assert _order_diff(pm, account) == []


def test_zero_aggregate_weight_does_not_hide_positive_rebuild(scenario):
    pm = _manager()
    scenario.position_schedulers["negative"] = scenario.position_schedulers[
        "updated"
    ]._replace(total_weight=-0.2)
    before = deepcopy(pm.data)
    account = _account(pm)
    writes = _track_writes(pm)
    with (
        _frozen_clock(),
        mock.patch.object(
            Position, "from_report", wraps=Position.from_report
        ) as rebuild,
        pytest.raises(PortfolioError),
    ):
        pm.update(scenario, total_balance=500000, smooth_transition=False)
    rebuild.assert_not_called()
    assert pm.data == before
    assert writes == []
    assert _order_diff(pm, account) == []


def test_negative_sleeve_weight_names_strategy_before_rebuild(scenario):
    pm = PortfolioSyncManager()
    scenario.position_schedulers["negative"] = scenario.position_schedulers[
        "updated"
    ]._replace(total_weight=-0.4)
    before = deepcopy(pm.data)
    with (
        _frozen_clock(),
        mock.patch.object(
            Position, "from_report", wraps=Position.from_report
        ) as rebuild,
        pytest.raises(PortfolioError, match=r"negative: -0\.4"),
    ):
        pm.update(scenario, total_balance=5000000, smooth_transition=False)
    rebuild.assert_not_called()
    assert pm.data == before


def test_rejected_rebuild_does_not_apply_other_sleeve_stop(daily_scenario):
    pm = PortfolioSyncManager()
    with _frozen_clock(pd.Timestamp("2024-06-05 20:00", tz="Asia/Taipei")):
        pm.update(
            daily_scenario("2024-06-05", exit_kind="take_profit"),
            total_balance=1000000,
            rebalance_safety_weight=0,
        )
    account = _account(pm)
    port = daily_scenario("2024-06-12", exit_kind="take_profit", appreciated=True)
    port.position_schedulers["retained"] = port.position_schedulers[
        "retained"
    ]._replace(total_weight=0.4)
    before = deepcopy(pm.data)
    with (
        _frozen_clock(pd.Timestamp("2024-06-12 20:00", tz="Asia/Taipei")),
        mock.patch.object(
            Position, "from_report", wraps=Position.from_report
        ) as rebuild,
        pytest.raises(PortfolioError),
    ):
        # updated is the stopped but non-rebuilt sleeve (market value 575000).
        pm.update(port, total_balance=500000, smooth_transition=False)
    rebuild.assert_not_called()
    assert pm.data == before
    assert pm.data["position"]["updated"]["stop"] == []
    assert _order_diff(pm, account) == []
