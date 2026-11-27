"""Fixtures for the PortfolioSyncManager tests (they run on top of an installed finlab)."""

from __future__ import annotations

import pytest

from .offline_sim import enable_offline_sim


@pytest.fixture
def offline_sim(monkeypatch):
    """Run ``sim()`` offline."""
    enable_offline_sim(monkeypatch)
