"""Offline ``sim()`` harness: a synthetic market and a stubbed backtest licence.

Lets unit tests run the real backtest engine and report assembly without
credentials or data downloads. ``SyntheticMarket`` and ``enable_offline_sim``
are copied from finlab's tests; the rest is shared by the sync tests here.
"""

from __future__ import annotations

import datetime
import importlib
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest import mock

import finlab.backtest.config as sim_config
import finlab.core.report as report_module
import numpy as np
import pandas as pd
from finlab.core import aes
from finlab.market import Market

import finlab_online.core.position as position_module
import finlab_online.portfolio.sync_market_data as sync_market_data_module
import finlab_online.portfolio.sync_state as sync_state_module
import finlab_online.portfolio.sync_update as sync_update_module

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest

# finlab.backtest re-exports sim(), shadowing the submodule attribute.
sim_module = importlib.import_module("finlab.backtest.sim")

# Licence expiry far in the future (2100-01-01), as the engine expects.
_OFFLINE_LICENCE = b"4102444800000000000"

ASSET_NAMES = {"1101": "台泥", "2330": "台積電", "2454": "聯發科"}


class SyntheticMarket(Market):
    """Deterministic daily market whose prices end on ``end``."""

    def __init__(self, end: pd.Timestamp, periods: int = 400) -> None:
        index = pd.bdate_range(end=end.normalize(), periods=periods)
        steps = np.arange(periods, dtype=float)
        self._close = pd.DataFrame(
            {
                symbol: 100 + offset + np.sin(steps / (5 + offset)) * 5 + steps * 0.05
                for offset, symbol in enumerate(ASSET_NAMES)
            },
            index=index,
        )

    @staticmethod
    def get_name() -> str:
        return "synthetic"

    @staticmethod
    def get_asset_id_to_name() -> dict[str, str]:
        return dict(ASSET_NAMES)

    def get_price(
        self, trade_at_price: str | pd.Series | pd.DataFrame, adj: bool = True
    ) -> pd.DataFrame:
        if trade_at_price == "volume":
            return self._close * 0 + 1_000
        return self._close.copy()


def enable_offline_sim(monkeypatch: pytest.MonkeyPatch) -> type[SyntheticMarket]:
    """Patch licence and version checks so ``sim()`` runs fully offline."""
    monkeypatch.setattr(
        aes,
        "AES",
        lambda key: SimpleNamespace(
            decrypt_ctr=lambda encryption, iv: _OFFLINE_LICENCE
        ),
    )
    monkeypatch.setattr(sim_module, "download_backtest_encryption", lambda: "offline")
    monkeypatch.setattr(sim_config, "check_version", lambda: None)
    return SyntheticMarket


def close_at(day: str | pd.Timestamp) -> pd.Timestamp:
    """The 15:00 Asia/Taipei market close on *day*."""
    return (
        pd.Timestamp(pd.Timestamp(day).date()) + pd.Timedelta(hours=15)
    ).tz_localize("Asia/Taipei")


class TaipeiSyntheticMarket(SyntheticMarket):
    """Synthetic prices with a tz-aware 15:00 Taipei close, like TWMarket."""

    @staticmethod
    def tzinfo() -> datetime.timezone:
        return datetime.timezone(datetime.timedelta(hours=8))

    def market_close_at_timestamp(self, timestamp=None) -> pd.Timestamp:
        return close_at(timestamp if timestamp is not None else self._close.index[-1])


def use_market(monkeypatch: pytest.MonkeyPatch, market: Market) -> None:
    """Resolve every strategy's market name to *market*."""
    for module in (sync_state_module, sync_market_data_module):
        monkeypatch.setattr(module, "get_market_by_name", lambda name: market)


class RealDateTimeMeta(type):
    """Lets a frozen ``datetime`` subclass pass ``isinstance`` checks for real datetimes."""

    def __instancecheck__(cls, obj: object) -> bool:
        return isinstance(obj, datetime.datetime)


@contextmanager
def patched_datetime(frozen: type[datetime.datetime]) -> Iterator[None]:
    """Use *frozen* as ``datetime.datetime`` in the modules that read the wall clock."""
    fake = mock.MagicMock(wraps=datetime)
    fake.datetime = frozen
    fake.timezone = datetime.timezone
    fake.timedelta = datetime.timedelta
    with ExitStack() as stack:
        for module in (report_module, position_module, sync_update_module):
            stack.enter_context(mock.patch.object(module, "datetime", fake))
        yield
