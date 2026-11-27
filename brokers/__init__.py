"""Broker-specific account adapters with lazy imports."""

from importlib import import_module

_EXPORTS: dict[str, str] = {
    "BinanceAccount": ".binance",
    "EsunAccount": ".esun",
    "FubonAccount": ".fubon",
    "FugleAccount": ".fugle",
    "KGIAccount": ".kgi",
    "MasterlinkAccount": ".masterlink",
    "PocketAccount": ".pocket",
    "SchwabAccount": ".schwab",
    "SinopacAccount": ".sinopac",
    "TaishinAccount": ".taishin",
    "YuantaAccount": ".yuanta",
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

    value = getattr(import_module(_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value
