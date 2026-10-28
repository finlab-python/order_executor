from __future__ import annotations

import importlib
import sys
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from finlab.online.core.enums import Action, OrderCondition, OrderStatus

from ..utils.mock_helpers import patch_utc_host_clock

ACCOUNT = "S98875005091"
TWSE, TWOTC = 1, 2


class _List(list):
    """System.Collections.Generic.List 的替身"""

    def __class_getitem__(cls, item):
        return cls

    def Add(self, item):
        self.append(item)

    @property
    def Count(self):
        return len(self)


def _date(y, m, d):
    return NS(ushtYear=y, bytMon=m, bytDay=d)


class _FakeSpark:
    """同步模擬 YuantaSparkAPITrader：每個請求立刻從 OnResponse 回應"""

    def __init__(self, account) -> None:
        self.on_response = account._on_response
        self.sent: list = []
        self.records: dict = {}
        self.otc = {"6488"}
        self.reject = False

    def _reply(self, name, value):
        self.on_response(1, 1, name, None, value)
        return True

    def Login(self, *args):
        self.login_args = args
        return self._reply(
            "Login", NS(LoginStatus=NS(MsgCode="0001", MsgContent="", Count=1))
        )

    def SendStockOrder(self, account, orders):
        [o] = orders
        self.sent.append(o)
        if self.reject:
            row = NS(ReplyCode=1, OrderNO="", ErrNO="13022", Advisory="委託張數錯誤")
        elif o.TradeKind == 0:
            no = f"H{len(self.records):04d}"
            row = NS(ReplyCode=0, OrderNO=no, ErrNO="", Advisory="")
            shares = o.OrderQty if o.APCode in (2, 4) else o.OrderQty * 1000
            self.records[no] = NS(
                OrderNo=no,
                CompanyNo=o.StkCode,
                BS=o.BuySell,
                Price=o.Price,
                PriceFlag="2",
                APCode=o.APCode,
                OrderType=int(o.OrderType),
                OR_QTY=shares,
                CancelQty=0,
                OkQty=0,
                OrderStatus=20,
                TradeDate=_date(2026, 10, 21),
                AcceptDate=_date(2026, 10, 21),
                AcceptTime=NS(bytHour=9, bytMin=30, bytSec=1),
            )
        else:
            r = self.records[o.OrderNo]
            if o.TradeKind == 4:
                r.CancelQty, r.OrderStatus = r.OR_QTY - r.OkQty, 30
            elif o.TradeKind == 3:
                r.CancelQty += o.OrderQty if r.APCode in (2, 4) else o.OrderQty * 1000
            row = NS(ReplyCode=0, OrderNO=o.OrderNo, ErrNO="", Advisory="")
        return self._reply(
            "SendStockOrder",
            NS(ResultCount=NS(MsgCode="0001", MsgContent=""), ResultList=_List([row])),
        )

    def GetOrderTradeReport(self, not_show_cancel, account):
        return self._reply(
            "GetOrderTradeReport", NS(StkOrderList=_List(self.records.values()))
        )

    def GetWatchListAll(self, account, quotes):
        rows = [
            NS(
                StkCode=q.StockCode,
                YstPrice=560.0,
                DealPrice=580.0,
                OpenPrice=575.0,
                HighPrice=585.0,
                LowPrice=570.0,
                BuyPrice=999999999,
                BidQty=10,
                SellPrice=580.0,
                AskQty=5,
                UpStopPrice=616.0,
                DownStopPrice=504.0,
            )
            for q in quotes
            if (q.MarketType == TWOTC) == (q.StockCode in self.otc)
        ]
        return self._reply("GetWatchListAll", NS(QueryWatchList=_List(rows)))

    def GetStoreSummary(self, account):
        stores = [
            NS(
                TradeKind=0,
                StkCode="2330",
                StockQty=2300,
                Cost=1_150_000,
                ReturnAmt=180_000,
            ),
            NS(
                TradeKind=3,
                StkCode="2330",
                StockQty=1000,
                Cost=240_000,
                ReturnAmt=10_000,
            ),
            NS(
                TradeKind=4,
                StkCode="2603",
                StockQty=2000,
                Cost=90_000,
                ReturnAmt=-5_000,
            ),
            NS(TradeKind=6, StkCode="2603", StockQty=1000, Cost=0, ReturnAmt=0),
        ]
        return self._reply("GetStoreSummary", NS(StkStoreList=_List(stores)))

    def GetBankBalance(self, account):
        return self._reply(
            "GetBankBalance",
            NS(BankBalanceList=_List([NS(AvailableBalance=1_000_000.0)])),
        )

    def GetStkTransactionOutlay(self, account):
        outlays = [
            NS(SettlementDay="2026/10/21", SettlementAmt=-100.0),
            NS(SettlementDay="2026/10/22", SettlementAmt=-200.0),
            NS(SettlementDay="2026/10/23", SettlementAmt=50.0),
        ]
        return self._reply(
            "GetStkTransactionOutlay", NS(TransactionOutlayList=_List(outlays))
        )


def _fake_sdk(trader):
    return NS(
        StockOrder=NS,
        Quote=NS,
        YuantaSparkAPITrader=trader,
        OnResponseEventHandler=lambda f: f,
        enumMarketType=NS(TWSE=TWSE, TWOTC=TWOTC),
        enumEnvironmentMode=NS(PROD="PROD", UAT="UAT"),
    )


@pytest.fixture
def make_account(monkeypatch: pytest.MonkeyPatch):
    def make(utc_time: tuple = (2, 0, 0)):
        sys.modules.pop("finlab.online.brokers.yuanta", None)
        module = importlib.import_module("finlab.online.brokers.yuanta")
        patch_utc_host_clock(monkeypatch, module, utc_time)
        monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
        acc = module.YuantaAccount.__new__(module.YuantaAccount)
        acc.account = ACCOUNT
        acc._init_state()
        acc._sdk, acc._List = _fake_sdk(None), _List
        acc.api = _FakeSpark(acc)
        return acc, module

    return make


class _Trader:
    """登入流程用：Open 後回報連線，Login 回報成功"""

    def __init__(self) -> None:
        self.handlers: list = []
        self.OnResponse = self

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def Open(self, mode):
        self.mode = mode
        self.handlers[0](0, 1, "", None, "Connect")

    def Login(self, *args):
        self.args = args
        status = NS(MsgCode="0001", MsgContent="", Count=1)
        self.handlers[0](1, 1, "Login", None, NS(LoginStatus=status))
        return True


def test_login_with_certificate_on_macos_and_linux(make_account, monkeypatch):
    _, module = make_account()
    trader = _Trader()
    sdk = _fake_sdk(lambda: trader)
    monkeypatch.setattr(module, "_load_sdk", lambda api_dir: (sdk, _List))
    for key, value in {
        "YUANTA_ACCOUNT": "98875005091",
        "YUANTA_PASSWORD": "pw",
        "YUANTA_CERT_PATH": "/c.pfx",
        "YUANTA_CERT_PASSWORD": "cpw",
        "YUANTA_API_DIR": "/api",
    }.items():
        monkeypatch.setenv(key, value)

    module.YuantaAccount()
    assert (trader.mode, trader.args) == ("PROD", ("/c.pfx", "cpw", ACCOUNT, "pw"))


@pytest.mark.parametrize(
    "utc_time, odd_lot, kwargs, ap_code, qty, price",
    [
        ((2, 0, 0), False, {}, 0, 2, 580.0),
        ((2, 0, 0), True, {}, 4, 300, 580.0),
        ((5, 40, 0), True, {}, 2, 300, 580.0),
        ((6, 0, 0), False, {}, 7, 2, 580.0),
        ((2, 0, 0), False, {"market_order": True}, 0, 2, 616.0),
        ((2, 0, 0), True, {"best_price_limit": True}, 4, 300, 504.0),
    ],
)
def test_create_order_session_and_price(
    make_account, utc_time, odd_lot, kwargs, ap_code, qty, price
):
    acc, _ = make_account(utc_time)
    order_id = acc.create_order(
        Action.BUY, "2330", qty, price="580", odd_lot=odd_lot, **kwargs
    )

    [sent] = acc.api.sent
    assert order_id == "H0000"
    assert (sent.APCode, sent.OrderQty, sent.Price, sent.PriceFlag, sent.TradeKind) == (
        ap_code,
        qty,
        price,
        " ",
        0,
    )


def test_fixing_session_skips_orders_that_cannot_fill_and_rejects_return_none(
    make_account,
):
    acc, _ = make_account((6, 10, 0))
    assert acc.create_order(Action.BUY, "2330", 1, price=575) is None
    assert (
        acc.create_order(Action.BUY, "2330", 1, price=580, best_price_limit=True)
        is None
    )
    assert acc.api.sent == []
    acc.api.reject = True
    assert acc.create_order(Action.SELL, "2330", 1, price=580) is None


def test_quotes_fall_back_to_otc(make_account):
    acc, _ = make_account()
    stocks = acc.get_stocks(["2330", "6488"])
    assert set(stocks) == {"2330", "6488"} and acc._markets["6488"] == TWOTC
    assert stocks["2330"].bid_price == 0 and stocks["2330"].pct_change == pytest.approx(
        3.5714, abs=1e-3
    )


def test_get_orders_and_modify(make_account):
    acc, _ = make_account()
    acc.create_order(Action.BUY, "2330", 500, price=580, odd_lot=True)
    acc.create_order(
        Action.SELL, "2330", 3, price=600, order_cond=OrderCondition.MARGIN_TRADING
    )
    acc.api.records["H0000"].OkQty = 200

    orders = acc.get_orders()
    assert (orders["H0000"].quantity, orders["H0000"].filled_quantity) == (
        Decimal("0.5"),
        Decimal("0.2"),
    )
    assert orders["H0000"].status == OrderStatus.PARTIALLY_FILLED
    assert (orders["H0001"].quantity, orders["H0001"].order_condition) == (
        3,
        OrderCondition.MARGIN_TRADING,
    )

    acc.update_order("H0001", quantity=1)  # 減量 2 張
    acc.update_order("H0001", price=605)  # 原生改價
    reduce, reprice = acc.api.sent[2:]
    assert (reduce.TradeKind, reduce.OrderQty, reduce.OrderNo) == (3, 2, "H0001")
    assert (reprice.TradeKind, reprice.OrderQty, reprice.Price) == (7, 1, 605.0)
    with pytest.raises(ValueError, match="只能減量"):
        acc.update_order("H0001", quantity=1)

    acc.cancel_order("H0001")
    assert acc.get_orders()["H0001"].status == OrderStatus.CANCEL
    n = len(acc.api.sent)
    acc.cancel_order("H0001")  # 已取消的不再送
    assert len(acc.api.sent) == n


def test_odd_lot_reprice_cancels_and_replaces_the_rest(make_account):
    acc, _ = make_account()
    acc.create_order(Action.BUY, "2330", 500, price=580, odd_lot=True)
    acc.api.records["H0000"].OkQty = 100
    real_send = acc.api.SendStockOrder

    def send(account, orders):
        if orders[0].TradeKind == 4:  # 刪單前一刻又成交 100 股
            acc.api.records["H0000"].OkQty = 200
        return real_send(account, orders)

    acc.api.SendStockOrder = send
    assert acc.update_order("H0000", price=583) == "H0001"
    cancel, new = acc.api.sent[1:]
    assert (cancel.TradeKind, cancel.OrderQty) == (4, 400)
    assert (new.TradeKind, new.APCode, new.OrderQty, new.Price) == (0, 4, 300, 583.0)


def test_position_cash_settlement_and_balance(make_account):
    acc, _ = make_account((3, 0, 0))
    quantities = {
        (p["stock_id"], p["order_condition"]): p["quantity"]
        for p in acc.get_position().position
    }
    assert quantities == {
        ("2330", OrderCondition.CASH): Decimal("2.3"),
        ("2330", OrderCondition.MARGIN_TRADING): 1,
        ("2603", OrderCondition.SHORT_SELLING): -2,
    }
    assert acc.get_cash() == 1_000_000
    assert acc.get_settlement() == -150
    assert acc.get_total_balance() == 1_665_000 + 1_000_000 - 150
