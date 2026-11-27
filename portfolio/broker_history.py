"""從 finlab-online 的券商帳戶抓實盤覆盤需要的成交、持股與資金紀錄。

每家券商 API 能給的不一樣，抓不到的部分寫進 ``BrokerHistory.limitations``，
不自行補假資料。各券商的差異見文件「實盤覆盤」。
"""

from __future__ import annotations

import datetime
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = ["BrokerHistory", "fetch_history"]

_THROTTLE = 0.25  # 永豐帳務查詢 25 次／5 秒、富邦 5 次／秒


@dataclass
class BrokerHistory:
    """券商 API 取得的歷史紀錄。

    Attributes:
        fills: 成交（:func:`finlab.portfolio.trade_review.normalize_fills` 格式），
            可能含起始日前買進、仍在期間內持有的部位。
        holdings: 目前庫存股數 ``{代號: 股數}``。
        cash: 目前帳戶現金（成交日制）；只有入出金紀錄完整時才有值，可據此算帳戶淨值。
        cash_events: 券商提供的現金事件（股利、入出金…），欄位 ``time, amount, type``。
        dividends: ``cash_events`` 是否已含股利；為 False 時由 FinLab 除權息資料自動補。
        limitations: 這家券商 API 的限制說明。
        prices: FinLab 沒有的市場（加密貨幣）由券商 API 取得的日收盤價。
    """

    fills: pd.DataFrame
    holdings: dict[str, float]
    cash: float | None = None
    cash_events: pd.DataFrame | None = None
    dividends: bool = False
    limitations: list[str] = field(default_factory=list)
    prices: pd.DataFrame | None = None


def _fill(
    t: Any, sid: Any, action: str, qty: Any, price: Any, fee: Any = 0.0, tax: Any = 0.0
) -> dict[str, Any]:
    return {
        "time": pd.to_datetime(str(t), format="mixed"),
        "stock_id": str(sid).strip(),
        "action": action,
        "quantity": float(qty),
        "price": float(price),
        "fee": float(fee or 0.0),
        "tax": float(tax or 0.0),
    }


def _fills(rows: list[dict[str, Any]]) -> pd.DataFrame:
    cols = ["time", "stock_id", "action", "quantity", "price", "fee", "tax"]
    df = pd.DataFrame(rows, columns=cols)
    return df[df["quantity"] > 0].reset_index(drop=True)


def _chunks(
    start: pd.Timestamp, end: pd.Timestamp, days: int
) -> Iterator[tuple[pd.Timestamp, pd.Timestamp]]:
    while start <= end:
        stop = min(start + pd.Timedelta(days=days - 1), end)
        yield start, stop
        start = stop + pd.Timedelta(days=1)


def current_shares(account: Any) -> dict[str, float]:
    """``account.get_position()`` 的張數換成股數（只計多單）。"""
    lot = account.get_market().get_board_lot_size()
    out: dict[str, float] = defaultdict(float)
    for p in account.get_position().position:
        qty = float(p["quantity"]) * lot
        if qty > 0:
            out[str(p["stock_id"])] += qty
    return dict(out)


def estimate_tw_charges(fills: pd.DataFrame, fee_ratio: float) -> pd.DataFrame:
    """依手續費率與法定證交稅率（ETF 0.1%、股票 0.3%）估算台股費稅。"""
    gross = fills["quantity"] * fills["price"]
    tax_rate = fills["stock_id"].str.startswith("00").map({True: 0.001, False: 0.003})
    sell = fills["action"] == "sell"
    return fills.assign(
        fee=np.floor(gross * fee_ratio),
        tax=np.floor((gross * tax_rate).where(sell, 0.0)),
    )


def _per_share(total: float, shares: float, last_price: float) -> float:
    """部位明細的 price 可能是總金額；取與現價較接近的解讀。"""
    total = abs(float(total))
    if shares <= 0 or not last_price:
        return total
    unit = total / shares
    return (
        unit
        if abs(math.log(unit / last_price)) < abs(math.log(total / last_price))
        else total
    )


# --------------------------------------------------------------- 永豐、口袋
def _shioaji_like(
    account: Any, start: pd.Timestamp, end: pd.Timestamp, unit: Any = None, **_: Any
) -> BrokerHistory:
    api, acct = account.api, account.api.stock_account
    kw = {"unit": unit} if unit is not None else {}
    rows, notes = [], []
    has_detail = hasattr(api, "list_profit_loss_detail")

    for p in api.list_profit_loss(
        acct, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), **kw
    ):
        if "Short" in str(getattr(p, "cond", "")):
            notes.append(f"{p.code} 融券交易不在覆盤範圍，已略過")
            continue
        if not has_detail:
            rows.append(_fill(p.date, p.code, "sell", p.quantity, p.price))
            continue
        time.sleep(_THROTTLE)
        legs = api.list_profit_loss_detail(acct, detail_id=p.id, **kw)
        cost = sum(float(d.cost) for d in legs)
        for d in legs:
            fee = (
                float(d.cost) - float(d.quantity) * float(d.price) if d.cost else d.fee
            )
            rows.append(
                _fill(f"{d.date} 09:00", d.code, "buy", d.quantity, d.price, fee)
            )
        # 損益 = 賣出淨收 − 買進成本，反推賣出的手續費加交易稅
        charges = float(p.quantity) * float(p.price) - (float(p.pnl) + cost)
        rows.append(
            _fill(
                f"{p.date} 13:30",
                p.code,
                "sell",
                p.quantity,
                p.price,
                max(charges, 0.0),
            )
        )

    for p in api.list_positions(acct, **kw):
        time.sleep(_THROTTLE)
        details = list(api.list_position_detail(acct, p.id))
        total = sum(float(d.quantity) for d in details)
        if total <= 0:
            continue
        scale = (
            1000.0
            if abs(total * 1000 - float(p.quantity)) < abs(total - float(p.quantity))
            else 1.0
        )
        for d in details:
            qty = float(d.quantity) * scale
            px = _per_share(d.price, qty, float(getattr(p, "last_price", 0) or 0))
            rows.append(
                _fill(f"{d.date} 09:00", d.code, "buy", qty, px, getattr(d, "fee", 0))
            )

    if not has_detail:
        notes.append(
            "API 查不到已平倉部位的買進成交：期間內賣掉的股票視為起始日已持有，"
            "以起始日前收盤價計成本"
        )
    notes.append(
        "成交只有日期沒有時間；賣出的手續費與交易稅由已實現損益反推，合併記在 fee"
    )
    return BrokerHistory(_fills(rows), current_shares(account), limitations=notes)


def _sinopac(
    account: Any, start: pd.Timestamp, end: pd.Timestamp, **_: Any
) -> BrokerHistory:
    from ..brokers.sinopac import SJUnit

    return _shioaji_like(account, start, end, unit=SJUnit.Share)


# --------------------------------------------------------------- 富邦、元富
def _fubon(
    account: Any,
    start: pd.Timestamp,
    end: pd.Timestamp,
    fee_ratio: float | None = None,
    **_: Any,
) -> BrokerHistory:
    if fee_ratio is None:
        fee_ratio = account.get_market().default_fee_ratio()
    sdk, acct = account.sdk, account.target_account
    rows, notes = [], []
    for a, b in _chunks(start, end, 30):  # 每次最多 30 天
        res = sdk.stock.filled_history(acct, a.strftime("%Y%m%d"), b.strftime("%Y%m%d"))
        if not res.is_success:
            raise RuntimeError(f"富邦查詢歷史成交失敗：{res.message}")
        for f in res.data or []:
            if str(f.order_type).split(".")[-1] in ("Short", "SBL"):
                notes.append(f"{f.stock_no} 融券／借券交易不在覆盤範圍，已略過")
                continue
            action = "buy" if "Buy" in str(f.buy_sell) else "sell"
            rows.append(
                _fill(
                    f"{f.date} {f.filled_time}",
                    f.stock_no,
                    action,
                    f.filled_qty,
                    f.filled_price,
                )
            )
        time.sleep(_THROTTLE)
    fills = estimate_tw_charges(_fills(rows), fee_ratio)
    notes += [
        "這家券商的 API 沒有逐筆手續費與交易稅，依 fee_ratio 與法定稅率估算",
        "歷史成交需 fubon_neo 2.1.1 以上（舊版只查得到最近兩天）",
    ]
    return BrokerHistory(fills, current_shares(account), limitations=notes)


def _masterlink(
    account: Any, start: pd.Timestamp, end: pd.Timestamp, **_: Any
) -> BrokerHistory:
    sdk, acct = account.sdk, account.target_account
    rows, notes = [], []
    for a, b in _chunks(start, end, 30):
        res = sdk.accounting.account_statment(
            acct, a.strftime("%Y%m%d"), b.strftime("%Y%m%d")
        )
        for r in getattr(res, "filled_records", None) or []:
            if str(r.order_type) in ("2", "4"):
                notes.append(f"{r.symbol} 融券交易不在覆盤範圍，已略過")
                continue
            rows.append(
                _fill(
                    r.filled_date,
                    r.symbol,
                    str(r.buy_sell),
                    r.filled_qty,
                    r.filled_price,
                    r.fee,
                    r.tax,
                )
            )
        time.sleep(_THROTTLE)
    notes.append("成交只有日期沒有時間")
    return BrokerHistory(_fills(rows), current_shares(account), limitations=notes)


# --------------------------------------------------------------- 玉山（富果）
def _esun(
    account: Any, start: pd.Timestamp, end: pd.Timestamp, **_: Any
) -> BrokerHistory:
    rows, notes = [], []
    for a, b in _chunks(start, end, 180):  # 每次最多 180 天
        for summary in account.sdk.get_transactions_by_date(
            a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")
        ):
            for m in summary.get("mat_dats") or []:
                if m.get("trade") == "4":
                    notes.append(f"{m.get('stk_no')} 融券交易不在覆盤範圍，已略過")
                    continue
                tax = float(m.get("tax") or 0) + float(m.get("tax_g") or 0)
                hms = "".join(c for c in str(m.get("t_time") or "") if c.isdigit())[:6]
                hms = (
                    f"{hms[:2]}:{hms[2:4]}:{hms[4:6]}" if len(hms) == 6 else "00:00:00"
                )
                rows.append(
                    _fill(
                        f"{m['t_date']} {hms}",
                        m["stk_no"],
                        m["buy_sell"],
                        m["qty"],
                        m["price"],
                        m.get("fee"),
                        tax,
                    )
                )
    return BrokerHistory(_fills(rows), current_shares(account), limitations=notes)


# --------------------------------------------------------------- 嘉信
_SCHWAB_FLOWS = {
    "ACH_RECEIPT",
    "ACH_DISBURSEMENT",
    "CASH_RECEIPT",
    "CASH_DISBURSEMENT",
    "ELECTRONIC_FUND",
    "WIRE_IN",
    "WIRE_OUT",
    "JOURNAL",
}


def _security_legs(t: dict[str, Any]) -> list[dict[str, Any]]:
    """A Schwab transaction's non-cash ``transferItems``."""
    return [
        i
        for i in t.get("transferItems", [])
        if i.get("instrument", {}).get("assetType") not in (None, "CURRENCY")
    ]


def _schwab(
    account: Any, start: pd.Timestamp, end: pd.Timestamp, **_: Any
) -> BrokerHistory:
    client, account_hash = account.client, account.account_hash
    rows, events, notes = [], [], []
    for a, b in _chunks(start, end, 365):
        resp = client.get_transactions(
            account_hash,
            start_date=a.to_pydatetime(),
            end_date=(b + pd.Timedelta(hours=23, minutes=59)).to_pydatetime(),
        )
        resp.raise_for_status()
        for t in resp.json():
            when = (
                pd.Timestamp(t["time"]).tz_convert("America/New_York").tz_localize(None)
            )
            kind, net = t.get("type"), float(t.get("netAmount") or 0.0)
            if kind == "TRADE":
                legs = _security_legs(t)
                if len(legs) != 1 or legs[0]["instrument"]["assetType"] == "OPTION":
                    notes.append(
                        f"{t.get('description') or t.get('activityId')} 非單一股票成交，已略過 / Not a single-stock trade; skipped."
                    )
                    continue
                leg = legs[0]
                qty, price = abs(float(leg["amount"])), float(leg["price"])
                buy = float(leg["amount"]) > 0
                charges = (-net - qty * price) if buy else (qty * price - net)
                rows.append(
                    _fill(
                        when,
                        leg["instrument"]["symbol"],
                        "buy" if buy else "sell",
                        qty,
                        price,
                        max(charges, 0.0),
                    )
                )
            elif kind == "DIVIDEND_OR_INTEREST":
                symbols = [i["instrument"].get("symbol") for i in _security_legs(t)]
                events.append((when, net, "dividend", symbols[0] if symbols else None))
            elif kind in _SCHWAB_FLOWS:
                kind = "deposit" if net >= 0 else "withdrawal"
                events.append((when, net, kind, None))
            elif kind == "RECEIVE_AND_DELIVER":
                notes.append(
                    f"{when.date()} 有股票轉入轉出或公司行動（{t.get('description')}），"
                    "股數變動已含在倒推的起始庫存，未當成交易 / "
                    f"{when.date()}: share transfer or corporate action ({t.get('description')}); "
                    "share changes are included in reconstructed initial holdings, not treated as trades."
                )
            elif net:
                events.append((when, net, "other", None))
    balances = client.get_account(account_hash).json()["securitiesAccount"][
        "currentBalances"
    ]
    notes.append(
        "現金以目前 cashBalance 倒推，含未交割款；費用為淨額與成交金額的差 / Cash is reconstructed from current cashBalance, including unsettled funds; fees are the difference between net amount and trade value."
    )
    return BrokerHistory(
        _fills(rows),
        current_shares(account),
        cash=float(balances["cashBalance"]),
        cash_events=pd.DataFrame(
            events, columns=["time", "amount", "type", "stock_id"]
        ),
        dividends=True,
        limitations=notes,
    )


# --------------------------------------------------------------- 幣安
def _ms(t: pd.Timestamp) -> int:
    return int(t.tz_localize("UTC").timestamp() * 1000)


def _binance_fills(
    client: Any, asset: str, base: str, lo: int, hi: int, notes: list[str]
) -> list[dict[str, Any]]:
    rows, from_id = [], 0
    while True:
        batch = client.get_my_trades(symbol=asset + base, fromId=from_id, limit=1000)
        for t in (t for t in batch if lo <= t["time"] < hi):
            qty, price, fee = float(t["qty"]), float(t["price"]), float(t["commission"])
            if t["commissionAsset"] == asset:
                # 以該幣支付的手續費直接從幣數扣：買進入帳較少、賣出出帳較多，成交金額不變
                gross = qty * price
                qty += -fee if t["isBuyer"] else fee
                price, fee = gross / qty, 0.0
            elif t["commissionAsset"] != base:
                notes.append(
                    f"{asset}{base} 有以 {t['commissionAsset']} 支付的手續費，未計入 / Fees paid in {t['commissionAsset']} are excluded."
                )
                fee = 0.0
            rows.append(
                _fill(
                    pd.Timestamp(t["time"], unit="ms"),
                    asset,
                    "buy" if t["isBuyer"] else "sell",
                    qty,
                    price,
                    fee,
                )
            )
        if len(batch) < 1000 or batch[-1]["time"] >= hi:
            return rows
        from_id = batch[-1]["id"] + 1


def _binance_closes(client: Any, pair: str, lo: int, hi: int) -> pd.Series:
    closes: dict[pd.Timestamp, float] = {}
    while lo < hi:
        klines = client.get_klines(symbol=pair, interval="1d", startTime=lo, limit=1000)
        closes.update({pd.Timestamp(k[0], unit="ms"): float(k[4]) for k in klines})
        if len(klines) < 1000:
            break
        lo = klines[-1][0] + 86_400_000
    return pd.Series(closes, dtype=float)


def _binance_cash_events(
    client: Any, base: str, start: pd.Timestamp, end: pd.Timestamp
) -> list[tuple]:
    events: list[tuple] = []
    for a, b in _chunks(start, end, 90):
        kw = {"startTime": _ms(a), "endTime": _ms(b + pd.Timedelta(days=1)) - 1}
        events += [
            (pd.Timestamp(d["insertTime"], unit="ms"), float(d["amount"]), "deposit")
            for d in client.get_deposit_history(coin=base, **kw)
            if d.get("status") == 1
        ]
        events += [
            (
                pd.Timestamp(w["applyTime"]),
                -float(w["amount"]) - float(w.get("transactionFee") or 0),
                "withdrawal",
            )
            for w in client.get_withdraw_history(coin=base, **kw)
            if w.get("status") == 6
        ]
    for a, b in _chunks(start, end, 180):
        div = client.get_asset_dividend_history(
            asset=base,
            startTime=_ms(a),
            limit=500,
            endTime=_ms(b + pd.Timedelta(days=1)) - 1,
        )
        events += [
            (pd.Timestamp(r["divTime"], unit="ms"), float(r["amount"]), "dividend")
            for r in div.get("rows", [])
        ]
    return events


def _binance(
    account: Any, start: pd.Timestamp, end: pd.Timestamp, symbols: Any = (), **_: Any
) -> BrokerHistory:
    client, base = account.simple_client.client, account.base_currency
    balances = {
        b["asset"]: float(b["free"]) + float(b["locked"])
        for b in client.get_account()["balances"]
    }
    holdings = {a: q for a, q in balances.items() if q > 0 and a != base}
    lo, hi = _ms(start), _ms(end + pd.Timedelta(days=1))
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    closes = {}
    for asset in sorted(set(holdings) | set(symbols)):
        rows += _binance_fills(client, asset, base, lo, hi, notes)
        closes[asset] = _binance_closes(client, asset + base, lo - 3 * 86_400_000, hi)
    events = _binance_cash_events(client, base, start, end)
    notes += [
        f"只查目前持有幣別與 symbols 參數列出的幣別（{base} 計價交易對） / Only current holdings and symbols are queried ({base}-quoted pairs).",
        f"只計 {base} 的入出金與配發；其他幣別轉入轉出已含在倒推的起始庫存 / Only {base} deposits, withdrawals and distributions are counted; other asset transfers are included in reconstructed initial holdings.",
        "估值用幣安日 K 收盤價（UTC 日界） / Valuation uses Binance daily closing prices (UTC day boundaries).",
    ]
    return BrokerHistory(
        _fills(rows),
        holdings,
        cash=balances.get(base, 0.0),
        cash_events=pd.DataFrame(events, columns=["time", "amount", "type"]),
        dividends=True,
        limitations=notes,
        # 只有現金時也要有每日估值的日期
        prices=pd.DataFrame(
            closes, index=pd.date_range(start, end) if not closes else None
        ),
    )


_FETCHERS: dict[str, Callable[..., BrokerHistory]] = {
    "SinopacAccount": _sinopac,
    "PocketAccount": _shioaji_like,
    "FubonAccount": _fubon,
    "MasterlinkAccount": _masterlink,
    "FugleAccount": _esun,
    "SchwabAccount": _schwab,
    "BinanceAccount": _binance,
}


def fetch_history(
    account: Any, start: Any, end: Any = None, **kwargs: Any
) -> BrokerHistory:
    """依帳戶類別呼叫對應券商的歷史查詢。

    Args:
        account: finlab-online 的券商帳戶（已登入）。
        start: 起始日。
        end: 結束日，預設今天。
        **kwargs: 傳給個別券商，例如 ``fee_ratio``（API 沒有費稅時估算用，預設為帳戶市場的
            ``default_fee_ratio()``）。
    """
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end or datetime.date.today()).normalize()
    for cls in type(account).__mro__:
        if cls.__name__ in _FETCHERS:
            return _FETCHERS[cls.__name__](account, start, end, **kwargs)
    raise NotImplementedError(
        f"{type(account).__name__} 尚未支援實盤覆盤；請改用 TradeReview 直接傳入成交紀錄 / Live trade review is not supported for this account type; pass fills directly to TradeReview."
    )
