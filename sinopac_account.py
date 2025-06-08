import shioaji as sj
from shioaji.constant import (
    StockPriceType as SJStockPriceType,
    StockOrderLot as SJStockOrderLot,
    Action as SJAction,
    SecurityType as SJSecurityType,
    Exchange as SJExchange,
    OrderType as SJOrderType,
    Unit as SJUnit,
)
from shioaji.contracts import Stock as SJStock
from shioaji.order import Trade as SJTrade, StockOrder as SJStockOrder
from shioaji.position import StockPosition as SJStockPosition, SettlementV1 as SJSettlementV1
import datetime
import time
import os
import re
import math
import logging
import pandas as pd
from typing import Dict, Optional
from decimal import Decimal

from finlab.online.base_account import Account, Stock, Order, typesafe_op
from finlab.online.utils import estimate_stock_price
from finlab.online.enums import *
from finlab.online.order_executor import Position
from finlab import data
from finlab.markets.tw import TWMarket

logger = logging.getLogger(__name__)

class SinopacAccount(Account):

    required_module = "shioaji"
    module_version = "1.2.5"

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        certificate_person_id: Optional[str] = None,
        certificate_password: Optional[str] = None,
        certificate_path: Optional[str] = None,
    ):

        api_key = api_key or os.getenv("SHIOAJI_API_KEY")
        secret_key = (
            secret_key
            or os.getenv("SHIOAJI_SECRET_KEY")
            or os.getenv("SHIOAJI_API_SECRET")
        )
        certificate_password = certificate_password or os.getenv(
            "SHIOAJI_CERT_PASSWORD"
        )
        certificate_path = certificate_path or os.getenv("SHIOAJI_CERT_PATH")
        certificate_person_id = certificate_person_id or os.getenv(
            "SHIOAJI_CERT_PERSON_ID"
        )

        if api_key is None:
            raise ValueError("api_key must be provided and not None.")
        if secret_key is None:
            raise ValueError("secret_key must be provided and not None.")
        if certificate_person_id is None:
            raise ValueError("certificate_person_id must be provided and not None.")
        if certificate_password is None:
            raise ValueError("certificate_password must be provided and not None.")
        if certificate_path is None:
            raise ValueError("certificate_path must be provided and not None.")
        if not os.path.exists(certificate_path):
            raise ValueError(f"certificate_path {certificate_path} does not exist.")

        self.api = sj.Shioaji()
        self.accounts = self.api.login(api_key, secret_key, fetch_contract=False)

        self.trades: Dict[str, SJTrade] = {}

        self.api.activate_ca(
            ca_path=certificate_path,
            ca_passwd=certificate_password,
            person_id=certificate_person_id,
        )

    def __del__(self):
        try:
            self.api.logout()
        except:
            pass

    def create_order(
        self,
        action,
        stock_id,
        quantity,
        price=None,
        odd_lot=False,
        market_order=False,
        best_price_limit=False,
        order_cond=OrderCondition.CASH,
    ) -> str:

        # contract = self.api.Contracts.Stocks.get(stock_id)
        contract = SJStock(
            security_type=SJSecurityType.Stock,
            code=stock_id,
            exchange=SJExchange.TSE,
        )
        pinfo = self.get_price_info()

        if stock_id not in pinfo:
            # warning
            logging.warning(f"stock {stock_id} not in price info")
            return ""

        limitup = float(pinfo[stock_id]["漲停價"])
        limitdn = float(pinfo[stock_id]["跌停價"])

        if stock_id not in pinfo:
            raise Exception(f"stock {stock_id} not in price info")

        if quantity <= 0:
            raise Exception(f"quantity must be positive, got {quantity}")
        
        if price == None:
            price = self.api.snapshots([contract])[0].close

        price_type = SJStockPriceType.LMT

        if market_order:
            if action == Action.BUY:
                price = limitup
            elif action == Action.SELL:
                price = limitdn

        elif best_price_limit:
            if action == Action.BUY:
                price = limitdn
            elif action == Action.SELL:
                price = limitup

        if action == Action.BUY:
            action = SJAction.Buy
        elif action == Action.SELL:
            action = SJAction.Sell

        daytrade_short = order_cond == OrderCondition.DAY_TRADING_SHORT
        daytrade_short = True if daytrade_short else False

        order_cond = {
            OrderCondition.CASH: "Cash",
            OrderCondition.MARGIN_TRADING: "MarginTrading",
            OrderCondition.SHORT_SELLING: "ShortSelling",
            OrderCondition.DAY_TRADING_LONG: "Cash",
            OrderCondition.DAY_TRADING_SHORT: "Cash",
        }[order_cond]

        order_lot = (
            SJStockOrderLot.IntradayOdd
            if odd_lot
            else SJStockOrderLot.Common
        )
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        if (
            datetime.time(13, 40) < datetime.time(now.hour, now.minute)
            and datetime.time(now.hour, now.minute) < datetime.time(14, 30)
            and odd_lot
        ):
            order_lot = SJStockOrderLot.Odd
        if (
            datetime.time(14, 00) < datetime.time(now.hour, now.minute)
            and datetime.time(now.hour, now.minute) < datetime.time(14, 30)
            and not odd_lot
        ):
            order_lot = SJStockOrderLot.Fixing

        order = self.api.Order(
            price=float(price),
            quantity=quantity,
            action=action,
            price_type=price_type,
            order_type=SJOrderType.ROD,
            order_cond=order_cond,
            daytrade_short=daytrade_short,
            account=self.api.stock_account,
            order_lot=order_lot,
            custom_field="FiNlAB",
        )
        trade = self.api.place_order(contract, order)

        self.trades[trade.status.id] = trade
        return trade.status.id

    def get_price_info(self):
        ref = data.get("reference_price")
        return ref.set_index("stock_id").to_dict(orient="index")

    def update_trades(self):
        if self.api.stock_account is not None:
            self.api.update_status(self.api.stock_account)
        else:
            raise ValueError("SinopacAccount: stock_account is None, please login first.")

        self.trades: Dict[str, SJTrade] = {t.status.id: t for t in self.api.list_trades()}

    def update_order(self, order_id, price=None, quantity=None):
        order = self.get_orders()[order_id]
        trade: SJTrade = self.trades[order_id]

        try:
            order_lot = trade.order.order_lot if isinstance(trade.order, SJStockOrder) else SJStockOrderLot.Common
            if order_lot == SJStockOrderLot.IntradayOdd:
                action = order.action
                stock_id = order.stock_id
                q = typesafe_op(order.quantity, order.filled_quantity, "-")
                q *= 1000

                self.cancel_order(order_id)
                self.create_order(
                    action=action,
                    stock_id=stock_id,
                    quantity=q,
                    price=price,
                    odd_lot=True,
                )
            else:
                if price is None and quantity is None:
                    logger.warning(
                        f"update_order: No price or quantity provided for order {order_id}, skipping update."
                    )
                    return
                
                if price is not None and quantity is None:
                    self.api.update_order(trade, price=float(price))
                elif price is None and quantity is not None:
                    self.api.update_order(trade, qty=int(quantity))

        except ValueError as ve:
            logging.warning(
                f"update_order: Cannot update price of order {order_id}: {ve}"
            )

    def cancel_order(self, order_id):
        self.update_trades()
        self.api.cancel_order(self.trades[order_id])

    def get_position(self):

        if self.api.stock_account is None:
            raise ValueError("SinopacAccount: stock_account is None, please login first.")

        position = self.api.list_positions(
            self.api.stock_account, unit=SJUnit.Share
        )

        order_conditions = {
            "Cash": OrderCondition.CASH,
            "MarginTrading": OrderCondition.MARGIN_TRADING,
            "ShortSelling": OrderCondition.SHORT_SELLING,
        }

        ret = []

        for p in position:
            if not isinstance(p, SJStockPosition):
                continue

            ret.append({
                "stock_id": p.code,
                "quantity": (
                    Decimal(p.quantity) / 1000
                    if p.direction == "Buy"
                    else -Decimal(p.quantity) / 1000
                ),
                "order_condition": order_conditions.get(p.cond, OrderCondition.CASH),
            })
        return Position.from_list(ret)


    def get_orders(self) -> Dict[str, Order]:
        self.update_trades()
        return {t.status.id: trade_to_order(t) for name, t in self.trades.items()}

    def get_stocks(self, stock_ids):
        contracts = [
            SJStock(security_type=SJSecurityType.Stock, code=s, exchange=SJExchange.TSE)
            for s in stock_ids
        ]
        try:
            snapshots = self.api.snapshots(list(contracts))
        except:
            time.sleep(10)
            contracts = [
                SJStock(security_type=SJSecurityType.Stock, code=s, exchange=SJExchange.TSE)
                for s in stock_ids
            ]
            snapshots = self.api.snapshots(list(contracts))

        return {s.code: snapshot_to_stock(s) for s in snapshots}

    def get_total_balance(self) -> int:

        if self.api.stock_account is None:
            raise ValueError("SinopacAccount: stock_account is None, please login first.")

        lp = self.api.list_positions(
            self.api.stock_account, unit=SJUnit.Share
        )

        ac_pos = pd.DataFrame([p.dict() for p in lp])

        if len(ac_pos) == 0:
            return self.get_settlement() + self.get_cash()

        return (
            (
                (ac_pos.last_price * ac_pos.quantity)
                * (1 - 1.425 / 1000)
                * (1 - 3 / 1000)
                - ac_pos.get("margin_purchase_amount", 0)
                - ac_pos.get("interest", 0)
            ).sum()
            + self.get_settlement()
            + self.get_cash()
        )

    def get_cash(self) -> int:
        return int(self.api.account_balance().acc_balance)

    def get_settlement(self) -> int:

        if self.api.stock_account is None:
            raise ValueError("SinopacAccount: stock_account is None, please login first.")

        tw_now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        settlements = self.api.settlements(self.api.stock_account)

        # Settlement time is at 3:00 AM
        def settlement_time(date):
            t = datetime.time(3, 0)
            return datetime.datetime.combine(date, t)
        
        total = 0
        for settlement in settlements:
            if not isinstance(settlement, SJSettlementV1):
                logger.warning(f"Settlement {settlement} is not an instance of SettlementV1, skipping.")
                continue
            if settlement_time(settlement.date) > tw_now:
                total += int(settlement.amount)
        return total

    def sep_odd_lot_order(self):
        return True

    def get_market(self):
        return TWMarket()


def map_trade_status(status):
    return {
        "PendingSubmit": OrderStatus.NEW,
        "PreSubmitted": OrderStatus.NEW,
        "Submitted": OrderStatus.NEW,
        "Failed": OrderStatus.CANCEL,
        "Cancelled": OrderStatus.CANCEL,
        "Filled": OrderStatus.FILLED,
        "Filling": OrderStatus.PARTIALLY_FILLED,
        "PartFilled": OrderStatus.PARTIALLY_FILLED,
    }[status]


def map_order_condition(order_condition):
    return {
        "Cash": OrderCondition.CASH,
        "MarginTrading": OrderCondition.MARGIN_TRADING,
        "ShortSelling": OrderCondition.SHORT_SELLING,
    }[order_condition]


def map_action(action):
    return {"Buy": Action.BUY, "Sell": Action.SELL}[action]


def trade_to_order(trade):
    """將 shioaji package 的委託單轉換成 finlab 格式"""
    action = map_action(trade.order.action)
    status = map_trade_status(trade.status.status)
    order_condition = map_order_condition(trade.order.order_cond)

    # calculate order condition
    if trade.order.daytrade_short == True and order_condition == OrderCondition.CASH:
        order_condition = OrderCondition.DAY_TRADING_SHORT

    # calculate quantity
    # calculate filled quantity
    quantity = Decimal(trade.order.quantity)
    filled_quantity = Decimal(trade.status.deal_quantity)

    if trade.order.order_lot == "IntradayOdd":
        quantity /= 1000
        filled_quantity /= 1000

    return Order(
        **{
            "order_id": trade.status.id,
            "stock_id": trade.contract.code,
            "action": action,
            "price": (
                trade.order.price
                if trade.status.modified_price == 0
                else trade.status.modified_price
            ),
            "quantity": quantity,
            "filled_quantity": filled_quantity,
            "status": status,
            "order_condition": order_condition,
            "time": trade.status.order_datetime,
            "org_order": trade,
        }
    )


def snapshot_to_stock(snapshot):
    """將 shioaji 股價行情轉換成 finlab 格式"""
    d = snapshot
    return Stock(
        stock_id=d.code,
        open=d.open,
        high=d.high,
        low=d.low,
        close=d.close,
        bid_price=d.buy_price,
        ask_price=d.sell_price,
        bid_volume=d.buy_volume,
        ask_volume=d.sell_volume,
    )
