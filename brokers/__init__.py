"""Broker-specific account adapters with lazy imports."""

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "BinanceAccount": ("finlab_online.brokers.binance", "BinanceAccount"),
    "EsunAccount": ("finlab_online.brokers.esun", "EsunAccount"),
    "FubonAccount": ("finlab_online.brokers.fubon", "FubonAccount"),
    "FugleAccount": ("finlab_online.brokers.fugle", "FugleAccount"),
    "KGIAccount": ("finlab_online.brokers.kgi", "KGIAccount"),
    "MasterlinkAccount": ("finlab_online.brokers.masterlink", "MasterlinkAccount"),
    "PocketAccount": ("finlab_online.brokers.pocket", "PocketAccount"),
    "SchwabAccount": ("finlab_online.brokers.schwab", "SchwabAccount"),
    "SinopacAccount": ("finlab_online.brokers.sinopac", "SinopacAccount"),
    "TaishinAccount": ("finlab_online.brokers.taishin", "TaishinAccount"),
    "YuantaAccount": ("finlab_online.brokers.yuanta", "YuantaAccount"),
}

__all__ = [
    "BinanceAccount",
    "EsunAccount",
    "FubonAccount",
    "FugleAccount",
    "KGIAccount",
    "MasterlinkAccount",
    "PocketAccount",
    "SchwabAccount",
    "SinopacAccount",
    "TaishinAccount",
    "YuantaAccount",
]


def __getattr__(name: str) -> type:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
