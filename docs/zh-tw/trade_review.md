# 實盤覆盤：從券商帳戶抓成交

用 `finlab-online` 連上券商帳戶，`TradeReview.from_account()` 直接從券商抓成交、重建每天的持股與淨值。`TradeReview` 本身在 finlab 套件的 `finlab.portfolio`；用匯出的成交檔覆盤、報酬怎麼算、在 Studio 看報表與保存明細，見 FinLab 文件的[實盤覆盤](https://studio.finlab.finance/docs/workflows/trade_review)。

券商帳戶的設定方式見[下單：單一策略](order_api.md)。

## 從券商帳戶覆盤

### 連上券商帳戶

**台股**

以永豐為例，其他台股券商的支援程度見下方的表：

```python
from finlab.online.sinopac_account import SinopacAccount

acc = SinopacAccount()
```
**美股**

以嘉信為例：

```python
from finlab.online.schwab_account import SchwabAccount

acc = SchwabAccount()
```

### 建立覆盤

```python
from finlab.portfolio import TradeReview

review = TradeReview.from_account(acc, start="2026-01-01")
```

`from_account` 會依序做四件事：

1. 依券商 API 抓 `start` 到今天的成交（各券商的差異見下方的表）。
2. 由券商**目前庫存**倒推起始日的庫存（扣回期間成交、除回配股與分割），最後再把重建出的期末庫存和券商庫存對帳，不一致的代號會寫進 `review.limitations`。
3. 套用除權息。台股自動套用 FinLab 公告的除權息：現金股利在除息交易日入帳，配股與 ETF 分割在除權交易日（分割為恢復買賣日）調整股數。嘉信與幣安用券商紀錄裡的股利。
4. 以未還原收盤價每日估值。

### 先看資料限制

```python
review.limitations  # 這次覆盤的資料限制，務必看過
```

對帳不一致的代號、被略過的融券與借券成交，都會列在這裡。先看過，再相信後面的數字。

### 看績效與明細

```python
review.summary()  # 起訖淨值、外部淨投入、股利、費稅、損益、時間加權報酬
review.daily  # 每日現金、持股市值、淨值、流入流出、報酬率、累計損益
review.holdings  # 每日收盤持股股數
review.trades  # FIFO 配對的每段實際交易（含股利），未出清的部位 exit_date 為空
review.report.display()  # FinLab 報表：淨值曲線、績效指標、MAE/MFE、交易明細
```

### 和策略目標比對

`compare` 用「目標日收盤時」的實際部位和目標比，不會用到之後的成交。目標可以是股數，也可以是權重：

**台股**

```python
import pandas as pd

target = pd.DataFrame({"2330": [2000], "2454": [1000]}, index=["2026-03-02"])
review.compare(target)  # date, stock_id, target, actual, diff（股數）

weights = pd.DataFrame({"2330": [0.6], "2454": [0.4]}, index=["2026-03-02"])
review.compare(weights, kind="weight")  # 也可以比權重
```
**美股**

```python
import pandas as pd

target = pd.DataFrame({"AAPL": [20], "MSFT": [10]}, index=["2026-03-02"])
review.compare(target)  # date, stock_id, target, actual, diff（股數）

weights = pd.DataFrame({"AAPL": [0.6], "MSFT": [0.4]}, index=["2026-03-02"])
review.compare(weights, kind="weight")  # 也可以比權重
```

## 各券商支援程度

| 券商 | 成交來源 | 手續費／交易稅 | 已平倉部位 | 股利 | 入出金 | 預設口徑 |
|---|---|---|---|---|---|---|
| 永豐 | 已實現損益＋明細、未實現部位明細 | 買進取自明細；賣出由已實現損益反推（合併記在 fee） | 可還原買進腿 | FinLab 自動 | 無 | 持股模式 |
| 口袋 | 已實現損益、未實現部位明細 | 無 | SDK 有明細查詢時同永豐；沒有時期間內賣出的股票視為起始日已持有 | FinLab 自動 | 無 | 持股模式 |
| 富邦 | `filled_history`（每次 30 天，需 fubon_neo 2.1.1 以上） | API 無逐筆費稅，依 `fee_ratio` 與法定稅率估算 | 可 | FinLab 自動 | 無 | 持股模式 |
| 台新（原元富） | 對帳單 `account_statment` | 逐筆實際值 | 可 | FinLab 自動 | 無 | 持股模式 |
| 玉山（富果） | `get_transactions_by_date`（每次 180 天） | 逐筆實際值 | 可 | FinLab 自動 | 無 | 持股模式 |
| 嘉信 | 交易紀錄 `get_transactions` | 淨額與成交金額的差 | 可 | 券商紀錄 | 券商紀錄 | 帳戶模式 |
| 幣安 | `myTrades`（逐幣別） | 以報價幣或該幣支付的手續費；以 BNB 支付的未計入 | 只查目前持有與 `symbols=` 指定的幣別 | 報價幣配發 | 報價幣入出金 | 帳戶模式 |

所有券商共同的限制：

- 只覆盤現股與融資的**多單**；融券、借券成交會略過並列在 `limitations`。融資利息不計。
- 台股成交大多只有日期；同一天先處理買進再處理賣出，每日收盤估值不受影響。
- 減資、面額變更沒有完整的每股退還現金與換股比例資料，不自動處理；遇到時把事件放進 `corporate_actions`（欄位 `stock_id, date, cash, ratio`）。配股以「元/股 ÷ 面額」換算，零股以無條件捨去計算。
- 券商 API 查不到時間範圍外的資料時，覆盤只能從查得到的那天開始。
