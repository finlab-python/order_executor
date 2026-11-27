"""Offline ``sim()`` harness (copied from finlab's tests): a synthetic market and a stubbed backtest licence.

Lets unit tests run the real backtest engine and report assembly without
credentials or data downloads.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import TYPE_CHECKING

import finlab.backtest.config as sim_config
import numpy as np
import pandas as pd
from finlab.core import aes
from finlab.market import Market

if TYPE_CHECKING:
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
