"""Storage and schema-conversion helpers for ``PortfolioSyncManager``."""

from __future__ import annotations

import copy
import json
import os
from typing import TYPE_CHECKING, Any, TypeAlias, cast

import finlab
import requests
from finlab.compat import is_typed_strict_mode

from .sync_validation import position_type_check, replace_inf_nan
from .validation import normalize_data_payload

if TYPE_CHECKING:
    from finlab.schemas import PortfolioData, PortfolioDataDict

DataPayload: TypeAlias = dict[str, Any]

__all__ = [
    "get_data_payload",
    "get_data_typed",
    "get_local_path",
    "load_cloud_data",
    "load_local_data",
    "load_path_data",
    "normalize_and_check_payload",
    "save_cloud_data",
    "save_local_data",
    "save_path_data",
    "set_data_payload",
    "set_data_typed",
]


def get_local_path(local_dir: str, name: str) -> str:
    if not os.path.exists(local_dir):
        os.makedirs(local_dir)
    return os.path.join(local_dir, f"{name}.position.json")


def load_local_data(name: str, local_dir: str) -> dict[str, Any]:
    return load_path_data(get_local_path(local_dir, name))


def load_cloud_data(name: str, cloud_url: str) -> dict[str, Any]:
    token, token_type = finlab.get_token()
    res = requests.post(
        cloud_url,
        params={"pid": name, token_type: token, "action": "get"},
        timeout=30,
    )

    data = res.json()

    if data is None:
        raise FileNotFoundError(f"path {name} not existed")

    return data


def load_path_data(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"path {path} not existed")

    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_local_data(data: dict[str, Any], name: str, local_dir: str) -> None:
    save_path_data(data, get_local_path(local_dir, name))


def save_cloud_data(
    data: dict[str, Any], name: str, cloud_url: str
) -> requests.Response:
    token, token_type = finlab.get_token()
    return requests.post(
        cloud_url,
        params={"pid": name, token_type: token, "action": "set"},
        json=replace_inf_nan(data),
        timeout=30,
    )


def save_path_data(data: dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, default=str)


def get_data_payload(
    data: dict[str, Any], typed: bool = False
) -> dict[str, Any] | PortfolioData:
    if typed or is_typed_strict_mode():
        return get_data_typed(data)
    return copy.deepcopy(data)


def set_data_payload(data: dict[str, Any] | Any, typed: bool = False) -> dict[str, Any]:
    if is_typed_strict_mode() and not typed:
        raise ValueError(
            "strict mode requires typed data input; use set_data_typed() or set_data(..., typed=True)"
        )

    if typed:
        return set_data_typed(data)

    if not isinstance(data, dict):
        raise ValueError(f"data should be dict, got {type(data)}")

    return normalize_and_check_payload(data)


def get_data_typed(data: dict[str, Any]) -> PortfolioData:
    from finlab.schemas import PortfolioData

    return PortfolioData.from_dict(cast("PortfolioDataDict", copy.deepcopy(data)))


def set_data_typed(data: dict[str, Any] | Any) -> dict[str, Any]:
    from finlab.schemas import PortfolioData

    if isinstance(data, dict):
        payload = PortfolioData.from_dict(
            cast("PortfolioDataDict", copy.deepcopy(data))
        ).to_dict()
    elif hasattr(data, "to_dict"):
        payload = data.to_dict()
    else:
        raise ValueError("data should be dict or schema object with to_dict()")

    return normalize_and_check_payload(cast("dict[str, Any]", payload))


def normalize_and_check_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize *data* and warn about mistyped fields in each strategy position."""
    normalized_data = normalize_data_payload(data)
    for k, v in normalized_data["position"].items():
        position_type_check(k, v)
    return normalized_data
