from __future__ import annotations

from finlab.online.brokers.fugle import (
    FugleAccount,
    create_finlab_order,
    to_finlab_stock,
)

# EsunAccount is an alias for FugleAccount (same API, rebranded)
EsunAccount = FugleAccount

__all__ = ["EsunAccount", "FugleAccount", "create_finlab_order", "to_finlab_stock"]
