"""Broker-specific account adapters with lazy imports."""

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "BinanceAccount": (".binance", "BinanceAccount"),
    "EsunAccount": (".esun", "EsunAccount"),
    "FubonAccount": (".fubon", "FubonAccount"),
    "FugleAccount": (".fugle", "FugleAccount"),
    "KGIAccount": (".kgi", "KGIAccount"),
    "MasterlinkAccount": (".masterlink", "MasterlinkAccount"),
    "PocketAccount": (".pocket", "PocketAccount"),
    "SchwabAccount": (".schwab", "SchwabAccount"),
    "SinopacAccount": (".sinopac", "SinopacAccount"),
    "TaishinAccount": (".taishin", "TaishinAccount"),
    "YuantaAccount": (".yuanta", "YuantaAccount"),
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
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
