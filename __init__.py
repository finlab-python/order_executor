"""Public API for finlab_online with stable import paths."""

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
        return importlib.import_module("finlab_online.brokers.pocket").PocketAccount
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Legacy import paths (e.g. finlab_online.sinopac_account) redirected to
# their real locations.  Broker modules load lazily — heavy deps like
# shioaji are only pulled in when actually used.
_MODULE_ALIASES: dict[str, str] = {
    "finlab_online.base_account": "finlab_online.core.account",
    "finlab_online.order_executor": "finlab_online.core.executor",
    "finlab_online.enums": "finlab_online.core.enums",
    "finlab_online.position": "finlab_online.core.position",
    "finlab_online.utils": "finlab_online.core.utils",
    "finlab_online.sinopac_account": "finlab_online.brokers.sinopac",
    "finlab_online.fugle_account": "finlab_online.brokers.fugle",
    "finlab_online.esun_account": "finlab_online.brokers.esun",
    "finlab_online.fubon_account": "finlab_online.brokers.fubon",
    "finlab_online.kgi_account": "finlab_online.brokers.kgi",
    "finlab_online.masterlink_account": "finlab_online.brokers.masterlink",
    "finlab_online.taishin_account": "finlab_online.brokers.taishin",
    "finlab_online.yuanta_account": "finlab_online.brokers.yuanta",
    "finlab_online.binance_account": "finlab_online.brokers.binance",
    "finlab_online.pocket_account": "finlab_online.brokers.pocket",
    "finlab_online.schwab_account": "finlab_online.brokers.schwab",
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
