"""
MasterlinkAccount 模組

實現與台新證券（原元富證券）API 交互的 Account 類；TaishinAccount 是同一個類別
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
from decimal import Decimal
from typing import Any

try:
    from taishin_sdk import (
        BSAction,
        MarketType,
        OrderType,
        PriceType,
        TaishinSDK,
        TimeInForce,
    )
    from taishin_sdk import Order as MLOrder
except ModuleNotFoundError as e:
    if e.name != "taishin_sdk":
        raise
    # 元富 2026-04 併入台新，SDK 由 masterlink_sdk 改為不在 PyPI 上的 taishin_sdk
    raise ModuleNotFoundError(
        "元富證券已併入台新證券，請改裝 taishin_sdk（官方支援 Python 3.8～3.12）："
        "到 https://ml-fugle-api.tssco.com.tw/FugleSDK/docs/download/download-sdk "
        "下載 whl 後用 pip install 安裝",
        name=e.name,
    ) from e

from finlab import data
from finlab.markets.tw import TWMarket
from finlab.online.core.account import Account, Order, Stock
from finlab.online.core.enums import *
from finlab.online.core.position import Position
from finlab.online.core.realtime_helpers import (
    build_bidask_from_quote,
    build_ticks_from_intraday_trade_rows,
)
from finlab.online.core.realtime_models import (
    BalanceUpdate,
    BidAsk,
    ConnectionState,
    Fill,
    OrderUpdate,
    Tick,
)
from finlab.online.core.realtime_normalizers import (
    get_field_value,
    get_first_valid_float,
    to_optional_float,
)
from finlab.online.core.realtime_provider import RealtimeProvider


class MasterlinkAccount(Account, RealtimeProvider):
    """
    台新證券（原元富證券）賬戶類
    實現與台新證券 API 的交互
    """

    required_module = "taishin_sdk"  # 需要的 Python 包名稱
    module_version = "1.0.2"  # 需要的版本號

    def __init__(
        self,
        base_url: str | None = None,
        national_id: str | None = None,
        account: str | None = None,
        account_pass: str | None = None,
        cert_path: str | None = None,
        cert_pass: str | None = None,
    ) -> None:
        """
        初始化台新證券賬戶

        環境變數優先讀 TAISHIN_*，沒有設定時讀舊的 MASTERLINK_*。

        Args:
            national_id (str, optional): 身分證字號。預設從環境變數獲取。
            account (str, optional): 帳號。預設從環境變數獲取。
            account_pass (str, optional): 登入密碼。預設從環境變數獲取。
            cert_path (str, optional): 憑證路徑。預設從環境變數獲取。
            cert_pass (str, optional): 憑證密碼。預設從環境變數獲取。
        """
        # 從參數或環境變數獲取登錄信息
        def env(name: str) -> str | None:
            return os.environ.get(f"TAISHIN_{name}") or os.environ.get(
                f"MASTERLINK_{name}"
            )

        self.base_url = base_url or env("BASE_URL")
        self.national_id = national_id or env("NATIONAL_ID")
        self.account = account or env("ACCOUNT")
        self.account_pass = account_pass or env("ACCOUNT_PASS")
        self.cert_path = cert_path or env("CERT_PATH")
        self.cert_pass = cert_pass or env("CERT_PASS")

        if not all([self.national_id, self.account_pass, self.cert_path]):
            raise ValueError(
                "缺少必要的登錄信息。請確保設置了 TAISHIN_NATIONAL_ID, TAISHIN_ACCOUNT_PASS, TAISHIN_CERT_PATH 環境變數或直接提供參數"
            )

        # 初始化市場和時間戳
        self.market = "tw_stock"
        self.order_records = {}
        self._tick_pct_change_cache = {}

        # 初始化 SDK 和帳戶
        logging.info("初始化台新 SDK...")
        self.sdk = TaishinSDK(self.base_url)

        # 登入
        try:
            if self.cert_pass:
                self.accounts = self.sdk.login(
                    self.national_id, self.account_pass, self.cert_path, self.cert_pass
                )
            else:
                # 若沒有提供憑證密碼，使用預設值 (技術文件申請)
                self.accounts = self.sdk.login(
                    self.national_id, self.account_pass, self.cert_path
                )
        except Exception as e:
            logging.exception(f"登入失敗: {e}")
            raise Exception(f"無法登入台新證券: {e}") from e

        # 選擇帳戶
        if self.account:
            self.target_account = next(
                (acc for acc in self.accounts if acc.account == self.account), None
            )
            if not self.target_account:
                logging.warning(f"未找到指定帳號 {self.account}，將使用第一個帳號")
                self.target_account = self.accounts[0] if self.accounts else None
        else:
            self.target_account = self.accounts[0] if self.accounts else None

        if not self.target_account:
            raise ValueError("無法獲取有效的台新證券帳戶")

        logging.info(f"成功登入帳號: {self.target_account.account}")

        # 初始化行情連線
        try:
            self.sdk.init_realtime(self.target_account)
            logging.info("初始化行情元件成功")
        except Exception as e:
            logging.warning(f"初始化行情元件失敗: {e}")
        self._init_realtime()

    # ── RealtimeProvider implementation ──────────────────────────────

    @staticmethod
    def _parse_event_time(payload: Any) -> datetime.datetime:
        time_value = get_field_value(payload, "time")
        if time_value is None:
            time_value = get_field_value(payload, "closeTime")
        if time_value is None:
            time_value = get_field_value(payload, "lastUpdated")
        parsed = to_optional_float(time_value)
        if parsed is None:
            return datetime.datetime.now()

        raw = int(parsed)
        try:
            if raw >= 10**14:
                return datetime.datetime.fromtimestamp(raw / 1_000_000)
            if raw >= 10**11:
                return datetime.datetime.fromtimestamp(raw / 1_000)
            return datetime.datetime.fromtimestamp(raw)
        except (OSError, OverflowError, ValueError):
            return datetime.datetime.now()

    @staticmethod
    def _map_buy_sell_action(value: Any) -> Action:
        if value is None:
            return Action.SELL
        text = str(value).upper()
        return Action.BUY if text in ("B", "BUY", "BSACTION.BUY") else Action.SELL

    @staticmethod
    def _order_time_from_payload(data: Any) -> datetime.datetime:
        order_datetime = get_field_value(data, "order_datetime")
        if isinstance(order_datetime, datetime.datetime):
            return order_datetime

        order_date = get_field_value(data, "order_date")
        order_time = get_field_value(data, "order_time")
        if order_date and order_time:
            try:
                return datetime.datetime.strptime(
                    f"{order_date}{order_time}", "%Y%m%d%H%M%S%f"
                )
            except ValueError:
                pass

        return datetime.datetime.now()

    @staticmethod
    def _order_quantity_divisor(data: Any) -> float:
        market_type = str(get_field_value(data, "market_type") or "").upper()
        if market_type in {"INTRADAYODD", "ODD", "EMGODD"}:
            return 1.0
        return 1000.0

    @staticmethod
    def _map_realtime_order_condition(data: Any) -> OrderCondition:
        order_type = str(get_field_value(data, "order_type") or "").upper()
        if "MARGIN" in order_type:
            return OrderCondition.MARGIN_TRADING
        if "SHORT" in order_type:
            return OrderCondition.SHORT_SELLING
        if "DAYTRADE" in order_type:
            return OrderCondition.DAY_TRADING_SHORT
        return OrderCondition.CASH

    @staticmethod
    def _map_realtime_operation(data: Any) -> str:
        act = str(get_field_value(data, "act") or "").upper()
        return {
            "0": "new",
            "M": "update_qty",
            "R": "update_price",
            "C": "cancel",
        }.get(act, "")

    def _map_realtime_status(self, data: Any) -> OrderStatus:
        kind = str(get_field_value(data, "kind") or "").upper()
        divisor = self._order_quantity_divisor(data)
        quantity = (
            get_first_valid_float(data, "after_qty", "org_qty", "quantity", "qty")
            or 0.0
        ) / divisor
        filled_quantity = (
            get_first_valid_float(data, "filled_qty", "mat_qty", "deal_quantity") or 0.0
        ) / divisor
        canceled_quantity = (
            get_first_valid_float(data, "cel_qty", "cancel_quantity") or 0.0
        ) / divisor
        can_cancel = get_field_value(data, "can_cancel")
        if isinstance(can_cancel, str):
            can_cancel = can_cancel.lower() == "true"
        err_code = str(get_field_value(data, "err_code") or "000000")

        if kind == "MAT" and filled_quantity > 0:
            if quantity > 0 and filled_quantity >= quantity:
                return OrderStatus.FILLED
            return OrderStatus.PARTIALLY_FILLED
        if canceled_quantity > 0:
            return (
                OrderStatus.PARTIALLY_FILLED
                if filled_quantity > 0
                else OrderStatus.CANCEL
            )
        if err_code not in {"000000", "", "0", "NONE"}:
            return OrderStatus.CANCEL
        if quantity > 0 and filled_quantity >= quantity > 0:
            return OrderStatus.FILLED
        if filled_quantity > 0:
            return OrderStatus.PARTIALLY_FILLED
        if can_cancel is False:
            return OrderStatus.CANCEL
        return OrderStatus.NEW

    def _build_realtime_order_update(self, data: Any) -> OrderUpdate:
        divisor = self._order_quantity_divisor(data)
        quantity = (
            get_first_valid_float(data, "after_qty", "org_qty", "quantity", "qty")
            or 0.0
        ) / divisor
        filled_quantity = (
            get_first_valid_float(data, "filled_qty", "mat_qty", "deal_quantity") or 0.0
        ) / divisor
        price = get_first_valid_float(data, "od_price", "order_price", "price") or 0.0

        return OrderUpdate(
            order_id=str(
                get_field_value(data, "order_no")
                or get_field_value(data, "orderNo")
                or get_field_value(data, "seq_no")
                or get_field_value(data, "seqNo")
                or get_field_value(data, "id")
                or ""
            ),
            stock_id=str(
                get_field_value(data, "stock_no")
                or get_field_value(data, "symbol")
                or get_field_value(data, "code")
                or ""
            ),
            action=self._map_buy_sell_action(
                get_field_value(data, "buy_sell") or get_field_value(data, "action")
            ),
            price=price,
            quantity=quantity,
            filled_quantity=filled_quantity,
            status=self._map_realtime_status(data),
            order_condition=self._map_realtime_order_condition(data),
            time=self._order_time_from_payload(data),
            operation=self._map_realtime_operation(data),
            org_event=data,
        )

    def _build_realtime_fill(self, data: Any) -> Fill:
        divisor = self._order_quantity_divisor(data)
        quantity = (
            get_first_valid_float(data, "filled_qty", "mat_qty", "quantity", "qty")
            or 0.0
        ) / divisor
        return Fill(
            order_id=str(
                get_field_value(data, "order_no")
                or get_field_value(data, "orderNo")
                or get_field_value(data, "ord_no")
                or get_field_value(data, "seq_no")
                or ""
            ),
            stock_id=str(
                get_field_value(data, "stock_no")
                or get_field_value(data, "symbol")
                or get_field_value(data, "code")
                or ""
            ),
            action=self._map_buy_sell_action(
                get_field_value(data, "buy_sell") or get_field_value(data, "action")
            ),
            price=get_first_valid_float(data, "filled_price", "mat_price", "price")
            or 0.0,
            quantity=quantity,
            time=self._order_time_from_payload(data),
            org_event=data,
        )

    def _get_realtime_balance(self) -> BalanceUpdate | None:
        balance_payload = None
        if hasattr(self.sdk.accounting, "skbank_balance"):
            try:
                balance_payload = self.sdk.accounting.skbank_balance(
                    self.target_account
                )
            except Exception:
                logging.exception("Failed to fetch skbank_balance for realtime")

        if balance_payload is None and hasattr(self.sdk.accounting, "bank_balance"):
            try:
                bank_balance = self.sdk.accounting.bank_balance(self.target_account)
                if isinstance(bank_balance, list) and bank_balance:
                    balance_payload = bank_balance[0]
                else:
                    balance_payload = bank_balance
            except Exception:
                logging.exception("Failed to fetch bank_balance for realtime")

        if balance_payload is None:
            return None

        available_balance = get_first_valid_float(
            balance_payload, "available_balance", "availableBalance"
        )
        reserved_amount = get_first_valid_float(
            balance_payload, "reserved_amount", "reservedAmount"
        )
        dedicated_account_balance = get_first_valid_float(
            balance_payload, "dedicated_account_balance", "dedicatedAccountBalance"
        )

        return BalanceUpdate(
            account_id=str(getattr(self.target_account, "account", "")),
            broker=self.__class__.__name__,
            available_balance=available_balance,
            reserved_amount=reserved_amount,
            dedicated_account_balance=dedicated_account_balance,
            cash=available_balance,
            # 查詢失敗時這兩項給 None（未知），不讓整筆餘額更新消失
            settlement=self._safe_call_number("get_settlement"),
            total_balance=self._safe_call_number("get_total_balance"),
            time=datetime.datetime.now(),
            org_event=balance_payload,
        )

    def connect_realtime(self) -> None:
        if self._realtime_connected:
            return

        def _extract_payload(message: Any) -> dict[str, Any]:
            if isinstance(message, str):
                try:
                    message = json.loads(message)
                except ValueError:
                    return {}

            payload = message
            nested_data = get_field_value(payload, "data")
            if nested_data is not None and get_field_value(payload, "symbol") is None:
                payload = nested_data
            return payload

        def _emit_tick_from_payload(payload: dict[str, Any], channel: str = "") -> None:
            symbol = get_field_value(payload, "symbol")
            if not symbol:
                return
            symbol = str(symbol)

            native_pct_change = get_first_valid_float(
                payload,
                "changePercent",
                "pct_change",
                "pctChange",
                "change_percent",
                "change_rate",
            )
            if native_pct_change is not None:
                self._tick_pct_change_cache[symbol] = native_pct_change
            else:
                native_pct_change = self._tick_pct_change_cache.get(symbol)

            price = get_first_valid_float(
                payload,
                "price",
                "closePrice",
                "close_price",
                "lastPrice",
            )
            volume = get_first_valid_float(payload, "size", "lastSize")
            total_volume = get_first_valid_float(payload, "volume")
            if total_volume is None:
                total_obj = get_field_value(payload, "total")
                total_volume = get_first_valid_float(total_obj, "tradeVolume")

            open_price = get_first_valid_float(
                payload, "openPrice", "open", "open_price"
            )
            high_price = get_first_valid_float(
                payload, "highPrice", "high", "high_price"
            )
            low_price = get_first_valid_float(payload, "lowPrice", "low", "low_price")
            avg_price = get_first_valid_float(payload, "avgPrice", "avg_price")
            channel_text = str(channel).lower()
            source = "aggregate" if "aggregate" in channel_text else "trade"
            if source != "aggregate":
                source = (
                    "trade"
                    if get_field_value(payload, "size") is not None
                    or get_field_value(payload, "lastSize") is not None
                    else "aggregate"
                )

            self._emit_tick(
                Tick(
                    stock_id=symbol,
                    price=price if price is not None else 0.0,
                    volume=int(volume or 0),
                    total_volume=int(total_volume or 0),
                    time=self._parse_event_time(payload),
                    open=open_price if open_price is not None else 0.0,
                    high=high_price if high_price is not None else 0.0,
                    low=low_price if low_price is not None else 0.0,
                    avg_price=avg_price if avg_price is not None else 0.0,
                    pct_change=native_pct_change,
                    source=source,
                )
            )

        def _on_message(message: Any) -> None:
            try:
                payload = _extract_payload(message)
                channel = get_field_value(message, "channel") or ""

                # Books channel payload can still arrive via generic "message" event.
                bids = get_field_value(payload, "bids")
                asks = get_field_value(payload, "asks")
                if bids is not None or asks is not None:
                    bids = bids or []
                    asks = asks or []
                    stock_id = get_field_value(payload, "symbol")
                    if stock_id:
                        self._emit_bidask(
                            BidAsk(
                                stock_id=str(stock_id),
                                bid_prices=[
                                    float(get_field_value(b, "price") or 0.0)
                                    for b in bids
                                ],
                                bid_volumes=[
                                    int(get_field_value(b, "size") or 0) for b in bids
                                ],
                                ask_prices=[
                                    float(get_field_value(a, "price") or 0.0)
                                    for a in asks
                                ],
                                ask_volumes=[
                                    int(get_field_value(a, "size") or 0) for a in asks
                                ],
                                time=self._parse_event_time(payload),
                            )
                        )

                trade_like = (
                    get_field_value(payload, "price") is not None
                    or get_field_value(payload, "size") is not None
                    or get_field_value(payload, "closePrice") is not None
                    or get_field_value(payload, "lastPrice") is not None
                )
                if trade_like:
                    _emit_tick_from_payload(payload, channel=channel)
            except Exception:
                logging.exception("Error in Masterlink tick handler")

        def _on_book_message(message: Any) -> None:
            try:
                payload = _extract_payload(message)
                stock_id = get_field_value(payload, "symbol")
                if not stock_id:
                    return
                bids = get_field_value(payload, "bids") or []
                asks = get_field_value(payload, "asks") or []
                self._emit_bidask(
                    BidAsk(
                        stock_id=str(stock_id),
                        bid_prices=[
                            float(get_field_value(b, "price") or 0.0) for b in bids
                        ],
                        bid_volumes=[
                            int(get_field_value(b, "size") or 0) for b in bids
                        ],
                        ask_prices=[
                            float(get_field_value(a, "price") or 0.0) for a in asks
                        ],
                        ask_volumes=[
                            int(get_field_value(a, "size") or 0) for a in asks
                        ],
                        time=self._parse_event_time(payload),
                    )
                )
            except Exception:
                logging.exception("Error in Masterlink bidask handler")

        ws_client = self.sdk.marketdata.websocket_client.stock
        ws_client.connect()
        ws_client.on("message", _on_message)
        ws_client.on("book", _on_book_message)

        def _on_order(data: Any) -> None:
            try:
                self._emit_order_update(self._build_realtime_order_update(data))
            except Exception:
                logging.exception("Error in Masterlink order handler")

        def _on_filled(data: Any) -> None:
            try:
                self._emit_fill(self._build_realtime_fill(data))
            except Exception:
                logging.exception("Error in Masterlink fill handler")

        self.sdk.set_on_order(_on_order)
        self.sdk.set_on_filled(_on_filled)
        self.sdk.connect_websocket()

        self._realtime_connected = True
        self._emit_connection(ConnectionState.CONNECTED)
        logging.info("Masterlink realtime connected")

    def disconnect_realtime(self) -> None:
        if not self._realtime_connected:
            return
        try:
            ws_client = self.sdk.marketdata.websocket_client.stock
            ws_client.disconnect()
        except Exception:
            logging.exception("Error disconnecting Masterlink websocket")
        self.unsubscribe_balances()
        self._realtime_connected = False
        self._emit_connection(ConnectionState.DISCONNECTED)
        logging.info("Masterlink realtime disconnected")

    def subscribe_ticks(self, stock_ids: list[str]) -> None:
        ws_client = self.sdk.marketdata.websocket_client.stock
        for sid in stock_ids:
            ws_client.subscribe({"channel": "trades", "symbol": sid})
            ws_client.subscribe({"channel": "aggregates", "symbol": sid})

    def unsubscribe_ticks(self, stock_ids: list[str]) -> None:
        ws_client = self.sdk.marketdata.websocket_client.stock
        for sid in stock_ids:
            ws_client.unsubscribe({"channel": "trades", "symbol": sid})
            ws_client.unsubscribe({"channel": "aggregates", "symbol": sid})
            self._tick_pct_change_cache.pop(sid, None)

    def subscribe_bidask(self, stock_ids: list[str]) -> None:
        ws_client = self.sdk.marketdata.websocket_client.stock
        for sid in stock_ids:
            ws_client.subscribe({"channel": "books", "symbol": sid})

    def unsubscribe_bidask(self, stock_ids: list[str]) -> None:
        ws_client = self.sdk.marketdata.websocket_client.stock
        for sid in stock_ids:
            ws_client.unsubscribe({"channel": "books", "symbol": sid})

    def backfill_ticks(
        self,
        stock_ids: list[str],
        start_time: Any = None,
        end_time: Any = None,
        emit: bool = True,
    ) -> dict[str, list[Tick]]:
        if not hasattr(self.sdk, "marketdata") or not hasattr(
            self.sdk.marketdata, "rest_client"
        ):
            try:
                self.sdk.init_realtime(self.target_account)
            except Exception as e:
                logging.exception(f"backfill_ticks: 無法初始化行情連線: {e}")
                return {}

        rest_stock = self.sdk.marketdata.rest_client.stock
        intraday = getattr(rest_stock, "intraday", None)
        if intraday is None or not hasattr(intraday, "trades"):
            raise NotImplementedError("Masterlink SDK does not expose intraday.trades")

        backfilled = {}
        session_date = datetime.datetime.now().date()

        for stock_id in stock_ids:
            rows = []
            try:
                quote = rest_stock.intraday.quote(symbol=stock_id) or {}
                prev_close = get_first_valid_float(
                    quote,
                    "previousClose",
                    "referencePrice",
                    "reference_price",
                )
                pct_change = get_first_valid_float(
                    quote,
                    "changePercent",
                    "pct_change",
                    "pctChange",
                )

                offset = 0
                limit = 500
                seen_pages = set()
                while True:
                    payload = intraday.trades(
                        symbol=stock_id, limit=limit, offset=offset
                    )
                    page_rows = (
                        payload.get("data", []) if isinstance(payload, dict) else []
                    )
                    if not page_rows:
                        break

                    page_marker = (
                        len(page_rows),
                        get_field_value(page_rows[0], "serial"),
                        get_field_value(page_rows[-1], "serial"),
                    )
                    if page_marker in seen_pages:
                        break
                    seen_pages.add(page_marker)

                    rows.extend(page_rows)

                    if len(page_rows) < limit:
                        break
                    offset += len(page_rows)

                ticks = build_ticks_from_intraday_trade_rows(
                    stock_id=stock_id,
                    rows=rows,
                    session_date=session_date,
                    prev_close=prev_close,
                    pct_change=pct_change,
                    start_time=start_time,
                    end_time=end_time,
                )

            except Exception:
                logging.exception(
                    "backfill_ticks: 無法回補股票 %s 的盤中 ticks", stock_id
                )
                ticks = []

            backfilled[stock_id] = ticks
            if emit:
                for tick in ticks:
                    self._emit_tick(tick)

        return backfilled

    def get_bidask_snapshot(
        self, stock_ids: list[str], emit: bool = True
    ) -> dict[str, BidAsk]:
        if not hasattr(self.sdk, "marketdata") or not hasattr(
            self.sdk.marketdata, "rest_client"
        ):
            try:
                self.sdk.init_realtime(self.target_account)
            except Exception as e:
                logging.exception(f"get_bidask_snapshot: 無法初始化行情連線: {e}")
                return {}

        snapshots = {}
        rest_stock = self.sdk.marketdata.rest_client.stock
        for stock_id in stock_ids:
            try:
                quote = rest_stock.intraday.quote(symbol=stock_id)
                if not quote:
                    continue
                bidask = build_bidask_from_quote(stock_id, quote)
                snapshots[stock_id] = bidask
                if emit:
                    self._emit_bidask(bidask)
            except Exception:
                logging.exception(
                    "get_bidask_snapshot: 無法取得股票 %s 的五檔快照", stock_id
                )

        return snapshots

    # ── End RealtimeProvider ──────────────────────────────────────

    def __del__(self) -> None:
        """
        當物件被刪除時，確保登出
        """
        try:
            if hasattr(self, "sdk") and hasattr(self.sdk, "logout"):
                self.sdk.logout()
        except Exception as e:
            logging.warning(f"登出時發生錯誤: {e}")

    def create_order(
        self,
        action: Action,
        stock_id: str,
        quantity: float,
        price: float | None = None,
        odd_lot: bool = False,
        best_price_limit: bool = False,
        market_order: bool = False,
        order_cond: OrderCondition = OrderCondition.CASH,
    ) -> str | None:
        """
        創建委託單

        Args:
            action (Action): 操作類型，買或賣
            stock_id (str): 股票代碼
            quantity (float): 數量，以張為單位
            price (float, optional): 價格
            odd_lot (bool): 是否為零股
            best_price_limit (bool): 是否使用最優價格限制
            market_order (bool): 是否為市價單
            order_cond (OrderCondition): 交易條件

        Returns:
            str: 委託單編號
        """
        if quantity <= 0.0:
            raise ValueError("委託數量必須大於零")

        # 將 finlab Action 轉換為元富 BSAction
        buy_sell = BSAction.Buy if action == Action.BUY else BSAction.Sell

        # 確定市場類型
        market_type = MarketType.IntradayOdd if odd_lot else MarketType.Common
        # 盤別依台北時間判斷，不受主機時區影響
        now = datetime.datetime.now(TWMarket.tzinfo()).time()

        # 盤後零股處理
        if datetime.time(13, 40) <= now < datetime.time(14, 30) and odd_lot:
            market_type = MarketType.Odd

        # 確定價格類型
        price_type = PriceType.Limit
        if market_order:
            price = None
            if action == Action.BUY:
                price_type = PriceType.LimitUp
            elif action == Action.SELL:
                price_type = PriceType.LimitDown

        if best_price_limit:
            price = None
            if action == Action.BUY:
                price_type = PriceType.LimitDown
            elif action == Action.SELL:
                price_type = PriceType.LimitUp

        # 定盤處理：盤後定價只接受參考價，一律以收盤價成交
        if datetime.time(14, 00) <= now < datetime.time(14, 30) and not odd_lot:
            unfilled = best_price_limit
            if price is not None:
                stock = self.get_stocks([stock_id]).get(stock_id)
                # 買價低於、賣價高於收盤價不會照限價成交；查不到收盤價也不送
                unfilled = stock is None or (
                    float(price) < stock.close
                    if action == Action.BUY
                    else float(price) > stock.close
                )
            if unfilled:
                # 跟券商拒單一樣不送、不中斷：呼叫端可能已先撤單，後面的單要照常下
                logging.warning(
                    f"create_order: 盤後定價只以收盤價成交，{stock_id} 的芭樂價或比收盤價差的限價不送單"
                )
                return None
            market_type = MarketType.Fixing
            price = None
            price_type = PriceType.Reference

        # 確定交易條件
        order_type = OrderType.Stock  # 默認為現股交易
        if order_cond == OrderCondition.MARGIN_TRADING:
            order_type = OrderType.Margin
        elif order_cond == OrderCondition.SHORT_SELLING:
            order_type = OrderType.Short
        elif order_cond == OrderCondition.DAY_TRADING_SHORT:
            order_type = OrderType.DayTradeShort

        # 設定委託時效
        time_in_force = TimeInForce.ROD

        # 建立委託單物件
        try:
            # 根據市場類型確定數量單位
            qty = int(quantity) if odd_lot else int(quantity * 1000)

            # 建立委託單
            order = MLOrder(
                buy_sell=buy_sell,
                symbol=stock_id,
                price=str(price) if price is not None else None,
                quantity=qty,
                market_type=market_type,
                price_type=price_type,
                time_in_force=time_in_force,
                order_type=order_type,
            )
            # 送出委託單
            ret = self.sdk.stock.place_order(self.target_account, order)
            order_id = self._get_order_id(ret)
            logging.debug(f"#create_order order({order_id}): {order}")
            # 返回委託單號碼
            return order_id
        except Exception as e:
            logging.warning(f"create_order: 無法創建委託單: {e}")
            return None

    @staticmethod
    def _enum_name(value: Any) -> str:
        return str(value).upper().split(".")[-1]

    @classmethod
    def _is_odd_lot_market_type(cls, market_type: Any) -> bool:
        odd_lot_market_types = tuple(
            value
            for value in (
                getattr(MarketType, "IntradayOdd", None),
                getattr(MarketType, "Odd", None),
                getattr(MarketType, "EmgOdd", None),
            )
            if value is not None
        )
        if market_type in odd_lot_market_types:
            return True

        return cls._enum_name(market_type) in {
            "INTRADAYODD",
            "ODD",
            "EMGODD",
        }

    def update_order(
        self,
        order_id: str,
        price: float | None = None,
        quantity: float | None = None,
    ) -> str | None:
        """
        更新委託單

        Args:
            order_id (str): 委託單編號
            price (float, optional): 新價格
            quantity (float, optional): 新數量
        """
        try:
            order = self.get_orders()[order_id]
        except Exception as e:
            logging.warning(f"update_order: 無法取得委託單 {order_id}: {e}")
            return None
        logging.debug(
            f"#update_order price: {price}, qty: {quantity}, order({order_id}): {order}"
        )
        order_record = order.org_order
        odd_lot = self._is_odd_lot_market_type(getattr(order_record, "market_type", ""))
        remaining_qty = self._remaining_shares(order_record)
        # quantity 是新的待成交張數，只能減量，0 表刪單；先檢查再送任何委託異動
        new_qty = remaining_qty
        if quantity is not None:
            new_qty = round(quantity * 1000)
            if quantity != 0 and new_qty >= remaining_qty:
                raise ValueError(
                    f"update_order: 只能減量，委託單 {order_id} 剩 {remaining_qty} 股，"
                    f"新數量 {quantity} 張"
                )
        if price:
            if self._needs_reprice_by_replace(order_record, odd_lot):
                return self._replace_order(order, new_qty, price, odd_lot)
            try:
                self.sdk.stock.modify_price(
                    self.target_account, order_record, str(price), PriceType.Limit
                )
            except Exception as e:
                logging.warning(f"update_order: 無法更新委託單 {order_id} 的價格: {e}")
        if quantity is not None:
            # modify_volume 收的是「刪減股數」，0 表刪單
            cel_qty = remaining_qty - new_qty if quantity != 0 else 0
            self.sdk.stock.modify_volume(self.target_account, order_record, cel_qty)

    @staticmethod
    def _remaining_shares(order_record: Any) -> int:
        return (
            getattr(order_record, "org_qty", 0)
            - getattr(order_record, "filled_qty", 0)
            - getattr(order_record, "cel_qty", 0)
        )

    def _needs_reprice_by_replace(self, order_record: Any, odd_lot: bool) -> bool:
        """零股不能改價；盤中也不能改 PriceType（芭樂價、市價單改限價），都要刪單重下。"""
        now = datetime.datetime.now(TWMarket.tzinfo()).time()
        price_type = self._enum_name(getattr(order_record, "price_type", ""))
        return odd_lot or (
            self._enum_name(getattr(order_record, "market_type", "")) == "COMMON"
            and price_type in {"LIMITUP", "LIMITDOWN", "MARKET"}
            and now >= datetime.time(9, 0)
        )

    def _replace_order(
        self, order: Order, new_qty: int, price: float, odd_lot: bool
    ) -> str | None:
        """刪單後以新價格重下 new_qty 股；刪單或重下失敗都要報錯，否則委託會停在舊價或消失。"""
        cel_qty_before = getattr(order.org_order, "cel_qty", 0)
        remaining_before = self._remaining_shares(order.org_order)
        self.sdk.stock.modify_volume(self.target_account, order.org_order, 0)
        if new_qty == 0:
            return None
        # 刪單前一刻成交的股數算在新數量裡，不重下（與 modify_volume 減量的結果一致）
        canceled = self._confirmed_cancel_qty(order.order_id) - cel_qty_before
        qty = new_qty - (remaining_before - canceled)
        if qty <= 0:
            return None
        new_order_id = self.create_order(
            action=order.action,
            stock_id=order.stock_id,
            quantity=qty if odd_lot else qty / 1000,
            price=price,
            odd_lot=odd_lot,
            order_cond=order.order_condition,
        )
        if not new_order_id:
            raise RuntimeError(
                f"update_order: 委託單 {order.order_id} 已刪單改價，但以 {price} 重下 "
                f"{qty} 股失敗，原委託已不存在，請手動補單"
            )
        return new_order_id

    def _confirmed_cancel_qty(self, order_id: str) -> int:
        """重查委託，確認已刪到沒有剩餘量，回傳累計刪單股數。"""
        for attempt in range(3):
            if attempt:
                time.sleep(1)
            orders = self.get_orders() or {}
            record = getattr(orders.get(order_id), "org_order", None)
            if record is not None and self._remaining_shares(record) == 0:
                return getattr(record, "cel_qty", 0)
        raise RuntimeError(
            f"update_order: 已送出委託單 {order_id} 的刪單，但無法確認刪除股數，未重下，"
            "請確認委託狀態後手動補單"
        )

    def cancel_order(self, order_id: str) -> None:
        """
        取消委託單

        Args:
            order_id (str): 委託單編號
        """
        # 用 get_orders() 剛存的委託，不再每刪一筆查一次；刪不掉要報錯，否則呼叫端會再補下一次
        order_record = self.order_records.get(order_id)
        if not getattr(order_record, "can_cancel", False):
            # 快取沒有或還不可取消（可能在等交易所確認），重查一次
            if self.get_orders() is None:
                raise RuntimeError(f"cancel_order: 無法查詢委託單，委託單 {order_id} 未取消")
            order_record = self.order_records.get(order_id)
        if order_record is None:
            raise KeyError(f"cancel_order: 找不到委託單 {order_id}")
        logging.debug(f"#cancel_order order({order_id}): {order_record}")
        # 檢查是否可以取消
        if getattr(order_record, "can_cancel", False):
            # 使用 modify_volume 並將數量設為 0 來取消委託單
            self.sdk.stock.modify_volume(self.target_account, order_record, 0)
            logging.info(f"已取消委託單 {order_id}")
        else:
            logging.warning(f"cancel_order: 委託單 {order_id} 不可取消")

    def get_orders(self) -> dict[str, Order] | None:
        """
        獲取所有委託單

        Returns:
            dict: 委託單字典，以委託單編號為鍵
        """
        try:
            # 獲取所有委託單
            orders = self.sdk.stock.get_order_results(self.target_account)
            self.order_records = {self._get_order_id(order): order for order in orders}
            return {
                name: self._create_finlab_order(t)
                for name, t in self.order_records.items()
            }
        except Exception as e:
            logging.warning(f"get_orders: 無法獲取委託單，等待重試: {e}")
            return None

    def _get_order_id_from_order(self, order: Any) -> str:
        """
        從委託單對象中獲取委託單編號

        Args:
            order (object): 元富 API 返回的委託單對象

        Returns:
            str: 委託單編號
        """
        # 對於物件式資料，假設有 order_no 屬性
        if hasattr(order, "order_no"):
            return order.order_no

        # 對於字典式資料
        if isinstance(order, dict):
            return order.get("order_no", order.get("orderNo", order.get("ordNo", "")))

        # 嘗試其他常見屬性名
        for attr in ["order_no", "orderNo", "ordNo", "seq_no", "seqNo"]:
            if hasattr(order, attr):
                return getattr(order, attr)

        # 無法找到委託單編號
        logging.warning(f"無法從委託單中獲取編號: {order}")
        return f"unknown_{int(time.time())}"

    def _map_order_action(self, order: Any) -> Action:
        action = order.buy_sell
        if action == BSAction.Buy:
            return Action.BUY
        if action == BSAction.Sell:
            return Action.SELL
        raise ValueError(f"不支援的操作: {action}")

    def _map_order_condition(self, order: Any) -> OrderCondition:
        condition = order.order_type

        # 使用 if-elif-else 判斷替代字典查詢
        if condition == OrderType.Stock:
            return OrderCondition.CASH
        if condition == OrderType.Margin:
            return OrderCondition.MARGIN_TRADING
        if condition == OrderType.Short:
            return OrderCondition.SHORT_SELLING
        if condition == OrderType.DayTradeShort:
            return OrderCondition.DAY_TRADING_SHORT
        raise ValueError(f"不支援的訂單類型: {condition}")

    def _get_order_timestamp(self, order: Any) -> datetime.datetime:
        order_date = order.order_date
        order_time = order.order_time

        return datetime.datetime.strptime(order_date + order_time, "%Y%m%d%H%M%S%f")

    def _get_order_id(self, order: Any) -> str:
        order_no = getattr(order, "order_no", "")
        pre_order_no = getattr(order, "pre_order_no", "")
        order_id = order_no
        if order_id is None or order_id == "":
            order_id = pre_order_no

        return order_id

    def _create_finlab_order(self, order: Any) -> Order:
        """
        將元富委託單轉換為 finlab Order 格式

        Args:
            order (object): 元富委託單

        Returns:
            Order: finlab 格式的委託單
        """
        order_action = self._map_order_action(order)
        order_condition = self._map_order_condition(order)
        full_timestamp = self._get_order_timestamp(order)
        order_id = self._get_order_id(order)

        # 股票代碼
        stock_id = getattr(order, "symbol", "")

        # 價格
        price = getattr(order, "order_price", 0)

        divisor = 1000

        # 獲取各種數量
        org_qty = float(getattr(order, "org_qty", 0)) / divisor
        filled_qty = float(getattr(order, "filled_qty", 0)) / divisor
        canceled_qty = float(getattr(order, "cel_qty", 0)) / divisor
        error_code = order.err_code
        cancelable = getattr(order, "can_cancel", False)

        # 判斷狀態（減量過的委託依剩餘量判斷）
        status = OrderStatus.NEW
        # 取到股，避免除以 1000 後相減的浮點誤差
        remaining_qty = round(org_qty - filled_qty - canceled_qty, 3)

        if org_qty == filled_qty:
            status = OrderStatus.FILLED
        elif remaining_qty > 0 and cancelable:
            status = (
                OrderStatus.PARTIALLY_FILLED if filled_qty > 0 else OrderStatus.NEW
            )
        elif canceled_qty > 0 or error_code != "000000" or not cancelable:
            status = OrderStatus.CANCEL

        # 創建 finlab Order 物件
        return Order(
            order_id=order_id,
            stock_id=stock_id,
            action=order_action,
            price=price,
            quantity=org_qty - canceled_qty,
            filled_quantity=filled_qty,
            status=status,
            order_condition=order_condition,
            time=full_timestamp,
            org_order=order,
        )

    def get_stocks(self, stock_ids: list[str]) -> dict[str, Stock]:
        """
        獲取股票即時報價

        Args:
            stock_ids (list): 股票代碼列表

        Returns:
            dict: 股票報價字典，以股票代碼為鍵
        """
        ret = {}
        for s in stock_ids:
            try:
                # 確保已初始化行情連線
                if not hasattr(self.sdk, "marketdata") or not hasattr(
                    self.sdk.marketdata, "rest_client"
                ):
                    logging.warning("get_stocks: 行情連線尚未初始化，嘗試重新初始化")
                    try:
                        self.sdk.init_realtime(self.target_account)
                    except Exception as e:
                        logging.exception(f"get_stocks: 無法初始化行情連線: {e}")
                        continue

                # 使用正確的 API 獲取股票報價
                rest_stock = self.sdk.marketdata.rest_client.stock
                if not hasattr(rest_stock, "intraday") or not hasattr(
                    rest_stock.intraday, "quote"
                ):
                    logging.warning("get_stocks: SDK 無法存取 intraday.quote 方法")
                    continue

                quote = rest_stock.intraday.quote(symbol=s)
                logging.debug(quote)
                if quote:
                    ret[s] = self._create_finlab_stock(quote, s)
                else:
                    logging.warning(f"get_stocks: 無法獲取股票 {s} 的報價")
            except Exception as e:
                logging.warning(f"get_stocks: 獲取股票 {s} 報價時發生錯誤: {e}")

        return ret

    def _create_finlab_stock(
        self, quote: Any, original_stock_id: str | None = None
    ) -> Stock:
        """
        將元富行情轉換為 finlab Stock 格式

        Args:
            quote (object): 元富行情數據
            original_stock_id (str, optional): 原始股票代碼，用於備份

        Returns:
            Stock: finlab 格式的股票數據
        """
        # 嘗試直接從對象中獲取屬性
        try:
            stock_id = quote.get("symbol", original_stock_id)
            open_price = float(quote.get("openPrice", 0) or 0)
            high_price = float(quote.get("highPrice", 0) or 0)
            low_price = float(quote.get("lowPrice", 0) or 0)
            # 今天還沒成交時 closePrice 不揭示，改用參考價或昨收
            close_price = float(
                quote.get("closePrice")
                or quote.get("referencePrice")
                or quote.get("previousClose")
                or 0
            )

            logging.debug(
                f"stock_id: {stock_id}, open_price: {open_price}, high_price: {high_price}, low_price: {low_price}, close_price: {close_price}"
            )

            # 即時委買委賣
            bids = quote.get("bids", [])
            asks = quote.get("asks", [])

            bid_price = 0
            bid_volume = 0
            ask_price = 0
            ask_volume = 0

            # 如果有委買資訊
            if bids and len(bids) > 0:
                first_bid = bids[0]
                if "price" in first_bid:
                    bid_price = float(first_bid.get("price", 0) or 0)
                if "size" in first_bid:
                    bid_volume = float(first_bid.get("size", 0) or 0)

            # 如果有委賣資訊
            if asks and len(asks) > 0:
                first_ask = asks[0]
                if "price" in first_ask:
                    ask_price = float(first_ask.get("price", 0) or 0)
                if "size" in first_ask:
                    ask_volume = float(first_ask.get("size", 0) or 0)

            # 確保股票代碼不為空
            if not stock_id and original_stock_id:
                stock_id = original_stock_id

            # 提取漲跌幅
            pct_change = get_first_valid_float(quote, "changePercent", "change_rate")

            # 返回 finlab Stock 物件
            return Stock(
                stock_id=stock_id,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                bid_price=bid_price,
                ask_price=ask_price,
                bid_volume=bid_volume,
                ask_volume=ask_volume,
                pct_change=pct_change,
            )
        except Exception as e:
            logging.warning(f"_create_finlab_stock: 轉換時發生錯誤: {e}")
            return Stock(
                stock_id=original_stock_id,
                open=0,
                high=0,
                low=0,
                close=0,
                bid_price=0,
                ask_price=0,
                bid_volume=0,
                ask_volume=0,
            )

    def get_position(self) -> Position:
        """
        獲取當前持有部位

        Returns:
            Position: 持有部位對象
        """
        try:
            # 獲取持倉
            inventory_response = self.sdk.accounting.inventories(self.target_account)
            positions = []
            # 從 position_summaries 列表中獲取持倉資訊
            if hasattr(inventory_response, "position_summaries"):
                position_summaries = getattr(
                    inventory_response, "position_summaries", []
                )
                if position_summaries and hasattr(position_summaries, "__iter__"):
                    for position in position_summaries:
                        # 確定交易條件
                        order_condition = OrderCondition.CASH
                        order_type = getattr(position, "order_type", "")
                        order_type_name = getattr(position, "order_type_name", "")

                        # 判斷交易類型
                        if order_type in ["1", "3"] or "融資" in order_type_name:
                            order_condition = OrderCondition.MARGIN_TRADING
                        elif order_type in ["2", "4"] or "融券" in order_type_name:
                            order_condition = OrderCondition.SHORT_SELLING

                        # 取得股票代碼和數量
                        stock_id = getattr(position, "symbol", "")
                        quantity_str = getattr(position, "current_quantity", "0")

                        # 分析買賣方向以確定數量的正負
                        buy_sell = getattr(position, "buy_sell", "")

                        try:
                            # 轉換數量為數字並轉為張
                            quantity = Decimal(quantity_str.replace(",", "")) / 1000

                            # 如果有數量，增加到持倉列表
                            if quantity != 0:
                                # 確定數量的正負値（融券是負值）
                                quantity_sign = (
                                    -1
                                    if (
                                        order_condition == OrderCondition.SHORT_SELLING
                                        or buy_sell == "S"
                                    )
                                    else 1
                                )
                                positions.append(
                                    {
                                        "stock_id": stock_id,
                                        "quantity": quantity * quantity_sign,
                                        "order_condition": order_condition,
                                    }
                                )
                        except (ValueError, TypeError) as e:
                            logging.warning(
                                f"get_position: 無法解析數量 {quantity_str}: {e}"
                            )
            else:
                raise RuntimeError("回傳物件中無 position_summaries 屬性")

            logging.info(f"get_position: 成功獲取持倉，共 {len(positions)} 筆")
            return Position.from_list(positions)
        except Exception as e:
            # 不回傳空部位：空部位會被當成沒持股而重複買進
            logging.warning(f"get_position: 獲取持倉失敗: {e}")
            raise

    def get_total_balance(self) -> float:
        """
        計算帳戶總淨值

        總淨值 = 現股市值 + (融資市值 - 融資金額) + (擔保金 + 保證金 - 融券市值) + 現金 + 未交割款項

        Returns:
            float: 總淨值
        """
        # 獲取可用資金
        cash = self.get_cash()

        # 獲取未交割款項
        settlements = self.get_settlement()

        # 獲取庫存資料；查不到要報錯，不回傳只剩現金的淨值：偏小的淨值會讓部位被算成全賣
        position_response = self.sdk.accounting.inventories(self.target_account)

        # 從帳戶摘要獲取融資/融券相關資訊
        account_summary = getattr(position_response, "account_summary", None)

        if account_summary:
            # 從API獲取各項數值
            margin_position_market_value = float(
                getattr(account_summary, "margin_position_market_value_sum", 0)
                or 0
            )  # 融資市值
            margin_amount = float(
                getattr(account_summary, "margin_amount_sum", 0) or 0
            )  # 融資金額
            short_position_market_value = float(
                getattr(account_summary, "short_position_market_value_sum", 0)
                or 0
            )  # 融券市值
            short_collateral = float(
                getattr(account_summary, "short_collateral_sum", 0) or 0
            )  # 擔保品
            guarantee_amount = float(
                getattr(account_summary, "guarantee_amount_sum", 0) or 0
            )  # 保證金

            # 計算總市值
            total_market_value = float(
                getattr(position_response, "market_value", 0) or 0
            )

            # 計算現股市值（總市值減去融資和融券市值）
            cash_position_market_value = (
                total_market_value
                - margin_position_market_value
                - short_position_market_value
            )

            # 套用公式計算總淨值
            total_balance = (
                cash_position_market_value  # 現股市值
                + (margin_position_market_value - margin_amount)  # 融資淨值
                + (
                    short_collateral
                    + guarantee_amount
                    - short_position_market_value
                )  # 融券淨值
                + cash  # 可用資金
                + settlements  # 未交割款項
            )

            logging.info(
                f"總淨值計算: 現股市值={cash_position_market_value}, 融資淨值={(margin_position_market_value - margin_amount)}, "
                f"融券淨值={(short_collateral + guarantee_amount - short_position_market_value)}, "
                f"現金={cash}, 未交割款項={settlements}"
            )

            return total_balance
        # 如果沒有帳戶摘要，使用簡化的計算方式
        total_market_value = float(
            getattr(position_response, "market_value", 0) or 0
        )
        logging.warning("帳戶摘要資訊不完整，使用簡化的淨值計算方式")
        return total_market_value + cash + settlements

    def get_cash(self) -> float:
        """
        獲取可用資金

        Returns:
            float: 可用資金
        """
        # 每個來源都查詢失敗時報錯：回傳 0 會讓淨值偏小
        error: Exception | None = None
        answered = False
        # 先嘗試使用 skbank_balance
        if hasattr(self.sdk.accounting, "skbank_balance"):
            try:
                balance = self.sdk.accounting.skbank_balance(self.target_account)
                answered = True
                if balance is not None:
                    available_balance = getattr(balance, "available_balance", 0)
                    # 確保 available_balance 不為 None
                    if available_balance is not None:
                        try:
                            # 處理可能的字串格式（例如去除逗號）
                            if isinstance(available_balance, str):
                                available_balance = (
                                    available_balance.strip().replace(",", "")
                                )
                            return float(available_balance)
                        except (ValueError, TypeError):
                            logging.warning(
                                f"get_cash: 無法將 available_balance 轉換為浮點數: {available_balance}"
                            )
            except Exception as e:
                error = e
                logging.warning(f"get_cash: 無法獲取 skbank_balance: {e}")

        # 如果 skbank_balance 失敗或找不到有效餘額，嘗試 bank_balance
        if hasattr(self.sdk.accounting, "bank_balance"):
            try:
                balance = self.sdk.accounting.bank_balance(self.target_account)
                answered = True
                if balance and isinstance(balance, list) and len(balance) > 0:
                    available_balance = getattr(balance[0], "available_balance", 0)
                    # 確保 available_balance 不為 None
                    if available_balance is not None:
                        try:
                            # 處理可能的字串格式
                            if isinstance(available_balance, str):
                                available_balance = (
                                    available_balance.strip().replace(",", "")
                                )
                            return float(available_balance)
                        except (ValueError, TypeError):
                            logging.warning(
                                f"get_cash: 無法將 bank_balance 中的 available_balance 轉換為浮點數: {available_balance}"
                            )
            except Exception as e:
                error = e
                logging.warning(f"get_cash: 無法獲取 bank_balance: {e}")

        if error is not None and not answered:
            raise RuntimeError(f"get_cash: 查詢可用資金失敗: {error}") from error
        logging.warning("get_cash: 無法從任何來源獲取可用資金")
        return 0

    def get_settlement(self) -> float:
        """
        獲取未交割款項

        Returns:
            float: 未交割款項
        """
        total_settlement = 0

        # 檢查是否支援 history_settlement
        if hasattr(self.sdk.accounting, "history_settlement"):
            history_settlement = self._get_settlement_from_history_settlement()
            try:
                total_settlement += float(history_settlement)
            except (ValueError, TypeError):
                logging.warning(
                    f"get_settlement: 無法轉換 history_settlement 為數字: {history_settlement}"
                )

        # 檢查是否支援 today_settlement
        if hasattr(self.sdk.accounting, "today_settlement"):
            today_settlement = self._get_settlement_from_today_settlement()
            try:
                total_settlement += float(today_settlement)
            except (ValueError, TypeError):
                logging.warning(
                    f"get_settlement: 無法轉換 today_settlement 為數字: {today_settlement}"
                )

        return total_settlement

    def _get_settlement_from_history_settlement(self) -> float:
        """
        從歷史交割記錄中獲取未交割款項

        Returns:
            float: 未交割款項
        """
        # 查詢區間是交易日期：往前多查幾天，週一或連假後才不會漏掉上個交易日的款項
        today = datetime.datetime.now(TWMarket.tzinfo())
        today_str = today.strftime("%Y%m%d")
        start_str = (today - datetime.timedelta(days=10)).strftime("%Y%m%d")

        # 查詢交割款
        response = self.sdk.accounting.history_settlement(
            self.target_account, start_str, today_str
        )

        # 加總交割日在今天之後的 net_amount（今天交割的由 today_settlement 計入）
        settlement_amount = 0
        settlements = getattr(response, "settlements", [])
        if hasattr(settlements, "__iter__"):
            for s in settlements:
                if getattr(s, "s_date", "") <= today_str:
                    continue
                net_amount = getattr(s, "net_amount", "0")
                try:
                    # 移除千分位符號並轉換為浮點數
                    net_amount_cleaned = net_amount.strip().replace(",", "")
                    settlement_amount += float(net_amount_cleaned)
                except (ValueError, TypeError):
                    logging.warning(f"無法解析金額: {net_amount}")

        return settlement_amount

    def _get_settlement_from_today_settlement(self) -> float:
        """
        從今日交割中獲取未交割款項

        Returns:
            float: 未交割款項
        """
        today_settlements = self.sdk.accounting.today_settlement(self.target_account)
        return getattr(today_settlements, "net_amount", 0)

    def support_day_trade_condition(self) -> bool:
        """
        是否支援當沖交易

        Returns:
            bool: 是否支援當沖交易
        """
        # 從帳戶資訊判斷是否支援當沖
        return hasattr(
            self.target_account, "s_mark"
        ) and self.target_account.s_mark in ["B", "Y", "A"]

    def sep_odd_lot_order(self) -> bool:
        """
        是否支援零股交易

        Returns:
            bool: 是否支援零股交易
        """
        return True

    def get_price_info(self) -> dict[str, Any]:
        """
        獲取價格信息

        Returns:
            dict: 價格信息字典
        """
        ref = data.get("reference_price")
        return ref.set_index("stock_id").to_dict(orient="index")

    def get_market(self) -> TWMarket:
        """
        獲取市場信息

        Returns:
            TWMarket: 台灣市場對象
        """
        return TWMarket()
