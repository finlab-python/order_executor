"""Broker-specific account adapters with lazy imports."""

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "BinanceAccount": ("finlab.online.brokers.binance", "BinanceAccount"),
    "EsunAccount": ("finlab.online.brokers.esun", "EsunAccount"),
    "FubonAccount": ("finlab.online.brokers.fubon", "FubonAccount"),
    "FugleAccount": ("finlab.online.brokers.fugle", "FugleAccount"),
    "MasterlinkAccount": ("finlab.online.brokers.masterlink", "MasterlinkAccount"),
    "PocketAccount": ("finlab.online.brokers.pocket", "PocketAccount"),
    "SchwabAccount": ("finlab.online.brokers.schwab", "SchwabAccount"),
    "SinopacAccount": ("finlab.online.brokers.sinopac", "SinopacAccount"),
}

__all__ = [
    "BinanceAccount",
    "EsunAccount",
    "FubonAccount",
    "FugleAccount",
    "MasterlinkAccount",
    "PocketAccount",
    "SchwabAccount",
    "SinopacAccount",
]


def __getattr__(name: str) -> type:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
