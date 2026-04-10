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

# Legacy import paths (e.g. finlab.online.sinopac_account) redirected to
# their real locations.  Broker modules load lazily — heavy deps like
# shioaji are only pulled in when actually used.
_MODULE_ALIASES: dict[str, str] = {
    "finlab.online.base_account": "finlab.online.core.account",
    "finlab.online.order_executor": "finlab.online.core.executor",
    "finlab.online.enums": "finlab.online.core.enums",
    "finlab.online.position": "finlab.online.core.position",
    "finlab.online.utils": "finlab.online.core.utils",
    "finlab.online.sinopac_account": "finlab.online.brokers.sinopac",
    "finlab.online.fugle_account": "finlab.online.brokers.fugle",
    "finlab.online.esun_account": "finlab.online.brokers.esun",
    "finlab.online.fubon_account": "finlab.online.brokers.fubon",
    "finlab.online.masterlink_account": "finlab.online.brokers.masterlink",
    "finlab.online.binance_account": "finlab.online.brokers.binance",
    "finlab.online.pocket_account": "finlab.online.brokers.pocket",
    "finlab.online.schwab_account": "finlab.online.brokers.schwab",
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
