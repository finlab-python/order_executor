"""
玉山證券 E.SUN Securities Trading Account

This module provides the EsunAccount class for trading with E.SUN Securities.
It is an alias for FugleAccount, as E.SUN Securities uses the same API 
(migrated from fugle_trade to esun_trade).

For migration guide, see: https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/migration_guide/
"""

from finlab.online.fugle_account import FugleAccount, create_finlab_order, to_finlab_stock

# EsunAccount is an alias for FugleAccount (same API, rebranded)
EsunAccount = FugleAccount

__all__ = ['EsunAccount', 'FugleAccount', 'create_finlab_order', 'to_finlab_stock']

