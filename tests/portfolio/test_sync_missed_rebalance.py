"""PortfolioSyncManager must not stay stuck after a missed rebalance window."""

from __future__ import annotations

import datetime
import hashlib
import logging
from types import SimpleNamespace

import pandas as pd
import pytest
from finlab.backtest.sim import sim
from finlab.portfolio import Portfolio
from finlab.session_calendar import SessionCalendar, canonical

from finlab_online.portfolio import PortfolioSyncManager
from finlab_online.portfolio.sync_decisions import identify_updated_strategies

from .offline_sim import (
    RealDateTimeMeta,
    TaipeiSyntheticMarket,
    close_at,
    patched_datetime,
    use_market,
)

pytestmark = pytest.mark.unit


def calendar(now):
    """A trading calendar valid around *now* (copied from finlab's tests)."""
    sessions = pd.bdate_range("2025-01-01", "2027-12-31").strftime("%Y-%m-%d").tolist()
    sessions = [
        d for d in sessions if d not in {"2026-09-25", "2026-09-28", "2027-01-01"}
    ]
    body = {
        "schema_version": 1,
        "market": "tw",
        "timezone": "Asia/Taipei",
        "valid_from": "2025-01-01",
        "valid_through": "2027-12-31",
        "open_time": "09:00:00",
        "close_time": "13:30:00",
        "update_start_time": "15:00:00",
        "sessions": sessions,
    }
    return SessionCalendar(
        dict(
            body,
            version=hashlib.sha256(canonical(body)).hexdigest(),
            checked_at=(now - datetime.timedelta(hours=1)).isoformat(),
            expires_at=(now + datetime.timedelta(hours=25)).isoformat(),
        )
    )


TAIPEI = "Asia/Taipei"
TOTAL_BALANCE = 10_000_000
APRIL_BOUNDARY = "2024-04-30"
MAY_BOUNDARY = "2024-05-31"
FIRST_RUN_AFTER_MAY = "2024-06-03"
FIRST_RUN_AFTER_JUNE = "2024-07-01"
MISSED = "missed the rebalance"
MAY = pd.Timestamp(MAY_BOUNDARY)


def _frozen_clock(now: pd.Timestamp):
    """Freeze ``datetime.now()`` in the modules that read the wall clock."""

    class FrozenDateTime(datetime.datetime, metaclass=RealDateTimeMeta):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.tz_convert(None).to_pydatetime()

    return patched_datetime(FrozenDateTime)


def _monthly_report(day: str):
    """Hold 1101, then 2330 from mid-May, then 2454 from mid-June."""
    market = TaipeiSyntheticMarket(pd.Timestamp(day))
    close = market.get_price("close")
    signal = pd.DataFrame(False, index=close.index, columns=close.columns)
    signal.loc[:"2024-05-15", "1101"] = True
    signal.loc["2024-05-16":"2024-06-15", "2330"] = True
    signal.loc["2024-06-16":, "2454"] = True
    return sim(signal, resample="M", market=market, upload=False, end_date=day)


def _missed_logs(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if MISSED in r.getMessage()]


def _run_night(pm: PortfolioSyncManager, day: str, caplog) -> list[str]:
    report = _monthly_report(day)
    caplog.clear()
    with (
        _frozen_clock(pd.Timestamp(f"{day} 20:00", tz=TAIPEI)),
        caplog.at_level(
            logging.WARNING, logger="finlab_online.portfolio.sync_decisions"
        ),
    ):
        pm.update(Portfolio({"s": (report, 1.0)}), total_balance=TOTAL_BALANCE)
    return _missed_logs(caplog)


def _held_symbols(pm: PortfolioSyncManager) -> set[str]:
    return {p["symbol"] for p in pm.data["position"]["s"]["position"] if p["quantity"]}


@pytest.fixture
def pm(offline_sim, monkeypatch) -> PortfolioSyncManager:
    use_market(monkeypatch, TaipeiSyntheticMarket(pd.Timestamp(FIRST_RUN_AFTER_MAY)))
    return PortfolioSyncManager()


def test_missed_boundary_is_logged_and_caught_up(pm, caplog):
    assert not _run_night(pm, APRIL_BOUNDARY, caplog)
    assert _held_symbols(pm) == {"1101"}

    # The job does not run on the May boundary.
    caught = _run_night(pm, FIRST_RUN_AFTER_MAY, caplog)

    assert len(caught) == 1
    assert "2024-05-31" in caught[0]
    assert _held_symbols(pm) == {"2330"}
    assert pm.data["position"]["s"]["applied_signal_at"].startswith(MAY_BOUNDARY)


def test_promoted_boundary_is_not_flagged(pm, caplog):
    for day in (APRIL_BOUNDARY, MAY_BOUNDARY):
        assert not _run_night(pm, day, caplog)
    history_len = len(pm.data["history"]["s"])

    assert not _run_night(pm, FIRST_RUN_AFTER_MAY, caplog)
    assert _held_symbols(pm) == {"2330"}
    assert len(pm.data["history"]["s"]) == history_len


def test_catch_up_happens_once(pm, caplog):
    _run_night(pm, APRIL_BOUNDARY, caplog)
    _run_night(pm, FIRST_RUN_AFTER_MAY, caplog)
    history_len = len(pm.data["history"]["s"])

    assert not _run_night(pm, "2024-06-04", caplog)
    assert len(pm.data["history"]["s"]) == history_len


def test_a_boundary_missed_after_a_catch_up_is_also_caught_up(pm, caplog):
    _run_night(pm, APRIL_BOUNDARY, caplog)
    _run_night(pm, FIRST_RUN_AFTER_MAY, caplog)

    # The job does not run on the June boundary either.
    caught = _run_night(pm, FIRST_RUN_AFTER_JUNE, caplog)

    assert len(caught) == 1
    assert _held_symbols(pm) == {"2454"}


def _allocation(boundary: object, *, calendar_path: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        total_weight=1.0,
        is_rebalance_due=lambda: False,
        uses_trading_calendar=lambda: calendar_path,
        weights=pd.Series({"2330": 1.0}, name=boundary),
        market=SimpleNamespace(market_close_at_timestamp=close_at),
    )


def _record(**fields: object) -> dict[str, object]:
    return {
        "weight": 1.0,
        "position": [{"symbol": "2330", "stock_id": "2330"}],
        **fields,
    }


def _identify(portfolio: dict, position: dict) -> list[str]:
    return identify_updated_strategies(
        portfolio=portfolio,
        position=position,
        smooth_transition=True,
        force_override_difference=False,
    )


@pytest.mark.parametrize(
    ("boundary", "record", "expected"),
    [
        (MAY, {"applied_signal_at": APRIL_BOUNDARY}, ["s"]),
        (MAY, {"applied_signal_at": MAY_BOUNDARY}, []),
        (MAY, {"next_trading_time": close_at(APRIL_BOUNDARY).isoformat()}, ["s"]),
        (MAY, {"next_trading_time": close_at(MAY_BOUNDARY).isoformat()}, []),
        (MAY, {"next_trading_time": close_at("2024-06-30").isoformat()}, []),
        ("weight", {"applied_signal_at": APRIL_BOUNDARY}, []),
        (pd.NaT, {"applied_signal_at": APRIL_BOUNDARY}, []),
    ],
    ids=[
        "missed",
        "applied",
        "legacy-record-missed",
        "legacy-record-promoted",
        "legacy-record-ahead",
        "legacy-cloud-name",
        "no-signal-date",
    ],
)
def test_identify_updated_strategies_missed_boundary(
    boundary, record, expected, caplog
):
    with caplog.at_level(
        logging.WARNING, logger="finlab_online.portfolio.sync_decisions"
    ):
        result = _identify({"s": _allocation(boundary)}, {"s": _record(**record)})

    assert result == expected
    assert len(_missed_logs(caplog)) == len(expected)


@pytest.mark.parametrize(
    "record",
    [
        {"next_trading_time": "2024-04-30T15:00:00"},
        {"next_trading_time": ""},
        {"next_trading_time": None},
        {},
    ],
    ids=["tz-naive", "empty", "none", "missing"],
)
def test_a_malformed_record_does_not_block_other_strategies(record):
    portfolio = {
        "bad": _allocation(MAY),
        "good": _allocation(MAY),
    }
    position = {
        "bad": _record(**record),
        "good": _record(applied_signal_at=APRIL_BOUNDARY),
    }

    assert _identify(portfolio, position) == ["good"]


@pytest.mark.parametrize(
    ("applied", "expected"), [("2026-09-18", []), ("2026-09-11", ["s"])]
)
def test_labels_executing_on_one_session_are_one_rebalance(
    monkeypatch, applied, expected
):
    """A Sunday label executes on the same Monday as the Friday before it."""
    import finlab.data.calendar as calendar_module

    fresh = calendar(datetime.datetime.now(datetime.timezone.utc))
    monkeypatch.setattr(calendar_module, "get_calendar", lambda **kwargs: fresh)
    sunday = _allocation(pd.Timestamp("2026-09-20"), calendar_path=True)

    assert (
        _identify({"s": sunday}, {"s": _record(applied_signal_at=applied)}) == expected
    )
