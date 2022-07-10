from enum import Enum

OrderStatus = Enum('OrderStatus', 'NEW PARTIALLY_FILLED FILLED CANCEL')

Action = Enum('Action', 'BUY SELL')

OrderCondition = Enum('OrderCondition', 'CASH MARGIN_TRADING SHORT_SELLING DAY_TRADING_LONG DAY_TRADING_SHORT')
