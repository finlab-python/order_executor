from copy import deepcopy

from finlab.schemas import PortfolioData

from finlab_online.portfolio import PortfolioSyncManager


def _sample_portfolio_data_dict():
    return {
        "position": {
            "s1": {
                "timestamp": "2026-03-05T09:00:00+00:00",
                "next_trading_time": "2026-03-06T09:00:00+00:00",
                "position": [
                    {
                        "stock_id": "2330",
                        "symbol": "2330",
                        "quantity": 1,
                        "order_condition": 1,
                        "weight": 1.0,
                    }
                ],
                "allocation": 1000000,
                "weight": 1.0,
                "entry_at": "close",
                "exit_at": "close",
                "stop": [],
                "stop_loss": 1,
                "take_profit": None,
                "trail_stop": None,
                "market": "tw_stock",
                "last_market_timestamp": "2026-03-05T13:30:00+08:00",
            }
        },
        "history": {
            "s1": [
                {
                    "timestamp": "2026-03-04T09:00:00+00:00",
                    "next_trading_time": "2026-03-05T09:00:00+00:00",
                    "position": [
                        {
                            "stock_id": "2330",
                            "symbol": "2330",
                            "quantity": 0,
                            "order_condition": 1,
                            "weight": 1.0,
                        }
                    ],
                    "allocation": 1000000,
                    "weight": 1.0,
                    "entry_at": "close",
                    "exit_at": "close",
                    "stop": [],
                    "stop_loss": 1,
                    "take_profit": None,
                    "trail_stop": None,
                    "market": "tw_stock",
                    "last_market_timestamp": "2026-03-04T13:30:00+08:00",
                }
            ]
        },
        "config": {
            "weights": {"s1": 1.0},
            "params": {
                "total_balance": 1000000,
                "rebalance_safety_weight": 0.2,
                "smooth_transition": False,
                "force_override_difference": False,
                "kwargs": {},
            },
            "custom_position": [],
            "excluded_stock_ids": ["9999"],
        },
        "market": None,
    }


def test_get_data_typed_returns_portfolio_data():
    pm = PortfolioSyncManager(deepcopy(_sample_portfolio_data_dict()))

    typed = pm.get_data_typed()

    assert isinstance(typed, PortfolioData)
    assert typed.position["s1"].position[0].symbol == "2330"
    assert typed.history["s1"][0].position[0].quantity == 0


def test_set_data_typed_accepts_dataclass_and_keeps_dict_storage():
    pm = PortfolioSyncManager()
    typed = PortfolioData.from_dict(_sample_portfolio_data_dict())

    pm.set_data_typed(typed)

    assert pm.data["position"]["s1"]["position"][0]["symbol"] == "2330"
    assert pm.data["config"]["weights"]["s1"] == 1.0


def test_get_data_supports_typed_flag():
    pm = PortfolioSyncManager(deepcopy(_sample_portfolio_data_dict()))

    as_dict = pm.get_data()
    as_typed = pm.get_data(typed=True)

    assert isinstance(as_dict, dict)
    assert as_dict["position"]["s1"]["position"][0]["symbol"] == "2330"
    assert isinstance(as_typed, PortfolioData)


def test_set_data_supports_typed_flag_and_rejects_invalid_dict_input():
    pm = PortfolioSyncManager()
    typed = PortfolioData.from_dict(_sample_portfolio_data_dict())

    pm.set_data(typed, typed=True)
    assert pm.data["config"]["weights"]["s1"] == 1.0

    try:
        pm.set_data("invalid")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "data should be dict" in str(e)


def test_set_data_typed_accepts_dict_and_rejects_invalid_input():
    pm = PortfolioSyncManager()

    pm.set_data_typed(deepcopy(_sample_portfolio_data_dict()))
    assert pm.data["position"]["s1"]["position"][0]["symbol"] == "2330"

    try:
        pm.set_data_typed(123)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "dict or schema object" in str(e)


def test_typed_data_round_trip_via_path(tmp_path):
    pm = PortfolioSyncManager(deepcopy(_sample_portfolio_data_dict()))
    path = tmp_path / "phase4.position.json"

    pm.to_path(path)
    loaded = PortfolioSyncManager.from_path(path)

    assert loaded.get_data_typed().to_dict() == pm.get_data_typed().to_dict()


def test_typed_data_round_trip_via_local(tmp_path, monkeypatch):
    monkeypatch.setattr(PortfolioSyncManager, "LOCAL_DIR", str(tmp_path))

    pm = PortfolioSyncManager()
    pm.set_data_typed(PortfolioData.from_dict(_sample_portfolio_data_dict()))
    pm.to_local("phase4")

    loaded = PortfolioSyncManager.from_local("phase4")
    assert loaded.get_data_typed().config.weights == {"s1": 1.0}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_typed_data_round_trip_via_cloud(monkeypatch):
    calls = []

    def fake_post(url, params=None, json=None, timeout=30):
        calls.append({"url": url, "params": params, "json": json, "timeout": timeout})
        if params["action"] == "get":
            return _FakeResponse(deepcopy(_sample_portfolio_data_dict()))
        return _FakeResponse({"ok": True})

    monkeypatch.setattr("finlab.get_token", lambda: ("token", "api_token"))
    monkeypatch.setattr("requests.post", fake_post)

    pm = PortfolioSyncManager()
    pm.set_data_typed(PortfolioData.from_dict(_sample_portfolio_data_dict()))

    set_res = pm.to_cloud("phase4")
    assert set_res.json() == {"ok": True}

    loaded = PortfolioSyncManager.from_cloud("phase4")
    typed = loaded.get_data_typed()

    assert typed.position["s1"].allocation == 1000000
    assert calls[0]["params"]["action"] == "set"
    assert calls[1]["params"]["action"] == "get"
