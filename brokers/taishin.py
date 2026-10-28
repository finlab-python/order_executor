from __future__ import annotations

from finlab.online.brokers.masterlink import MasterlinkAccount

# TaishinAccount is an alias for MasterlinkAccount (Masterlink merged into Taishin, same SDK)
TaishinAccount = MasterlinkAccount

__all__ = ["MasterlinkAccount", "TaishinAccount"]
