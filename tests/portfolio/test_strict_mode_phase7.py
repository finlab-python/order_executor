from copy import deepcopy

import pytest
from finlab.schemas import PortfolioData

from finlab_online.portfolio import PortfolioSyncManager


@pytest.fixture
def sample_portfolio_data():
    return {
        "position": {},
        "history": {},
        "config": {"weights": {}, "params": {}},
        "market": None,
    }


def test_portfolio_sync_manager_get_data_defaults_to_typed_in_strict_mode(
    monkeypatch, sample_portfolio_data
):
    monkeypatch.setenv("FINLAB_TYPED_STRICT", "1")

    pm = PortfolioSyncManager(deepcopy(sample_portfolio_data))
    out = pm.get_data()

    assert isinstance(out, PortfolioData)


def test_portfolio_sync_manager_set_data_rejects_legacy_dict_in_strict_mode(
    monkeypatch, sample_portfolio_data
):
    monkeypatch.setenv("FINLAB_TYPED_STRICT", "1")

    pm = PortfolioSyncManager()
    with pytest.raises(ValueError, match="strict mode"):
        pm.set_data(deepcopy(sample_portfolio_data))


def test_portfolio_sync_manager_set_data_typed_still_works_in_strict_mode(
    monkeypatch, sample_portfolio_data
):
    monkeypatch.setenv("FINLAB_TYPED_STRICT", "1")

    pm = PortfolioSyncManager()
    pm.set_data_typed(PortfolioData.from_dict(deepcopy(sample_portfolio_data)))

    assert pm.data["config"]["weights"] == {}
