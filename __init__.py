"""Public API for finlab.online with stable import paths."""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Sequence

from .core import (
    Account,
    Action,
    Order,
    OrderCondition,
    OrderExecutor,
    OrderStatus,
    Position,
    Stock,
    calculate_price_with_extra_bid,
    typesafe_op,
)

__all__ = [
    "Account",
    "Action",
    "Order",
    "OrderCondition",
    "OrderExecutor",
    "OrderStatus",
    "Position",
    "Stock",
    "calculate_price_with_extra_bid",
    "typesafe_op",
]


def __getattr__(name: str) -> type:
    if name == "PocketAccount":
        return importlib.import_module(".brokers.pocket", __name__).PocketAccount
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Legacy import paths (e.g. finlab.online.sinopac_account) redirected to
# their real locations.  Broker modules load lazily — heavy deps like
# shioaji are only pulled in when actually used.
_MODULE_ALIASES: dict[str, str] = {
    f"{__name__}.{old}": f"{__name__}.{new}"
    for old, new in {
        "base_account": "core.account",
        "order_executor": "core.executor",
        "enums": "core.enums",
        "position": "core.position",
        "utils": "core.utils",
        "sinopac_account": "brokers.sinopac",
        "fugle_account": "brokers.fugle",
        "esun_account": "brokers.esun",
        "fubon_account": "brokers.fubon",
        "kgi_account": "brokers.kgi",
        "masterlink_account": "brokers.masterlink",
        "taishin_account": "brokers.taishin",
        "yuanta_account": "brokers.yuanta",
        "binance_account": "brokers.binance",
        "pocket_account": "brokers.pocket",
        "schwab_account": "brokers.schwab",
    }.items()
}


class _AliasImporter:
    """Meta-path finder that redirects legacy module names on first use."""

    def find_spec(
        self,
        fullname: str,
        path: "Sequence[str] | None" = None,
        target: "types.ModuleType | None" = None,
    ) -> "importlib.machinery.ModuleSpec | None":
        if fullname in _MODULE_ALIASES:
            return importlib.util.spec_from_loader(fullname, loader=self)
        return None

    def create_module(
        self, spec: importlib.machinery.ModuleSpec
    ) -> "types.ModuleType":
        return importlib.import_module(_MODULE_ALIASES[spec.name])

    def exec_module(self, module: "types.ModuleType") -> None:
        pass


if not any(isinstance(f, _AliasImporter) for f in sys.meta_path):
    sys.meta_path.append(_AliasImporter())
