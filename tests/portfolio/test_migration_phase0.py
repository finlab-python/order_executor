from finlab.portfolio import Portfolio

from finlab_online.portfolio import PortfolioSyncManager


def _make_empty_portfolio():
    class _EmptyPortfolio(Portfolio):
        def __init__(self):
            # Keep this lightweight for schema guardrail tests.
            self.position_schedulers = {}

    return _EmptyPortfolio()


def test_portfolio_sync_manager_config_params_shape_is_stable():
    pm = PortfolioSyncManager()
    pm.update(
        _make_empty_portfolio(),
        total_balance=123456,
        rebalance_safety_weight=0.35,
        smooth_transition=True,
        force_override_difference=True,
        odd_lot=True,
    )

    assert set(pm.data["config"].keys()) == {"weights", "params"}
    assert pm.data["config"]["weights"] == {}

    params = pm.data["config"]["params"]
    assert set(params.keys()) == {
        "total_balance",
        "rebalance_safety_weight",
        "smooth_transition",
        "force_override_difference",
        "kwargs",
    }
    assert params["total_balance"] == 123456
    assert params["rebalance_safety_weight"] == 0.35
    assert params["smooth_transition"] is True
    assert params["force_override_difference"] is True
    assert params["kwargs"] == {"odd_lot": True}


def test_portfolio_sync_manager_config_keeps_custom_and_excluded_fields():
    pm = PortfolioSyncManager()
    pm.update(
        _make_empty_portfolio(),
        total_balance=1,
        custom_position={"2454": 1},
        excluded_stock_ids=["2454"],
    )

    assert "custom_position" in pm.data["config"]
    assert "excluded_stock_ids" in pm.data["config"]
    custom = pm.data["config"]["custom_position"]
    assert isinstance(custom, list)
    assert len(custom) == 1
    assert custom[0]["symbol"] == "2454"
    assert custom[0]["stock_id"] == "2454"
    assert pm.data["config"]["excluded_stock_ids"] == ["2454"]
