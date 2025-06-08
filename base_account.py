from typing import Any, Union, Dict, Optional
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod
from decimal import Decimal
import importlib.util
import datetime
import numbers
import logging

from finlab.config import get_default_market
from finlab.online.position import Position
from finlab.online.enums import *
from finlab.market import Market
from finlab import data

logger = logging.getLogger(__name__)

Number = Union[int, float, Decimal]

def typesafe_op(a: Number, b: Number, op: str) -> Number:
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        if op == '+':
            return a + b
        elif op == '-':
            return a - b
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if op == '+':
            return a + b
        elif op == '-':
            return a - b
    raise TypeError(f"Unsupported types for operation {op}: {type(a)}, {type(b)}")

@dataclass
class Order:
    """
    Order status

    委託單的狀態

    Attributes:
        order_id (str): 委託單的 id，與券商 API 所提供的 id 一致
        stock_id (str): 股票代號 ex: '2330'
        action (Action): 買賣方向，通常為 'BUY' 或是 'SELL'
        price (Number): 股票買賣的價格(限價單)
        quantity (Number): 委託股票的總數量（張數），允許小數點
        filled_quantity (Number): 以成交股票的數量（張數），允許小數點
        status (OrderStatus): 委託狀態，可以設定為：'NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCEL'
        time (datetime.datetime): 委託時間
        org_order (Any = None): 券商所提供的委託物件格式
    """

    order_id: str
    stock_id: str
    action: Action
    price: Number
    quantity: Number
    filled_quantity: Number
    status: OrderStatus
    order_condition: OrderCondition
    time: datetime.datetime
    org_order: Any = None


@dataclass
class Stock:
    """
    Stock

    即時股票資料

    Attributes:
        stock_id (str): 股票代號
        open (Number): 開盤價
        high (Number): 最高價
        low (Number): 最低價
        close (Number): 收盤價
        bid_price (Number): 買方第一檔價格
        bid_volume (Number): 買方第一檔量
        ask_price (Number): 賣方第一檔價格
        ask_volume (Number): 賣方第一檔量
    """

    stock_id: str
    open: Number
    high: Number
    low: Number
    close: Number
    bid_price: Number
    bid_volume: Number
    ask_price: Number
    ask_volume: Number

    def to_dict(self):
        return asdict(self)


class Account(ABC):

    # Required module name and version for the account implementation
    required_module: str = ""
    module_version: str = ""

    """股票帳戶的 abstract class
    可以繼承此 Account，來實做券商的帳戶買賣動作，目前已經實做 SinopacAccount (永豐證券) 以及 FugleAccount (玉山富果)，來進行交易。可以用以下方式建構物件並用來交易：

    永豐證券
    ```py
    import os
    from finlab.online.sinopac_account import SinopacAccount


    # 舊版請使用
    # shioaji < 1.0.0 and finlab < 0.3.18
    os.environ['SHIOAJI_ACCOUNT']= '永豐證券帳號'
    os.environ['SHIOAJI_PASSWORD']= '永豐證券密碼'

    # 新版請使用
    # shioaji >= 1.0.0 and finlab >= 0.3.18
    os.environ['SHIOAJI_API_KEY'] = '永豐證券API_KEY'
    os.environ['SHIOAJI_SECRET_KEY'] = '永豐證券SECRET_KEY'
    os.environ['SHIOAJI_CERT_PERSON_ID']= '身份證字號'

    # shioaji
    os.environ['SHIOAJI_CERT_PATH']= '永豐證券憑證路徑'
    os.environ['SHIOAJI_CERT_PASSWORD'] = '永豐證券憑證密碼' # 預設與身份證字號

    acc = SinopacAccount()
    ```
    玉山富果:
    ```py
    from finlab.online.fugle_account import FugleAccount
    import os
    os.environ['FUGLE_CONFIG_PATH'] = '玉山富果交易設定檔(config.ini.example)路徑'
    os.environ['FUGLE_MARKET_API_KEY'] = '玉山富果的行情API Token'

    acc = FugleAccount()
    ```

    """

    @classmethod
    def check_version(cls) -> None:

        m = cls.required_module
        v = cls.module_version

        # check module installed
        if importlib.util.find_spec(m) is None:
            logger.error(f"Module {m} is not installed. Please install it using pip.")

    @abstractmethod
    def create_order(
        self,
        action: Action,
        stock_id: str,
        quantity: Number,
        price: Optional[Number] = None,
        odd_lot: bool = False,
        market_order: bool = False,
        best_price_limit: Optional[Number] = None,
        order_cond: OrderCondition = OrderCondition.CASH,
    ) -> str:
        """產生新的委託單

        Args:
            action (Action): 買賣方向，通常為 'BUY' 或是 'SELL'

            stock_id (str): 股票代號 ex: '2330'

            quantity (Number): 委託股票的總數量（張數），允許小數點

            price (Number, optional): 股票買賣的價格(限價單)

            force (bool): 是否用最差之價格（長跌停）強制成交? 當成交量足夠時，可以比較快成交，然而當成交量低時，容易有大的滑價

            wait_for_best_price (bool): 是否用最佳之價格（長跌停），無限時間等待？當今天要出場時，可以開啟等漲停價來購買，當今天要買入時，可以掛跌停價等待買入時機。

        Returns:
            (str): order id 券商提供的委託單編號
        """
        pass

    @abstractmethod
    def update_order(
        self,
        order_id,
        price: Optional[Number] = None,
        quantity: Optional[Number] = None,
    ) -> None:
        """產生新的委託單

        Attributes:
            order_id (str): 券商所提供的委託單 ID
            price (Number, optional): 更新的限價
            quantity (Number, optional): 更新的待成交量

        Returns:
            (None): 無跳出 erorr 代表成功更新委託單
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id):
        """刪除委託單

        建議使用 刪除委託單此功能前，先使用 update_order() 來更新委託單的狀況！如下
        ```py
        acc.update_order()
        acc.cancel_order('ORDER_ID')
        ```

        Attributes:
            order_id (str): 券商所提供的委託單 ID

        Returns:
            (None): 代表成功更新委託單
        """
        pass

    @abstractmethod
    def get_orders(self) -> Dict[str, Order]:
        """拿到現在所有委託單

        Returns:
            (Dict[str, Order]): 所有委託單 id 與委託單資料
                !!! example
                    `{'12345A': Order(order_id='12345A', stock_id='5410',...),...}`
        """
        pass

    @abstractmethod
    def get_stocks(self, stock_ids) -> Dict[str, Stock]:
        """拿到現在股票報價

        Attributes:
            stock_ids (`list` of `str`): 一次拿取所有股票的報價，ex: ['1101', '2330']

        Returns:
            (dict): 報價資料，
                !!! example
                    `{'1101': Stock(stock_id='1101', open=31.15, high=31.85, low=31.1, close=31.65, bid_price=31.6, bid_volume=728.0, ask_price=31.65, ask_volume=202)}`
        """
        pass

    @abstractmethod
    def get_position(self) -> Position:
        """拿到當前帳戶的股票部位

        Returns:
            (Position): 當前股票部位
        """
        pass

    @abstractmethod
    def get_total_balance(self) -> int:
        """拿到當前帳戶的股票部位淨值"""
        pass

    @abstractmethod
    def get_cash(self) -> int:
        """拿到當前帳戶的現金"""
        pass

    @abstractmethod
    def get_settlement(self) -> int:
        """拿到當前帳戶的結算資料"""
        pass

    def sep_odd_lot_order(self):
        return True

    def get_price(self, stock_ids):

        s = self.get_stocks(stock_ids)

        price = {pname: s[pname].close for pname in s}

        for sid, p in price.items():
            if p == 0:
                bid_price = (
                    s[sid].bid_price if s[sid].bid_price != 0 else s[sid].ask_price
                )
                ask_price = (
                    s[sid].ask_price if s[sid].ask_price != 0 else s[sid].bid_price
                )

                price[sid] = typesafe_op(bid_price, ask_price, '+') / 2

            if price[sid] == 0:
                raise Exception(
                    f"Stock {sid} has no price to reference. Use latest close of previous trading day"
                )

        return price

    def get_market(self) -> Market:
        """拿到當前帳戶的市場"""
        return get_default_market()
