from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from finlab_online.portfolio.sync_storage import (
    get_data_payload,
    get_local_path,
    load_cloud_data,
    load_local_data,
    load_path_data,
    save_cloud_data,
    save_local_data,
    save_path_data,
    set_data_payload,
    set_data_typed,
)

pytestmark = pytest.mark.unit


def _portfolio_payload() -> dict[str, object]:
    return {
        "position": {
            "alpha": {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "next_trading_time": "2026-01-02T00:00:00+00:00",
                "position": [
                    {"symbol": "2330", "quantity": 1, "order_condition": "CASH"}
                ],
                "allocation": 100000.0,
                "weight": 1.0,
                "entry_at": "close",
                "exit_at": "close",
                "stop": [],
                "stop_loss": None,
                "take_profit": None,
                "trail_stop": None,
                "market": "tw_stock",
            }
        },
        "history": {},
        "config": {},
        "market": None,
    }


def test_get_local_path_creates_directory(tmp_path: Path) -> None:
    path = get_local_path(str(tmp_path / "positions"), "demo")
    assert Path(path).parent.exists()
    assert path.endswith("demo.position.json")


def test_local_and_path_roundtrip(tmp_path: Path) -> None:
    payload = _portfolio_payload()
    local_dir = tmp_path / "local"
    path = tmp_path / "manual.json"

    save_local_data(payload, "demo", str(local_dir))
    save_path_data(payload, str(path))

    assert load_local_data("demo", str(local_dir)) == payload
    assert load_path_data(str(path)) == payload


def test_load_cloud_data_uses_dynamic_token_param() -> None:
    response = MagicMock()
    response.json.return_value = {"position": {}}

    with (
        patch(
            "finlab_online.portfolio.sync_storage.finlab.get_token",
            return_value=("tok", "api_token"),
        ),
        patch(
            "finlab_online.portfolio.sync_storage.requests.post", return_value=response
        ) as mock_post,
    ):
        payload = load_cloud_data("demo", "https://cloud.example")

    assert payload == {"position": {}}
    assert mock_post.call_args.kwargs["params"] == {
        "pid": "demo",
        "api_token": "tok",
        "action": "get",
    }


def test_load_cloud_data_none_payload_raises() -> None:
    response = MagicMock()
    response.json.return_value = None

    with (
        patch(
            "finlab_online.portfolio.sync_storage.finlab.get_token",
            return_value=("tok", "api_token"),
        ),
        patch(
            "finlab_online.portfolio.sync_storage.requests.post", return_value=response
        ),
        pytest.raises(FileNotFoundError, match=r"path demo not existed"),
    ):
        load_cloud_data("demo", "https://cloud.example")


def test_save_cloud_data_replaces_inf_nan() -> None:
    response = MagicMock()

    with (
        patch(
            "finlab_online.portfolio.sync_storage.finlab.get_token",
            return_value=("tok", "api_token"),
        ),
        patch(
            "finlab_online.portfolio.sync_storage.requests.post", return_value=response
        ) as mock_post,
    ):
        save_cloud_data({"weight": float("inf")}, "demo", "https://cloud.example")

    assert mock_post.call_args.kwargs["json"] == {"weight": None}


def test_set_data_payload_respects_strict_mode() -> None:
    with (
        patch(
            "finlab_online.portfolio.sync_storage.is_typed_strict_mode",
            return_value=True,
        ),
        pytest.raises(ValueError, match="strict mode requires typed data input"),
    ):
        set_data_payload(_portfolio_payload())


def test_set_data_typed_normalizes_schema_dict() -> None:
    normalized = set_data_typed(_portfolio_payload())
    position = normalized["position"]["alpha"]["position"][0]

    assert position["symbol"] == "2330"
    assert position["quantity"] == 1


def test_get_data_payload_returns_schema_when_typed_requested() -> None:
    typed = get_data_payload(_portfolio_payload(), typed=True)
    assert typed.to_dict()["position"]["alpha"]["position"][0]["symbol"] == "2330"
