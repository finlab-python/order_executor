"""Broker-specific account adapters with lazy imports."""

from importlib import import_module
from typing import Dict, Tuple

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "BinanceAccount": ("finlab.online.brokers.binance", "BinanceAccount"),
    "EsunAccount": ("finlab.online.brokers.esun", "EsunAccount"),
    "FubonAccount": ("finlab.online.brokers.fubon", "FubonAccount"),
    "FugleAccount": ("finlab.online.brokers.fugle", "FugleAccount"),
    "MasterlinkAccount": ("finlab.online.brokers.masterlink", "MasterlinkAccount"),
    "PocketAccount": ("finlab.online.brokers.pocket", "PocketAccount"),
    "SchwabAccount": ("finlab.online.brokers.schwab", "SchwabAccount"),
    "SinopacAccount": ("finlab.online.brokers.sinopac", "SinopacAccount"),
}

__all__ = sorted(_EXPORTS.keys())


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
