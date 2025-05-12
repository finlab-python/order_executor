"""
MasterlinkAccount 模組

實現與元富證券 API 交互的 Account 類
"""

import datetime
import logging
import time
import os
from decimal import Decimal

from finlab.online.base_account import Account, Stock, Order
from finlab.online.enums import *
from finlab.online.order_executor import Position
from finlab import data
from finlab.markets.tw import TWMarket
from masterlink_sdk import MasterlinkSDK, Order as MLOrder, Account as MLAccount, BSAction, MarketType, PriceType, \
    TimeInForce, OrderType


class MasterlinkAccount(Account):
    """
    元富證券賬戶類
    實現與元富證券 API 的交互
    """

    required_module = 'masterlink_sdk'  # 需要的 Python 包名稱
    module_version = '1.0.0'  # 需要的版本號

    def __init__(self,
                 base_url=None,
                 national_id=None,
                 account=None,
                 account_pass=None,
                 cert_path=None,
                 cert_pass=None):
        """
        初始化元富證券賬戶
        
        Args:
            national_id (str, optional): 身分證字號。預設從環境變數獲取。
            account (str, optional): 帳號。預設從環境變數獲取。
            account_pass (str, optional): 登入密碼。預設從環境變數獲取。
            cert_path (str, optional): 憑證路徑。預設從環境變數獲取。
            cert_pass (str, optional): 憑證密碼。預設從環境變數獲取。
        """
        # 從參數或環境變數獲取登錄信息
        self.base_url = base_url or os.environ.get('MASTERLINK_BASE_URL')
        self.national_id = national_id or os.environ.get('MASTERLINK_NATIONAL_ID')
        self.account = account or os.environ.get('MASTERLINK_ACCOUNT')
        self.account_pass = account_pass or os.environ.get('MASTERLINK_ACCOUNT_PASS')
        self.cert_path = cert_path or os.environ.get('MASTERLINK_CERT_PATH')
        self.cert_pass = cert_pass or os.environ.get('MASTERLINK_CERT_PASS')

        if not all([self.national_id, self.account_pass, self.cert_path]):
            raise ValueError(
                "缺少必要的登錄信息。請確保設置了 MASTERLINK_NATIONAL_ID, MASTERLINK_ACCOUNT_PASS, MASTERLINK_CERT_PATH 環境變數或直接提供參數")

        # 初始化市場和時間戳
        self.market = 'tw_stock'
        self.order_records = {}

        # 初始化 SDK 和帳戶
        logging.info("初始化元富 SDK...")
        self.sdk = MasterlinkSDK(self.base_url)

        # 登入
        try:
            if self.cert_pass:
                self.accounts = self.sdk.login(
                    self.national_id,
                    self.account_pass,
                    self.cert_path,
                    self.cert_pass
                )
            else:
                # 若沒有提供憑證密碼，使用預設值 (技術文件申請)
                self.accounts = self.sdk.login(
                    self.national_id,
                    self.account_pass,
                    self.cert_path
                )
        except Exception as e:
            logging.error(f"登入失敗: {e}")
            raise Exception(f"無法登入元富證券: {e}")

        # 選擇帳戶
        if self.account:
            self.target_account = next((acc for acc in self.accounts if acc.account == self.account), None)
            if not self.target_account:
                logging.warning(f"未找到指定帳號 {self.account}，將使用第一個帳號")
                self.target_account = self.accounts[0] if self.accounts else None
        else:
            self.target_account = self.accounts[0] if self.accounts else None

        if not self.target_account:
            raise ValueError("無法獲取有效的元富證券帳戶")

        logging.info(f"成功登入帳號: {self.target_account.account}")

        # 初始化行情連線
        try:
            self.sdk.init_realtime(self.target_account)
            logging.info("初始化行情元件成功")
        except Exception as e:
            logging.warning(f"初始化行情元件失敗: {e}")

    def __del__(self):
        """
        當物件被刪除時，確保登出
        """
        try:
            if hasattr(self, 'sdk'):
                # 假設 SDK 有 logout 方法
                if hasattr(self.sdk, 'logout'):
                    self.sdk.logout()
        except Exception as e:
            logging.warning(f"登出時發生錯誤: {e}")
            pass

    def create_order(self, action, stock_id, quantity, price=None, odd_lot=False,
                     best_price_limit=False, market_order=False,
                     order_cond=OrderCondition.CASH):
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
        now = datetime.datetime.now()

        # 盤後零股處理
        if datetime.time(13, 40) < datetime.time(now.hour, now.minute) < datetime.time(14, 30) and odd_lot:
            market_type = MarketType.Odd

        # 定盤處理
        if datetime.time(14, 00) < datetime.time(now.hour, now.minute) < datetime.time(14, 30) and not odd_lot:
            market_type = MarketType.Fixing

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
                order_type=order_type
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

    def update_order(self, order_id, price=None, quantity=None):
        """
        更新委託單
        
        Args:
            order_id (str): 委託單編號
            price (float, optional): 新價格
            quantity (float, optional): 新數量
        """
        try:
            order = self.get_orders()[order_id]
            logging.debug(f"#update_order price: {price}, qty: {quantity}, order({order_id}): {order}")
            if price:
                order_record = order.org_order
                if getattr(order_record, 'market_type', '') == MarketType.IntradayOdd:
                    action = order.action
                    stock_id = order.stock_id
                    filled_qty = getattr(order_record, 'filled_qty', 0)
                    org_qty = getattr(order_record, 'org_qty', 0)
                    qty = org_qty - filled_qty
                    self.sdk.stock.modify_volume(self.target_account, order_record, 0)
                    return self.create_order(action=action, stock_id=stock_id, quantity=qty, price=price, odd_lot=True)
                else:
                    self.sdk.stock.modify_price(self.target_account, order_record, str(price), PriceType.Limit)
            if quantity:
                order_record = order.org_order
                self.sdk.stock.modify_volume(self.target_account, order_record, int(quantity))

        except Exception as e:
            logging.warning(f"update_order: 無法更新委託單 {order_id} 的數量: {e}")

    def cancel_order(self, order_id):
        """
        取消委託單
        
        Args:
            order_id (str): 委託單編號
        """
        try:
            order = self.get_orders()[order_id]
            order_record = order.org_order
            logging.debug(f"#cancel_order order({order_id}): {order}")
            # 檢查是否可以取消
            if getattr(order_record, 'can_cancel', False):
                # 使用 modify_volume 並將數量設為 0 來取消委託單
                self.sdk.stock.modify_volume(self.target_account, order_record, 0)
                logging.info(f"已取消委託單 {order_id}")
            else:
                logging.warning(f"cancel_order: 委託單 {order_id} 不可取消")
        except Exception as e:
            logging.warning(f"cancel_order: 無法取消委託單 {order_id}: {e}")

    def get_orders(self):
        """
        獲取所有委託單
        
        Returns:
            dict: 委託單字典，以委託單編號為鍵
        """
        try:
            # 獲取所有委託單
            orders = self.sdk.stock.get_order_results(self.target_account)
            self.order_records = {self._get_order_id(order): order for order in orders}
            result = {name: self._create_finlab_order(t) for name, t in self.order_records.items()}
            return result
        except Exception as e:
            logging.warning(f"get_orders: 無法獲取委託單，等待重試: {e}")
            return None

    def _get_order_id_from_order(self, order):
        """
        從委託單對象中獲取委託單編號
        
        Args:
            order (object): 元富 API 返回的委託單對象
            
        Returns:
            str: 委託單編號
        """
        # 對於物件式資料，假設有 order_no 屬性
        if hasattr(order, 'order_no'):
            return order.order_no

        # 對於字典式資料
        if isinstance(order, dict):
            return order.get('order_no', order.get('orderNo', order.get('ordNo', '')))

        # 嘗試其他常見屬性名
        for attr in ['order_no', 'orderNo', 'ordNo', 'seq_no', 'seqNo']:
            if hasattr(order, attr):
                return getattr(order, attr)

        # 無法找到委託單編號
        logging.warning(f"無法從委託單中獲取編號: {order}")
        return f"unknown_{int(time.time())}"

    def _map_order_action(self, order):
        action = getattr(order, 'buy_sell')
        if action == BSAction.Buy:
            return Action.BUY
        elif action == BSAction.Sell:
            return Action.SELL
        else:
            raise ValueError(f"不支援的操作: {action}")

    def _map_order_condition(self, order):
        condition = getattr(order, 'order_type')

        # 使用 if-elif-else 判斷替代字典查詢
        if condition == OrderType.Stock:
            return OrderCondition.CASH
        elif condition == OrderType.Margin:
            return OrderCondition.MARGIN_TRADING
        elif condition == OrderType.Short:
            return OrderCondition.SHORT_SELLING
        elif condition == OrderType.DayTradeShort:
            return OrderCondition.DAY_TRADING_SHORT
        else:
            raise ValueError(f"不支援的訂單類型: {condition}")

    def _get_order_timestamp(self, order):
        order_date = getattr(order, 'order_date')
        order_time = getattr(order, 'order_time')

        return datetime.datetime.strptime(order_date + order_time, '%Y%m%d%H%M%S%f')

    def _get_order_id(self, order):
        order_no = getattr(order, 'order_no', '')
        pre_order_no = getattr(order, 'pre_order_no', '')
        order_id = order_no
        if order_id is None or order_id == '':
            order_id = pre_order_no

        return order_id

    def _create_finlab_order(self, order):
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
        stock_id = getattr(order, 'symbol', '')

        # 價格
        price = getattr(order, 'order_price', 0)

        divisor = 1000

        # 獲取各種數量
        org_qty = float(getattr(order, 'org_qty', 0)) / divisor
        filled_qty = float(getattr(order, 'filled_qty', 0)) / divisor
        canceled_qty = float(getattr(order, 'cel_qty', 0)) / divisor
        error_code = getattr(order, 'err_code')
        cancelable = getattr(order, 'can_cancel', False)

        # 判斷狀態
        status = OrderStatus.NEW

        if org_qty == filled_qty:
            status = OrderStatus.FILLED
        elif filled_qty == 0 and canceled_qty == 0 and cancelable:
            status = OrderStatus.NEW
        elif org_qty > filled_qty + canceled_qty and cancelable and filled_qty > 0:
            status = OrderStatus.PARTIALLY_FILLED
        elif canceled_qty > 0 or error_code != '000000' or not cancelable:
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
            org_order=order
        )

    def get_stocks(self, stock_ids):
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
                if not hasattr(self.sdk, 'marketdata') or not hasattr(self.sdk.marketdata, 'rest_client'):
                    logging.warning(f"get_stocks: 行情連線尚未初始化，嘗試重新初始化")
                    try:
                        self.sdk.init_realtime(self.target_account)
                    except Exception as e:
                        logging.error(f"get_stocks: 無法初始化行情連線: {e}")
                        continue

                # 使用正確的 API 獲取股票報價
                rest_stock = self.sdk.marketdata.rest_client.stock
                if not hasattr(rest_stock, 'intraday') or not hasattr(rest_stock.intraday, 'quote'):
                    logging.warning(f"get_stocks: SDK 無法存取 intraday.quote 方法")
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

    def _create_finlab_stock(self, quote, original_stock_id=None):
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
            stock_id = quote.get('symbol', original_stock_id)
            open_price = float(quote.get('openPrice', 0) or 0)
            high_price = float(quote.get('highPrice', 0) or 0)
            low_price = float(quote.get('lowPrice', 0) or 0)
            close_price = float(quote.get('closePrice', 0) or 0)

            logging.debug(f'stock_id: {stock_id}, open_price: {open_price}, high_price: {high_price}, low_price: {low_price}, close_price: {close_price}')

            # 即時委買委賣
            bids = quote.get('bids', [])
            asks = quote.get('asks', [])

            bid_price = 0
            bid_volume = 0
            ask_price = 0
            ask_volume = 0

            # 如果有委買資訊
            if bids and len(bids) > 0:
                first_bid = bids[0]
                if 'price' in first_bid:
                    bid_price = float(first_bid.get('price', 0) or 0)
                if 'size' in first_bid:
                    bid_volume = float(first_bid.get('size', 0) or 0)

            # 如果有委賣資訊
            if asks and len(asks) > 0:
                first_ask = asks[0]
                if 'price' in first_ask:
                    ask_price = float(first_ask.get('price', 0) or 0)
                if 'size' in first_ask:
                    ask_volume = float(first_ask.get('size', 0) or 0)

            # 確保股票代碼不為空
            if not stock_id and original_stock_id:
                stock_id = original_stock_id

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
                ask_volume=ask_volume
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
                ask_volume=0
            )

    def get_position(self):
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
            if hasattr(inventory_response, 'position_summaries'):
                position_summaries = getattr(inventory_response, 'position_summaries', [])
                if position_summaries and hasattr(position_summaries, '__iter__'):
                    for position in position_summaries:
                        # 確定交易條件
                        order_condition = OrderCondition.CASH
                        order_type = getattr(position, 'order_type', '')
                        order_type_name = getattr(position, 'order_type_name', '')

                        # 判斷交易類型
                        if order_type in ['1', '3'] or '融資' in order_type_name:
                            order_condition = OrderCondition.MARGIN_TRADING
                        elif order_type in ['2', '4'] or '融券' in order_type_name:
                            order_condition = OrderCondition.SHORT_SELLING

                        # 取得股票代碼和數量
                        stock_id = getattr(position, 'symbol', '')
                        quantity_str = getattr(position, 'current_quantity', '0')

                        # 分析買賣方向以確定數量的正負
                        buy_sell = getattr(position, 'buy_sell', '')

                        try:
                            # 轉換數量為數字並轉為張
                            quantity = Decimal(quantity_str.replace(',', '')) / 1000

                            # 如果有數量，增加到持倉列表
                            if quantity != 0:
                                # 確定數量的正負値（融券是負值）
                                quantity_sign = -1 if (
                                        order_condition == OrderCondition.SHORT_SELLING or buy_sell == 'S') else 1
                                positions.append({
                                    'stock_id': stock_id,
                                    'quantity': quantity * quantity_sign,
                                    'order_condition': order_condition
                                })
                        except (ValueError, TypeError) as e:
                            logging.warning(f"get_position: 無法解析數量 {quantity_str}: {e}")
            else:
                # 如果沒有 position_summaries，單獨处理每個帳戶的持倉
                logging.warning("get_position: 回傳物件中無 position_summaries 屬性")

            logging.info(f"get_position: 成功獲取持倉，共 {len(positions)} 筆")
            return Position.from_list(positions)
        except Exception as e:
            logging.warning(f"get_position: 獲取持倉失敗: {e}")
            return Position({})

    def get_total_balance(self):
        """
        計算帳戶總淨值
        
        總淨值 = 現股市值 + (融資市值 - 融資金額) + (擔保金 + 保證金 - 融券市值) + 現金 + 未交割款項
        
        Returns:
            float: 總淨值
        """
        try:
            # 獲取可用資金
            cash = self.get_cash()

            # 獲取未交割款項
            settlements = self.get_settlement()

            # 獲取庫存資料
            try:
                position_response = self.sdk.accounting.inventories(self.target_account)

                # 從帳戶摘要獲取融資/融券相關資訊
                account_summary = getattr(position_response, 'account_summary', None)

                if account_summary:
                    # 從API獲取各項數值
                    margin_position_market_value = float(
                        getattr(account_summary, 'margin_position_market_value_sum', 0) or 0)  # 融資市值
                    margin_amount = float(getattr(account_summary, 'margin_amount_sum', 0) or 0)  # 融資金額
                    short_position_market_value = float(
                        getattr(account_summary, 'short_position_market_value_sum', 0) or 0)  # 融券市值
                    short_collateral = float(getattr(account_summary, 'short_collateral_sum', 0) or 0)  # 擔保品
                    guarantee_amount = float(getattr(account_summary, 'guarantee_amount_sum', 0) or 0)  # 保證金

                    # 計算總市值
                    total_market_value = float(getattr(position_response, 'market_value', 0) or 0)

                    # 計算現股市值（總市值減去融資和融券市值）
                    cash_position_market_value = total_market_value - margin_position_market_value - short_position_market_value

                    # 套用公式計算總淨值
                    total_balance = (
                            cash_position_market_value +  # 現股市值
                            (margin_position_market_value - margin_amount) +  # 融資淨值
                            (short_collateral + guarantee_amount - short_position_market_value) +  # 融券淨值
                            cash +  # 可用資金
                            settlements  # 未交割款項
                    )

                    logging.info(
                        f"總淨值計算: 現股市值={cash_position_market_value}, 融資淨值={(margin_position_market_value - margin_amount)}, " +
                        f"融券淨值={(short_collateral + guarantee_amount - short_position_market_value)}, " +
                        f"現金={cash}, 未交割款項={settlements}")

                    return total_balance
                else:
                    # 如果沒有帳戶摘要，使用簡化的計算方式
                    total_market_value = float(getattr(position_response, 'market_value', 0) or 0)
                    logging.warning("帳戶摘要資訊不完整，使用簡化的淨值計算方式")
                    return total_market_value + cash + settlements

            except Exception as e:
                logging.warning(f"無法獲取持倉資訊: {e}")
                return cash + settlements

        except Exception as e:
            logging.warning(f"get_total_balance: 獲取總資產失敗: {e}")
            return 0

    def get_cash(self):
        """
        獲取可用資金

        Returns:
            float: 可用資金
        """
        try:
            # 先嘗試使用 skbank_balance
            if hasattr(self.sdk.accounting, 'skbank_balance'):
                try:
                    balance = self.sdk.accounting.skbank_balance(self.target_account)
                    if balance is not None:
                        available_balance = getattr(balance, 'available_balance', 0)
                        # 確保 available_balance 不為 None
                        if available_balance is not None:
                            try:
                                # 處理可能的字串格式（例如去除逗號）
                                if isinstance(available_balance, str):
                                    available_balance = available_balance.strip().replace(',', '')
                                return float(available_balance)
                            except (ValueError, TypeError):
                                logging.warning(f"get_cash: 無法將 available_balance 轉換為浮點數: {available_balance}")
                except Exception as e:
                    logging.warning(f"get_cash: 無法獲取 skbank_balance: {e}")

            # 如果 skbank_balance 失敗或找不到有效餘額，嘗試 bank_balance
            if hasattr(self.sdk.accounting, 'bank_balance'):
                try:
                    balance = self.sdk.accounting.bank_balance(self.target_account)
                    if balance and isinstance(balance, list) and len(balance) > 0:
                        available_balance = getattr(balance[0], 'available_balance', 0)
                        # 確保 available_balance 不為 None
                        if available_balance is not None:
                            try:
                                # 處理可能的字串格式
                                if isinstance(available_balance, str):
                                    available_balance = available_balance.strip().replace(',', '')
                                return float(available_balance)
                            except (ValueError, TypeError):
                                logging.warning(
                                    f"get_cash: 無法將 bank_balance 中的 available_balance 轉換為浮點數: {available_balance}")
                except Exception as e:
                    logging.warning(f"get_cash: 無法獲取 bank_balance: {e}")

            logging.warning("get_cash: 無法從任何來源獲取可用資金")
            return 0

        except Exception as e:
            logging.warning(f"get_cash: 處理過程中發生異常: {e}")
            return 0

    def get_settlement(self):
        """
        獲取未交割款項

        Returns:
            float: 未交割款項
        """
        try:
            total_settlement = 0

            # 檢查是否支援 history_settlement
            if hasattr(self.sdk.accounting, 'history_settlement'):
                history_settlement = self._get_settlement_from_history_settlement()
                try:
                    total_settlement += float(history_settlement)
                except (ValueError, TypeError):
                    logging.warning(f"get_settlement: 無法轉換 history_settlement 為數字: {history_settlement}")

            # 檢查是否支援 today_settlement
            if hasattr(self.sdk.accounting, 'today_settlement'):
                today_settlement = self._get_settlement_from_today_settlement()
                try:
                    total_settlement += float(today_settlement)
                except (ValueError, TypeError):
                    logging.warning(f"get_settlement: 無法轉換 today_settlement 為數字: {today_settlement}")

            return total_settlement

        except Exception as e:
            logging.warning(f"get_settlement: 無法獲取未交割款項: {e}")
            return 0

    def _get_settlement_from_history_settlement(self):
        """
        從歷史交割記錄中獲取未交割款項

        Returns:
            float: 未交割款項
        """
        try:
            # 取得日期範圍
            today = datetime.datetime.now()
            today_str = today.strftime('%Y%m%d')
            one_days_ago = today - datetime.timedelta(days=1)
            one_days_ago_str = one_days_ago.strftime('%Y%m%d')

            # 查詢交割款
            response = self.sdk.accounting.history_settlement(
                self.target_account,
                one_days_ago_str,
                today_str
            )

            # 從 settlements 加總 net_amount
            settlement_amount = 0
            settlements = getattr(response, 'settlements', [])
            if hasattr(settlements, '__iter__'):
                for s in settlements:
                    net_amount = getattr(s, 'net_amount', '0')
                    try:
                        # 移除千分位符號並轉換為浮點數
                        net_amount_cleaned = net_amount.strip().replace(',', '')
                        settlement_amount += float(net_amount_cleaned)
                    except (ValueError, TypeError):
                        logging.warning(f"無法解析金額: {net_amount}")

            return settlement_amount
        except Exception as e:
            logging.warning(f"_get_settlement_from_history_settlement: 無法處理歷史交割: {e}")
            return 0

    def _get_settlement_from_today_settlement(self):
        """
        從今日交割中獲取未交割款項
        
        Returns:
            float: 未交割款項
        """
        try:
            today_settlements = self.sdk.accounting.today_settlement(self.target_account)
            settle_amount = 0
            if hasattr(today_settlements, 'net_amount'):
                settle_amount = today_settlements.net_amount

            return settle_amount
        except Exception as e:
            logging.warning(f"_get_settlement_from_today_settlement: 無法處理今日交割: {e}")
            return 0

    def support_day_trade_condition(self):
        """
        是否支援當沖交易
        
        Returns:
            bool: 是否支援當沖交易
        """
        # 從帳戶資訊判斷是否支援當沖
        return hasattr(self.target_account, 's_mark') and self.target_account.s_mark in ['B', 'Y', 'A']

    def sep_odd_lot_order(self):
        """
        是否支援零股交易
        
        Returns:
            bool: 是否支援零股交易
        """
        return True

    def get_price_info(self):
        """
        獲取價格信息
        
        Returns:
            dict: 價格信息字典
        """
        ref = data.get('reference_price')
        return ref.set_index('stock_id').to_dict(orient='index')

    def get_market(self):
        """
        獲取市場信息
        
        Returns:
            TWMarket: 台灣市場對象
        """
        return TWMarket()
