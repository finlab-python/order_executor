from __future__ import annotations

import contextlib
import datetime
import logging
import os
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import kgisuperpy as kgi

from finlab.markets.tw import TWMarket
from finlab.online.core.account import Account, Order, Stock
from finlab.online.core.enums import Action, OrderCondition, OrderStatus
from finlab.online.core.position import Position
from finlab.online.core.realtime_normalizers import calculate_tick_pct_change

logger = logging.getLogger(__name__)

_FROM_KGI_ACTION = {kgi.Action.Buy: Action.BUY, kgi.Action.Sell: Action.SELL}

_TO_KGI_COND = {
    OrderCondition.CASH: kgi.OrderCond.CASH,
    OrderCondition.MARGIN_TRADING: kgi.OrderCond.MARGIN,
    OrderCondition.SHORT_SELLING: kgi.OrderCond.SHORT_SELLING,
    OrderCondition.DAY_TRADING_LONG: kgi.OrderCond.CASH,
    OrderCondition.DAY_TRADING_SHORT: kgi.OrderCond.CASH_SELLING,
}

_FROM_KGI_COND = {
    kgi.OrderCond.CASH: OrderCondition.CASH,
    kgi.OrderCond.MARGIN: OrderCondition.MARGIN_TRADING,
    kgi.OrderCond.MARGIN_DayTrade: OrderCondition.MARGIN_TRADING,
    kgi.OrderCond.SHORT_SELLING: OrderCondition.SHORT_SELLING,
    kgi.OrderCond.SHORT_DayTrade: OrderCondition.SHORT_SELLING,
    kgi.OrderCond.Lend_SELLING: OrderCondition.SHORT_SELLING,
    kgi.OrderCond.CASH_SELLING: OrderCondition.DAY_TRADING_SHORT,
}

_ODD_LOTS = (kgi.OddLot.Odd, kgi.OddLot.Odd_AfterMarket)
_DONE = (
    kgi.Status.Filled,
    kgi.Status.Cancelled,
    kgi.Status.PartFilled_Cancelled,
    kgi.Status.Failed,
)


class KGIAccount(Account):
    """凱基證券帳戶，使用官方 ``kgisuperpy`` SDK（``pip install kgisuperpy``）。

    下單與帳務只支援 Windows 與 Linux（SDK 沒有 macOS 的下單元件），Python 3.9～3.14。
    使用前要先申請憑證並完成 API 申請與測試：
    https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/prefix

    數量單位：整股與盤後定價以張計，零股以股計（與 OrderExecutor 傳入的一致）。
    """

    required_module = "kgisuperpy"

    def __init__(
        self,
        person_id: str | None = None,
        password: str | None = None,
        account: str | None = None,
        simulation: bool = False,
    ) -> None:
        person_id = person_id or os.environ.get("KGI_PERSON_ID")
        password = password or os.environ.get("KGI_PASSWORD")
        account = account or os.environ.get("KGI_ACCOUNT")
        if not person_id or not password:
            raise ValueError(
                "請設定凱基身分證字號與登入密碼：KGI_PERSON_ID、KGI_PASSWORD"
            )

        # kgisuperpy 預設 simulation=True（模擬環境），一定要明確傳入
        self.api = kgi.login(person_id, password, simulation)
        # 登入失敗時 SDK 只印訊息，不會掛上 set_Account
        if not hasattr(self.api, "set_Account"):
            raise ConnectionError("凱基登入失敗，請確認帳號密碼、憑證與 API 申請狀態")

        accounts = [
            a["account"] for a in self.api.show_account() if a["account_flag"] == "證券"
        ]
        if not accounts:
            raise ValueError("這個身分證字號下沒有凱基證券帳號")
        if account is None:
            account = accounts[0]
        elif account not in accounts:
            raise ValueError(f"找不到凱基證券帳號 {account}，可用的帳號：{accounts}")
        self.api.set_Account(account)
        # SDK 預設把每則委託回報 print 出來
        self.api.Order.set_event(logger.debug)

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.api.logout()

    def create_order(
        self,
        action: Action,
        stock_id: str,
        quantity: float,
        price: float | None = None,
        odd_lot: bool = False,
        market_order: bool = False,
        best_price_limit: bool = False,
        order_cond: OrderCondition = OrderCondition.CASH,
    ) -> str | None:
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        return self._place(
            action,
            stock_id,
            int(quantity),
            price,
            _TO_KGI_COND[order_cond],
            odd_lot=odd_lot,
            market_order=market_order,
            best_price_limit=best_price_limit,
        )

    def _place(
        self,
        action: Action,
        stock_id: str,
        qty: int,
        price: Any,
        cond: Any,
        *,
        odd_lot: bool = False,
        market_order: bool = False,
        best_price_limit: bool = False,
    ) -> str | None:
        is_buy = action == Action.BUY
        # 盤別依台北時間判斷，不用 SDK 以分鐘比對的自動判斷（14:00 整會送成整股盤中）
        now = datetime.datetime.now(TWMarket.tzinfo()).time()
        if odd_lot:
            after_hours = datetime.time(13, 40) <= now < datetime.time(14, 30)
            lot = kgi.OddLot.Odd_AfterMarket if after_hours else kgi.OddLot.Odd
        elif datetime.time(14, 0) <= now < datetime.time(14, 30):
            lot = kgi.OddLot.Fixing
        else:
            lot = kgi.OddLot.Common

        # 一律送限價：SDK 依交易所回報重建價格種類，漲跌停旗標的委託之後可能無法改單或刪單
        snapshot = None
        if (
            lot == kgi.OddLot.Fixing
            or market_order
            or best_price_limit
            or price is None
        ):
            snapshot = self._snapshots([stock_id]).get(stock_id)
            if snapshot is None:
                logger.warning(f"create_order: 查不到 {stock_id} 的報價，不送單")
                return None

        if lot == kgi.OddLot.Fixing:
            # 盤後定價只以收盤價成交：芭樂價或比收盤價差的限價不送、不中斷，
            # 呼叫端可能已先撤單，後面的單要照常下
            close = float(snapshot.price)
            if best_price_limit or (
                not market_order
                and price is not None
                and (float(price) < close if is_buy else float(price) > close)
            ):
                logger.warning(
                    f"create_order: 盤後定價只以收盤價成交，{stock_id} 的芭樂價或比收盤價差的限價不送單"
                )
                return None
            order_price = close
        elif market_order:
            order_price = snapshot.limit_up if is_buy else snapshot.limit_down
        elif best_price_limit:
            order_price = snapshot.limit_down if is_buy else snapshot.limit_up
        elif price is None:
            order_price = snapshot.price
        else:
            order_price = price

        trade = self.api.Order.create_order(
            action=kgi.Action.Buy if is_buy else kgi.Action.Sell,
            symbol=stock_id,
            qty=qty,
            price=float(order_price),
            time_in_force=kgi.TimeInForce.ROD,
            order_cond=cond,
            odd_lot=lot,
        )
        # 委託書號由交易所回報後才填上
        if trade is None or not self._wait(
            lambda: trade.order.order_id is not None, trade.operations[0]
        ):
            logger.warning(f"create_order: 凱基委託 {stock_id} 失敗或未收到回報")
            return None
        return trade.order.order_id

    @staticmethod
    def _wait(done: Callable[[], bool], operation: Any, timeout: float = 10) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if done():
                return True
            if operation.status == kgi.Status.Failed:
                return False
            time.sleep(0.1)
        return done()

    def update_order(
        self,
        order_id: str,
        price: float | None = None,
        quantity: float | None = None,
    ) -> str | None:
        trade = self.api.Order.get_trades().get(order_id)
        if trade is None:
            logger.warning(f"update_order: 委託單 {order_id} 已不在市場上")
            return None
        odd_lot = trade.order.odd_lot in _ODD_LOTS
        remaining = trade.order_status.modified_quantity
        # quantity 是新的待成交張數，只能減量，0 表刪單；先檢查再送任何委託異動
        new_qty = remaining
        if quantity is not None:
            new_qty = round(quantity * 1000) if odd_lot else round(quantity)
            if quantity != 0 and new_qty >= remaining:
                raise ValueError(
                    f"update_order: 只能減量，委託單 {order_id} 剩 {remaining}，新數量 {quantity} 張"
                )
        # 零股不能改價；市價等非限價委託 SDK 不接受改價，都要刪單重下
        if price is not None and (
            odd_lot or trade.order.price_type != kgi.PriceType.LMT
        ):
            return self._replace_order(order_id, trade, new_qty, price)
        if new_qty == 0:
            self.cancel_order(order_id)
            return None
        if new_qty != remaining and (
            self.api.Order.update_order(order_id, qty=remaining - new_qty) is None
        ):
            raise RuntimeError(f"update_order: 凱基減量 {order_id} 送出失敗")
        if price is not None and (
            self.api.Order.update_order(order_id, price=float(price)) is None
        ):
            logger.warning(f"update_order: 無法更新委託單 {order_id} 的價格")
        return None

    def _replace_order(
        self, order_id: str, trade: Any, new_qty: int, price: float
    ) -> str | None:
        """刪單後以新價格重下；刪單或重下失敗都要報錯，否則委託會停在舊價或消失。"""
        filled_before = self._filled(trade)
        if self.api.Order.cancel_order(order_id) is None or not self._wait(
            lambda: trade.order_status.status in _DONE, trade.operations[-1]
        ):
            raise RuntimeError(
                f"update_order: 已送出委託單 {order_id} 的刪單，但無法確認刪除，未重下，"
                "請確認委託狀態後手動補單"
            )
        # 刪單前一刻成交的量算在新數量裡，不重下
        qty = new_qty - (self._filled(trade) - filled_before)
        if qty <= 0:
            return None
        order = trade.order
        new_order_id = self._place(
            _FROM_KGI_ACTION[order.action],
            order.symbol,
            qty,
            price,
            order.order_cond,
            odd_lot=order.odd_lot in _ODD_LOTS,
        )
        if not new_order_id:
            raise RuntimeError(
                f"update_order: 委託單 {order_id} 已刪單改價，但以 {price} 重下 {qty} 失敗，"
                "原委託已不存在，請手動補單"
            )
        return new_order_id

    def cancel_order(self, order_id: str) -> None:
        # 讀委託後才成交或失效的單，SDK 會 raise「查無此order_id」
        if order_id not in self.api.Order.get_trades():
            logger.warning(f"cancel_order: 委託單 {order_id} 已不在市場上，不需取消")
            return
        if self.api.Order.cancel_order(order_id) is None:
            raise RuntimeError(f"cancel_order: 凱基刪單 {order_id} 送出失敗")

    @staticmethod
    def _filled(trade: Any) -> int:
        return sum(d.quantity for d in trade.order_status.deals)

    def get_orders(self) -> dict[str, Order]:
        trades = self.api.Order.get_trades(True)
        today = datetime.datetime.now(TWMarket.tzinfo()).date()
        # 委託回報在背景執行緒更新，先複製一份；「無效單」是失敗委託的清單
        return {
            order_id: self._to_order(order_id, trade, today)
            for order_id, trade in list(trades.items())
            if order_id != "無效單"
        }

    def _to_order(self, order_id: str, trade: Any, today: datetime.date) -> Order:
        order, order_status = trade.order, trade.order_status
        divisor = 1000 if order.odd_lot in _ODD_LOTS else 1
        filled = Decimal(self._filled(trade)) / divisor
        remaining = Decimal(order_status.modified_quantity or 0) / divisor

        if order_status.status == kgi.Status.Filled:
            status = OrderStatus.FILLED
        elif order_status.status in _DONE:
            status = OrderStatus.CANCEL
        elif filled:
            status = OrderStatus.PARTIALLY_FILLED
        else:
            status = OrderStatus.NEW

        # 市價等非限價委託的 modified_price 是「市價」字串
        price = order_status.modified_price
        if not isinstance(price, (int, float)):
            price = order.price
        digits = "".join(c for c in str(trade.operations[0].op_time) if c.isdigit())
        op_time = digits[:6].ljust(6, "0")
        return Order(
            order_id=order_id,
            stock_id=order.symbol,
            action=_FROM_KGI_ACTION[order.action],
            price=price,
            quantity=filled + remaining,
            filled_quantity=filled,
            status=status,
            order_condition=_FROM_KGI_COND.get(order.order_cond, OrderCondition.CASH),
            time=datetime.datetime.combine(
                today, datetime.datetime.strptime(op_time, "%H%M%S").time()
            ),
            org_order=trade,
        )

    def _snapshots(self, stock_ids: list[str]) -> dict[str, Any]:
        # 登入時 Token 無效，SDK 不會掛上 Data
        if not hasattr(self.api, "Data"):
            raise RuntimeError("凱基行情未啟用（登入時 Token 無效），無法查詢報價")
        return self.api.Data.get_snapshots(list(stock_ids))

    def get_stocks(self, stock_ids: list[str]) -> dict[str, Stock]:
        snapshots = self._snapshots(stock_ids)
        return {
            sid: Stock(
                stock_id=sid,
                open=s.open_price,
                high=s.high_price,
                low=s.low_price,
                close=s.price,
                bid_price=s.bid_price,
                bid_volume=s.bid_volume,
                ask_price=s.ask_price,
                ask_volume=s.ask_volume,
                pct_change=calculate_tick_pct_change(s.price, s.reference_price),
            )
            for sid, s in snapshots.items()
        }

    def get_position(self) -> Position:
        # 'B' 以股數顯示，零股才不會被捨去；現股與零股分在不同欄
        inventory = self.api.Account.InventorySum("B")
        if inventory is None:
            raise RuntimeError("get_position: 凱基庫存查詢失敗")
        columns = (
            (OrderCondition.CASH, ("NETQTY0", "NETQTY9"), 1),
            (OrderCondition.MARGIN_TRADING, ("NETQTY3",), 1),
            (OrderCondition.SHORT_SELLING, ("NETQTY4",), -1),
        )
        position = []
        for row in inventory.to_dict("records"):
            for cond, names, sign in columns:
                shares = sum(int(float(row.get(name) or 0)) for name in names)
                if shares:
                    position.append(
                        {
                            "stock_id": row["Symbol"],
                            "quantity": sign * Decimal(shares) / 1000,
                            "order_condition": cond,
                        }
                    )
        return Position.from_list(position)

    def get_cash(self) -> int:
        raise NotImplementedError(
            "凱基 API 沒有提供銀行餘額查詢，請在凱基 App 或網站查看"
        )

    def get_total_balance(self) -> int:
        raise NotImplementedError("凱基 API 沒有提供銀行餘額查詢，無法計算帳戶淨值")

    def get_settlement(self) -> int:
        """近三日交割款中還沒交割的部分（正數為應收、負數為應付）"""
        settlements = self.api.Account.SettleAmt("SS")
        if settlements is None:
            raise RuntimeError("get_settlement: 凱基交割款查詢失敗")
        tw_now = datetime.datetime.now(TWMarket.tzinfo()).replace(tzinfo=None)
        total = 0
        for row in settlements.to_dict("records"):
            if row.get("CURRENCY", "TWD") != "TWD":
                continue
            for i in (1, 2, 3):
                date = row.get(f"CDate{i}")
                if (
                    date
                    and datetime.datetime.strptime(f"{date} 10:00", "%Y%m%d %H:%M")
                    > tw_now
                ):
                    total += int(float(row[f"CSRPAMT{i}"]))
        return total

    def get_market(self) -> TWMarket:
        return TWMarket()
