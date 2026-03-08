import shioaji as sj
from shioaji.constant import (
    StockPriceType as SJStockPriceType,
    StockOrderLot as SJStockOrderLot,
    Action as SJAction,
    SecurityType as SJSecurityType,
    Exchange as SJExchange,
    OrderType as SJOrderType,
    Unit as SJUnit,
    OrderState as SJOrderState,
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

from finlab.online.core.account import Account, Stock, Order, typesafe_op
from finlab.online.core.utils import estimate_stock_price
from finlab.online.core.enums import *
from finlab.online.core.position import Position
from finlab.online.core.realtime_models import (
    BalanceUpdate,
    BidAsk,
    ConnectionState,
    Fill,
    OrderUpdate,
    Tick,
)
from finlab.online.core.realtime_normalizers import (
    finalize_backfilled_ticks,
    get_field_value,
    get_first_valid_float,
    normalize_backfill_window,
    to_optional_datetime,
    to_optional_float,
)
from finlab.online.core.realtime_provider import RealtimeProvider
from finlab import data
from finlab.markets.tw import TWMarket

logger = logging.getLogger(__name__)

class SinopacAccount(Account, RealtimeProvider):

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

        self._init_realtime()

    # ── RealtimeProvider implementation ──────────────────────────────

    @staticmethod
    def _parse_callback_time(payload):
        order_datetime = get_field_value(payload, "order_datetime")
        if isinstance(order_datetime, datetime.datetime):
            return order_datetime

        msg_datetime = get_field_value(payload, "datetime")
        if isinstance(msg_datetime, datetime.datetime):
            return msg_datetime

        ts = to_optional_float(get_field_value(payload, "ts"))
        if ts is not None:
            try:
                if ts >= 10**12:  # milliseconds
                    return datetime.datetime.fromtimestamp(ts / 1000)
                return datetime.datetime.fromtimestamp(ts)
            except (OSError, OverflowError, ValueError):
                pass

        return datetime.datetime.now()

    @staticmethod
    def _map_callback_action(raw_action):
        text = str(raw_action).upper()
        if text in ("BUY", "ACTION.BUY", "B"):
            return Action.BUY
        if text in ("SELL", "ACTION.SELL", "S"):
            return Action.SELL
        return Action.SELL

    @staticmethod
    def _map_callback_order_condition(raw_order_condition):
        if raw_order_condition is None:
            return OrderCondition.CASH
        try:
            return map_order_condition(str(raw_order_condition))
        except Exception:
            return OrderCondition.CASH

    def _build_order_update_from_callback(self, payload):
        order_id = str(
            get_field_value(payload, "id")
            or get_field_value(payload, "ordno")
            or get_field_value(payload, "seqno")
            or ""
        )
        stock_id = str(
            get_field_value(payload, "code")
            or get_field_value(payload, "symbol")
            or ""
        )
        quantity = get_first_valid_float(payload, "quantity", "order_quantity") or 0.0
        filled_quantity = get_first_valid_float(payload, "deal_quantity", "filled_qty") or 0.0
        price = get_first_valid_float(payload, "price", "modified_price", "avg_price") or 0.0

        status_raw = get_field_value(payload, "status")
        try:
            status = map_trade_status(str(status_raw))
        except Exception:
            status = OrderStatus.NEW

        cancel_quantity = get_first_valid_float(payload, "cancel_quantity") or 0.0
        operation = "new"
        if cancel_quantity > 0:
            operation = "cancel"
        elif get_first_valid_float(payload, "modified_price") not in (None, 0):
            operation = "update_price"

        return OrderUpdate(
            order_id=order_id,
            stock_id=stock_id,
            action=self._map_callback_action(get_field_value(payload, "action")),
            price=price,
            quantity=quantity,
            filled_quantity=filled_quantity,
            status=status,
            order_condition=self._map_callback_order_condition(
                get_field_value(payload, "order_cond")
            ),
            time=self._parse_callback_time(payload),
            operation=operation,
            org_event=payload,
        )

    def _build_fill_from_callback(self, payload):
        order_id = str(
            get_field_value(payload, "seqno")
            or get_field_value(payload, "ordno")
            or get_field_value(payload, "id")
            or ""
        )
        stock_id = str(
            get_field_value(payload, "code")
            or get_field_value(payload, "symbol")
            or ""
        )
        return Fill(
            order_id=order_id,
            stock_id=stock_id,
            action=self._map_callback_action(get_field_value(payload, "action")),
            price=get_first_valid_float(payload, "price", "avg_price") or 0.0,
            quantity=get_first_valid_float(payload, "quantity", "deal_quantity") or 0.0,
            time=self._parse_callback_time(payload),
            org_event=payload,
        )

    def _get_realtime_balance(self):
        account_id = ""
        if self.api.stock_account is not None:
            account_id = str(
                getattr(self.api.stock_account, "account_id", "")
                or getattr(self.api.stock_account, "account", "")
            )

        cash = to_optional_float(self.get_cash())
        settlement = to_optional_float(self.get_settlement())
        total_balance = to_optional_float(self.get_total_balance())

        return BalanceUpdate(
            account_id=account_id,
            broker=self.__class__.__name__,
            available_balance=cash,
            cash=cash,
            settlement=settlement,
            total_balance=total_balance,
            time=datetime.datetime.now(),
        )

    def connect_realtime(self) -> None:
        if self._realtime_connected:
            return

        @self.api.on_tick_stk_v1()
        def _on_tick(exchange, tick):
            native_pct_change = get_first_valid_float(
                tick,
                "pct_chg",
                "pct_change",
                "change_percent",
                "change_pct",
            )
            prev_close = get_first_valid_float(
                tick,
                "prev_close",
                "reference",
                "reference_price",
                "yesterday_close",
            )
            self._emit_tick(Tick(
                stock_id=tick.code,
                price=tick.close,
                volume=tick.volume,
                total_volume=tick.total_volume,
                time=tick.datetime,
                open=tick.open,
                high=tick.high,
                low=tick.low,
                avg_price=tick.avg_price,
                tick_type=tick.tick_type,
                prev_close=prev_close,
                pct_change=native_pct_change,
                source="trade",
            ))

        @self.api.on_bidask_stk_v1()
        def _on_bidask(exchange, bidask):
            self._emit_bidask(BidAsk(
                stock_id=bidask.code,
                bid_prices=list(bidask.bid_price),
                bid_volumes=list(bidask.bid_volume),
                ask_prices=list(bidask.ask_price),
                ask_volumes=list(bidask.ask_volume),
                time=bidask.datetime,
            ))

        def _order_cb(stat, msg):
            try:
                state_value = str(getattr(stat, "value", stat))
                state_value = state_value.upper()

                if state_value in {
                    SJOrderState.StockDeal.value,
                    SJOrderState.FuturesDeal.value,
                    "SDEAL",
                    "FDEAL",
                }:
                    self._emit_fill(self._build_fill_from_callback(msg))
                    return

                if state_value in {
                    SJOrderState.StockOrder.value,
                    SJOrderState.FuturesOrder.value,
                    "SORDER",
                    "FORDER",
                }:
                    self._emit_order_update(self._build_order_update_from_callback(msg))
                    return

                # Unknown state fallback (older SDK payloads)
                if get_field_value(msg, "deal_quantity") not in (None, 0):
                    self._emit_fill(self._build_fill_from_callback(msg))
                else:
                    self._emit_order_update(self._build_order_update_from_callback(msg))
            except Exception:
                logger.exception("Sinopac order callback parsing error")
        self.api.set_order_callback(_order_cb)

        @self.api.quote.on_event
        def _event_cb(resp_code, event_code, info, event):
            state_map = {
                0: ConnectionState.CONNECTED,
                -1: ConnectionState.DISCONNECTED,
            }
            state = state_map.get(resp_code, ConnectionState.ERROR)
            self._emit_connection(state, str(event))

        self._realtime_connected = True
        self._emit_connection(ConnectionState.CONNECTED)
        logger.info("Sinopac realtime connected")

    def disconnect_realtime(self) -> None:
        if not self._realtime_connected:
            return
        self.unsubscribe_balances()
        self._realtime_connected = False
        self._emit_connection(ConnectionState.DISCONNECTED)
        logger.info("Sinopac realtime disconnected")

    def subscribe_ticks(self, stock_ids):
        for sid in stock_ids:
            contract = SJStock(
                security_type=SJSecurityType.Stock,
                code=sid,
                exchange=SJExchange.TSE,
            )
            self.api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.Tick)

    def unsubscribe_ticks(self, stock_ids):
        for sid in stock_ids:
            contract = SJStock(
                security_type=SJSecurityType.Stock,
                code=sid,
                exchange=SJExchange.TSE,
            )
            self.api.quote.unsubscribe(contract, quote_type=sj.constant.QuoteType.Tick)

    def subscribe_bidask(self, stock_ids):
        for sid in stock_ids:
            contract = SJStock(
                security_type=SJSecurityType.Stock,
                code=sid,
                exchange=SJExchange.TSE,
            )
            self.api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.BidAsk)

    def unsubscribe_bidask(self, stock_ids):
        for sid in stock_ids:
            contract = SJStock(
                security_type=SJSecurityType.Stock,
                code=sid,
                exchange=SJExchange.TSE,
            )
            self.api.quote.unsubscribe(contract, quote_type=sj.constant.QuoteType.BidAsk)

    def backfill_ticks(self, stock_ids, start_time=None, end_time=None, emit=True):
        start_filter, end_filter = normalize_backfill_window(start_time, end_time)
        session_date = datetime.datetime.now().date()
        session_date_str = session_date.strftime("%Y-%m-%d")
        backfilled = {}

        for stock_id in stock_ids:
            ticks = []
            try:
                contract = SJStock(
                    security_type=SJSecurityType.Stock,
                    code=stock_id,
                    exchange=SJExchange.TSE,
                )
                ticks_data = self.api.ticks(contract, date=session_date_str)
                prices = list(getattr(ticks_data, "close", []) or [])
                volumes = list(getattr(ticks_data, "volume", []) or [])
                timestamps = list(getattr(ticks_data, "ts", []) or [])
                tick_types = list(getattr(ticks_data, "tick_type", []) or [])

                running_total = 0
                for ts_value, price, volume, tick_type in zip(
                    timestamps,
                    prices,
                    volumes,
                    tick_types,
                ):
                    tick_time = to_optional_datetime(ts_value, default_date=session_date)
                    if tick_time is None:
                        continue
                    current_time = tick_time.time()
                    if start_filter is not None and current_time < start_filter:
                        continue
                    if end_filter is not None and current_time > end_filter:
                        continue

                    running_total += int(volume or 0)
                    ticks.append(
                        Tick(
                            stock_id=stock_id,
                            price=float(price or 0.0),
                            volume=int(volume or 0),
                            total_volume=running_total,
                            time=tick_time,
                            tick_type=int(tick_type or 0),
                            source="trade",
                        )
                    )

                ticks = finalize_backfilled_ticks(ticks)

            except Exception:
                logger.exception("backfill_ticks: unable to backfill intraday ticks for %s", stock_id)
                ticks = []

            backfilled[stock_id] = ticks
            if emit:
                for tick in ticks:
                    self._emit_tick(tick)

        return backfilled

    # ── End RealtimeProvider ──────────────────────────────────────

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
