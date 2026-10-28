from __future__ import annotations

import contextlib
import datetime
import logging
import os
import queue
import sys
import threading
import time
from decimal import Decimal
from typing import Any

from finlab import data
from finlab.markets.tw import TWMarket
from finlab.online.core.account import Account, Order, Stock
from finlab.online.core.enums import Action, OrderCondition, OrderStatus
from finlab.online.core.position import Position
from finlab.online.core.realtime_normalizers import calculate_tick_pct_change

logger = logging.getLogger(__name__)

# SendStockOrder 的 TradeKind
_NEW, _REDUCE, _CANCEL, _REPRICE = 0, 3, 4, 7
# APCode：一般、盤後零股、盤中零股、盤後定價；委託回報的盤中零股也可能是 99
_COMMON, _ODD_AFTER_HOURS, _ODD, _FIXING = 0, 2, 4, 7
_ODD_AP_CODES = (_ODD_AFTER_HOURS, _ODD, 99)
# 委託回報 OrderStatus：委託失敗、委託失效、價穩失效、取消成功
_DONE = (10, 24, 25, 30)
# OnResponse 查詢回應的錯誤狀態（尚未登入、帳號錯誤、權限不足、加簽失敗、使用限制、停權等）
_ERRORS = (3, 4, 5, 7, 9, 10, 11, 13, 14)
_RESPONSE_TIMEOUT = 10
_ORDER_TYPE = {
    OrderCondition.CASH: "0",
    OrderCondition.MARGIN_TRADING: "3",
    OrderCondition.SHORT_SELLING: "4",
    OrderCondition.DAY_TRADING_LONG: "0",
    # 現股當沖先賣要用委託種類 9（現股當沖委託控管）
    OrderCondition.DAY_TRADING_SHORT: "9",
}
_ORDER_CONDITION = {
    0: OrderCondition.CASH,
    3: OrderCondition.MARGIN_TRADING,
    4: OrderCondition.SHORT_SELLING,
    9: OrderCondition.DAY_TRADING_SHORT,
}
# 委託回報才有的代碼換成下單用的：盤中零股 99→4、資沖 7→融資 3、券沖 8→融券 4
_SEND_AP_CODE = {99: _ODD}
_SEND_ORDER_TYPE = {7: "3", 8: "4"}
# 庫存 TradeKind：現股、資買、券賣（借券不是部位）
_STORE_CONDITION = {
    0: (OrderCondition.CASH, 1),
    3: (OrderCondition.MARGIN_TRADING, 1),
    4: (OrderCondition.SHORT_SELLING, -1),
}


def _tw_now() -> datetime.datetime:
    return datetime.datetime.now(TWMarket.tzinfo())


def _is_odd(record: Any) -> bool:
    return int(record.APCode) in _ODD_AP_CODES


def _load_sdk(api_dir: str) -> tuple[Any, Any]:
    """用 pythonnet 載入元大 SPARK API（.NET 8）的 YuantaSparkAPI.dll"""
    import pythonnet

    if pythonnet.get_runtime_info() is None:
        pythonnet.load("coreclr")
    import clr

    sys.path.append(api_dir)
    if sys.platform == "win32":
        os.add_dll_directory(api_dir)
    clr.AddReference("System.Collections")
    clr.AddReference("YuantaSparkAPI")
    import YuantaOneAPI
    from System.Collections.Generic import List

    return YuantaOneAPI, List


class YuantaAccount(Account):
    """元大證券帳戶，使用官方 SPARK API（.NET 8 元件，以 pythonnet 呼叫）。

    安裝：安裝 .NET 8 SDK、``pip install pythonnet``，再到元大 SPARK API 網站下載對應平台的
    Python 元件並解壓縮：https://www.yuanta.com.tw/file-repository/content/API/page/index.html
    Windows、macOS、Linux 都能用；macOS、Linux 登入要帶憑證檔（.pfx）。
    要先線上簽署風險預告書、完成 API 測試，再請營業員開通 API。
    """

    required_module = "pythonnet"

    def __init__(
        self,
        account: str | None = None,
        password: str | None = None,
        cert_path: str | None = None,
        cert_password: str | None = None,
        api_dir: str | None = None,
        uat: bool = False,
    ) -> None:
        account = account or os.environ.get("YUANTA_ACCOUNT")
        password = password or os.environ.get("YUANTA_PASSWORD")
        cert_path = cert_path or os.environ.get("YUANTA_CERT_PATH")
        cert_password = cert_password or os.environ.get("YUANTA_CERT_PASSWORD")
        api_dir = api_dir or os.environ.get("YUANTA_API_DIR")
        if not account or not password or not api_dir:
            raise ValueError(
                "請設定元大帳號、密碼與 API 元件資料夾：YUANTA_ACCOUNT、YUANTA_PASSWORD、YUANTA_API_DIR"
            )
        # 登入帳號是 S + 分公司代號 4 碼 + 帳號 7 碼
        self.account = account if account.startswith("S") else f"S{account}"

        self._sdk, self._List = _load_sdk(api_dir)
        self._init_state()
        self.api = self._sdk.YuantaSparkAPITrader()
        self.api.OnResponse += self._sdk.OnResponseEventHandler(self._on_response)
        mode = self._sdk.enumEnvironmentMode
        self.api.Open(mode.UAT if uat else mode.PROD)
        if not self._connected.wait(10):
            logger.warning("元大 API 連線逾時，仍嘗試登入")

        # Windows 用系統憑證；macOS、Linux 要指定憑證檔
        args = (cert_path, cert_password or "") if cert_path else ()
        result = self._call("Login", *args, self.account, password)
        status = result.LoginStatus
        if status.MsgCode not in ("0001", "00001") and not status.Count:
            raise ConnectionError(f"元大登入失敗：{status.MsgCode} {status.MsgContent}")

    def _init_state(self) -> None:
        self._connected = threading.Event()
        self._responses: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._last_call: dict[str, float] = {}
        self._markets: dict[str, Any] = {}
        self._order_records: dict[str, Any] = {}
        self._timed_out = False

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.api.LogOut()
            self.api.Close()
            self.api.Dispose()

    def _on_response(
        self, mark: int, index: int, name: str, handle: Any, value: Any
    ) -> None:
        if mark == 0:  # 系統訊息：1 連線，2 斷線，3 網路異常
            if index == 1:
                self._connected.set()
            elif index in (2, 3, 4, 5):
                logger.warning(f"元大 API：{value}")
        elif mark == 1:  # 查詢與下單的回應
            self._responses.put((name, index, value))

    def _call(self, name: str, *args: Any) -> Any:
        """送出請求並等 OnResponse 的回應；每個功能每秒最多查詢 3 次、交易 10 次"""
        with self._lock:
            # 逾時的請求之後才回來的回應，會被下一個同名請求當成自己的
            if self._timed_out:
                raise RuntimeError(
                    "元大 API 先前有請求沒有回應，請重新建立 YuantaAccount"
                )
            interval = 0.11 if name.startswith("Send") else 0.34
            wait = self._last_call.get(name, 0) + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            while not self._responses.empty():
                self._responses.get_nowait()
            ok = getattr(self.api, name)(*args)
            self._last_call[name] = time.monotonic()
            if ok is False:
                raise RuntimeError(f"元大 API {name} 執行異常")
            deadline = time.monotonic() + _RESPONSE_TIMEOUT
            while True:
                try:
                    index_name, index, value = self._responses.get(
                        timeout=max(0, deadline - time.monotonic())
                    )
                except queue.Empty:
                    self._timed_out = True
                    raise TimeoutError(f"元大 API {name} 沒有回應") from None
                # 名稱是空字串表示請求有誤，value 是錯誤訊息
                if index_name not in (name, ""):
                    continue
                if index_name == "" or index in _ERRORS:
                    raise RuntimeError(f"元大 API {name} 失敗：{value}")
                return value

    def _send_order(
        self,
        trade_kind: int,
        stock_id: str,
        buy_sell: str,
        qty: int,
        price: float,
        ap_code: int,
        order_type: str,
        price_flag: str = " ",
        order_no: str = "",
        trade_date: str | None = None,
    ) -> tuple[str | None, str]:
        """送出委託、改量、取消或改價；回傳 (委託書號, 錯誤說明)"""
        order = self._sdk.StockOrder()
        order.Identify = 1
        order.Account = self.account
        order.APCode = ap_code
        order.TradeKind = trade_kind
        order.OrderType = order_type
        order.StkCode = stock_id
        order.PriceFlag = price_flag
        order.Price = float(price)
        order.OrderQty = int(qty)
        order.BuySell = buy_sell
        order.OrderNo = order_no
        order.TradeDate = trade_date or _tw_now().strftime("%Y/%m/%d")
        order.BasketNo = ""
        order.Time_in_force = "0"
        orders = self._List[self._sdk.StockOrder]()
        orders.Add(order)

        result = self._call("SendStockOrder", self.account, orders)
        if not result.ResultList.Count:
            return None, f"{result.ResultCount.MsgCode} {result.ResultCount.MsgContent}"
        row = result.ResultList[0]
        if int(row.ReplyCode) != 0:
            return None, f"{row.ErrNO} {row.Advisory}"
        return str(row.OrderNO).strip(), ""

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
            odd_lot,
            # 回補當沖先賣的買單是一般現股買進
            "0"
            if action == Action.BUY and order_cond == OrderCondition.DAY_TRADING_SHORT
            else _ORDER_TYPE[order_cond],
            market_order,
            best_price_limit,
        )

    def _place(
        self,
        action: Action,
        stock_id: str,
        qty: int,
        price: Any,
        odd_lot: bool,
        order_type: str,
        market_order: bool = False,
        best_price_limit: bool = False,
    ) -> str | None:
        is_buy = action == Action.BUY
        # 盤別依台北時間判斷
        now = _tw_now().time()
        if odd_lot:
            after_hours = datetime.time(13, 40) <= now < datetime.time(14, 30)
            ap_code = _ODD_AFTER_HOURS if after_hours else _ODD
        elif datetime.time(14, 0) <= now < datetime.time(14, 30):
            ap_code = _FIXING
        else:
            ap_code = _COMMON

        # 一律送限價，漲跌停與收盤價從報價表取，不用漲跌停旗標
        quote = None
        if ap_code == _FIXING or market_order or best_price_limit or price is None:
            quote = self._quotes([stock_id]).get(stock_id)
            if quote is None:
                logger.warning(f"create_order: 查不到 {stock_id} 的報價，不送單")
                return None

        if ap_code == _FIXING:
            # 盤後定價只以收盤價成交：芭樂價或比收盤價差的限價不送、不中斷，
            # 呼叫端可能已先撤單，後面的單要照常下
            close = float(self._last_price(quote))
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
            order_price = quote.UpStopPrice if is_buy else quote.DownStopPrice
        elif best_price_limit:
            order_price = quote.DownStopPrice if is_buy else quote.UpStopPrice
        elif price is None:
            order_price = self._last_price(quote)
        else:
            order_price = price

        order_no, error = self._send_order(
            _NEW,
            stock_id,
            "B" if is_buy else "S",
            qty,
            order_price,
            ap_code,
            order_type,
        )
        if order_no is None:
            logger.warning(f"create_order: 元大委託 {stock_id} 失敗：{error}")
        return order_no

    def _modify(
        self, record: Any, trade_kind: int, shares: int, price: Any = None
    ) -> None:
        """改量、取消、改價都要帶原委託的資訊與委託書號；shares 以股為單位，整股換算成張。
        改價一律改成限價（價格種類空白），其餘沿用原委託的價格種類。"""
        date = record.TradeDate
        ap_code = int(record.APCode)
        _, error = self._send_order(
            trade_kind,
            record.CompanyNo,
            record.BS,
            shares if _is_odd(record) else shares // 1000,
            record.Price if price is None else price,
            _SEND_AP_CODE.get(ap_code, ap_code),
            self._send_order_type(record),
            " "
            if trade_kind == _REPRICE
            else {"1": "M", "2": " "}.get(record.PriceFlag, record.PriceFlag),
            record.OrderNo,
            f"{date.ushtYear:04d}/{date.bytMon:02d}/{date.bytDay:02d}",
        )
        if error:
            raise RuntimeError(f"元大委託 {record.OrderNo} 異動失敗：{error}")

    @staticmethod
    def _send_order_type(record: Any) -> str:
        order_type = int(record.OrderType)
        return _SEND_ORDER_TYPE.get(order_type, str(order_type))

    @staticmethod
    def _shares(record: Any) -> tuple[int, int, int]:
        """（原委託量 − 取消量、成交量、剩餘量），單位為股"""
        quantity = int(record.OR_QTY) - int(record.CancelQty)
        filled = int(record.OkQty)
        remaining = 0 if int(record.OrderStatus) in _DONE else quantity - filled
        return quantity, filled, max(remaining, 0)

    def update_order(
        self,
        order_id: str,
        price: float | None = None,
        quantity: float | None = None,
    ) -> str | None:
        self._refresh_records()
        record = self._order_records.get(order_id)
        remaining = self._shares(record)[2] if record else 0
        if not remaining:
            logger.warning(f"update_order: 委託單 {order_id} 已不在市場上")
            return None
        # quantity 是新的待成交張數，只能減量，0 表刪單；先檢查再送任何委託異動
        new_shares = remaining
        if quantity is not None:
            new_shares = round(quantity * 1000)
            if quantity != 0 and new_shares >= remaining:
                raise ValueError(
                    f"update_order: 只能減量，委託單 {order_id} 剩 {remaining} 股，新數量 {quantity} 張"
                )
        # 零股不能改價，市價委託也不能改成限價，都要刪單重下
        if price is not None and (_is_odd(record) or record.PriceFlag in ("1", "M")):
            return self._replace_order(order_id, record, new_shares, price)
        if new_shares == 0:
            self.cancel_order(order_id)
            return None
        if new_shares != remaining:
            self._modify(record, _REDUCE, remaining - new_shares)
        if price is not None:
            try:
                self._modify(record, _REPRICE, new_shares, price)
            except RuntimeError as e:
                logger.warning(f"update_order: 無法更新委託單 {order_id} 的價格: {e}")
        return None

    def _replace_order(
        self, order_id: str, record: Any, new_shares: int, price: float
    ) -> str | None:
        """刪單後以新價格重下；刪單或重下失敗都要報錯，否則委託會停在舊價或消失。"""
        filled_before = self._shares(record)[1]
        # 刪單前一刻成交的股數算在新數量裡，不重下
        shares = new_shares - (self._cancel(order_id, record) - filled_before)
        if shares <= 0:
            return None
        odd_lot = _is_odd(record)
        new_order_id = self._place(
            Action.BUY if record.BS == "B" else Action.SELL,
            record.CompanyNo,
            shares if odd_lot else shares // 1000,
            price,
            odd_lot,
            self._send_order_type(record),
        )
        if not new_order_id:
            raise RuntimeError(
                f"update_order: 委託單 {order_id} 已刪單改價，但以 {price} 重下 {shares} 股失敗，"
                "原委託已不存在，請手動補單"
            )
        return new_order_id

    def cancel_order(self, order_id: str) -> None:
        record = self._order_records.get(order_id)
        if record is None or not self._shares(record)[2]:
            # 快取沒有或已不在市場上，重查一次
            self._refresh_records()
            record = self._order_records.get(order_id)
        if record is None:
            raise KeyError(f"cancel_order: 找不到委託單 {order_id}")
        remaining = self._shares(record)[2]
        if not remaining:
            logger.warning(f"cancel_order: 委託單 {order_id} 已不在市場上，不需取消")
            return
        self._cancel(order_id, record)

    def _cancel(self, order_id: str, record: Any) -> int:
        """刪單並重查到委託確定離開市場（已刪或剛好全部成交），回傳最終成交股數。
        沒確認就報錯，否則呼叫端接著下的新單會重複。"""
        error = None
        try:
            self._modify(record, _CANCEL, self._shares(record)[2])
        except RuntimeError as e:
            # 讀委託後才全部成交或失效，刪單會被拒；下面重查確認
            error = e
        for attempt in range(3):
            if attempt:
                time.sleep(1)
            self._refresh_records()
            current = self._order_records.get(order_id)
            if current is not None and not self._shares(current)[2]:
                return self._shares(current)[1]
        raise RuntimeError(
            f"cancel_order: 元大委託單 {order_id} 刪單失敗或無法確認刪除，"
            f"委託可能仍在市場上，請確認委託狀態（{error or '已送出刪單'}）"
        )

    def _refresh_records(self) -> None:
        records = self._call("GetOrderTradeReport", False, self.account).StkOrderList
        self._order_records = {str(r.OrderNo).strip(): r for r in records}

    def get_orders(self) -> dict[str, Order]:
        self._refresh_records()
        return {oid: self._to_order(oid, r) for oid, r in self._order_records.items()}

    def _to_order(self, order_id: str, record: Any) -> Order:
        quantity, filled, remaining = self._shares(record)
        if quantity and filled == int(record.OR_QTY):
            status = OrderStatus.FILLED
        elif not remaining:
            status = OrderStatus.CANCEL
        elif filled:
            status = OrderStatus.PARTIALLY_FILLED
        else:
            status = OrderStatus.NEW
        date, t = record.AcceptDate, record.AcceptTime
        return Order(
            order_id=order_id,
            stock_id=record.CompanyNo,
            action=Action.BUY if record.BS == "B" else Action.SELL,
            price=float(record.Price),
            quantity=Decimal(quantity) / 1000,
            filled_quantity=Decimal(filled) / 1000,
            status=status,
            order_condition=_ORDER_CONDITION.get(
                int(record.OrderType), OrderCondition.CASH
            ),
            time=datetime.datetime(
                date.ushtYear, date.bytMon, date.bytDay, t.bytHour, t.bytMin, t.bytSec
            ),
            org_order=record,
        )

    def _quotes(self, stock_ids: list[str]) -> dict[str, Any]:
        """報價表查詢要指定上市或上櫃：先查上市，查不到的再查上櫃"""
        market = self._sdk.enumMarketType
        found: dict[str, Any] = {}
        pending = list(dict.fromkeys(stock_ids))
        for market_type in (market.TWSE, market.TWOTC):
            # 已知市場的直接查，其餘先試這個市場
            batch = [
                s for s in pending if self._markets.get(s, market_type) == market_type
            ]
            wanted = set(batch)
            for i in range(0, len(batch), 600):  # 單次查詢上限 600 檔
                quotes = self._List[self._sdk.Quote]()
                for sid in batch[i : i + 600]:
                    quote = self._sdk.Quote()
                    quote.MarketType = market_type
                    quote.StockCode = sid
                    quotes.Add(quote)
                result = self._call("GetWatchListAll", self.account, quotes)
                for row in result.QueryWatchList:
                    code = row.StkCode
                    if code in wanted and row.YstPrice:
                        found[code] = row
                        self._markets[code] = market_type
            pending = [s for s in pending if s not in found]
        return found

    @staticmethod
    def _last_price(quote: Any) -> float:
        # 開盤前還沒有成交價，用開盤參考價
        return quote.DealPrice or quote.OpenRefPrice

    def get_stocks(self, stock_ids: list[str]) -> dict[str, Stock]:
        def book(price: float) -> float:
            # 市價買賣以 ±999999999 表示
            return 0 if abs(price) >= 999999999 else price

        return {
            sid: Stock(
                stock_id=sid,
                open=q.OpenPrice,
                high=q.HighPrice,
                low=q.LowPrice,
                close=self._last_price(q),
                bid_price=book(q.BuyPrice),
                bid_volume=q.BidQty,
                ask_price=book(q.SellPrice),
                ask_volume=q.AskQty,
                pct_change=calculate_tick_pct_change(q.DealPrice, q.YstPrice),
            )
            for sid, q in self._quotes(stock_ids).items()
        }

    def _store(self) -> list[Any]:
        return list(self._call("GetStoreSummary", self.account).StkStoreList)

    def get_position(self) -> Position:
        position = []
        for store in self._store():
            cond, sign = _STORE_CONDITION.get(int(store.TradeKind), (None, 0))
            shares = sign * int(store.StockQty)
            if cond is not None and shares:
                # 現股當沖先賣還沒買回時，現股股數是負的，跟下單時一樣標成當沖賣
                if cond == OrderCondition.CASH and shares < 0:
                    cond = OrderCondition.DAY_TRADING_SHORT
                position.append(
                    {
                        "stock_id": store.StkCode,
                        "quantity": Decimal(shares) / 1000,
                        "order_condition": cond,
                    }
                )
        return Position.from_list(position)

    def get_cash(self) -> int:
        balances = self._call("GetBankBalance", self.account).BankBalanceList
        if not balances.Count:
            raise RuntimeError("get_cash: 元大銀行餘額查詢沒有資料")
        return sum(int(b.AvailableBalance) for b in balances)

    def get_settlement(self) -> int:
        """近三交割日的交割款中還沒交割的部分"""
        result = self._call("GetStkTransactionOutlay", self.account)
        tw_now = _tw_now().replace(tzinfo=None)
        return sum(
            int(o.SettlementAmt)
            for o in result.TransactionOutlayList
            if datetime.datetime.strptime(f"{o.SettlementDay} 10:00", "%Y/%m/%d %H:%M")
            > tw_now
        )

    def get_total_balance(self) -> int:
        # 每筆庫存的持有成本加未實現損益，即賣出後拿回的金額（融資、融券已扣借款與回補成本）
        stores = sum(
            float(s.Cost) + float(s.ReturnAmt)
            for s in self._store()
            if int(s.TradeKind) in _STORE_CONDITION
        )
        return int(stores) + self.get_settlement() + self.get_cash()

    def get_price_info(self) -> dict[str, dict[str, Any]]:
        ref = data.get("reference_price")
        return ref.set_index("stock_id").to_dict(orient="index")

    def get_market(self) -> TWMarket:
        return TWMarket()
