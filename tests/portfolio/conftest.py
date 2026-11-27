"""Fixtures for the PortfolioSyncManager tests (they run on top of an installed finlab)."""

from __future__ import annotations

import pytest


@pytest.fixture
def offline_sim(monkeypatch):
    """Run ``sim()`` offline; returns the ``SyntheticMarket`` class."""
    from .offline_sim import enable_offline_sim

    return enable_offline_sim(monkeypatch)
