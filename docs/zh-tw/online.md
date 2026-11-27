# finlab.online

`finlab.online` 把回測算出的目標持股，變成券商帳戶裡的實際委託：先用 `Position` 算出每檔要持有幾張，再由 `OrderExecutor` 和帳戶現有持股比對，送出補足差額的委託。永豐、玉山、富邦、台新、口袋等台股券商，以及美股的嘉信、加密貨幣的幣安都能接。

> [!CAUTION]
> **重要風險警告**
>
> **實盤交易涉及真實金錢，錯誤可能導致財務損失！**
>
> **必須遵守的安全原則**：
>
> 1. **務必先用模擬帳戶測試至少 1 個月**
> 2. **初期資金不超過總資金的 10-20%**
> 3. **每日監控持倉與訂單狀態**
> 4. **設定停損機制，避免單次巨大虧損**
> 5. **在開發/測試環境與生產環境使用不同帳戶**
> 6. **絕對不要在未測試的策略上使用全部資金**
> 7. **不要忽略錯誤訊息或異常狀態**

## 選哪個函式

| 你想做的事 | 用這個 |
|---|---|
| 把回測報告換成現在要持有的張數 | `Position.from_report()` |
| 用權重和資金算出張數 | `Position.from_weight()` |
| 直接寫出要持有的股票與張數 | `Position()` |
| 連上券商帳戶 | 各券商的帳戶類別，例如 `SinopacAccount()` |
| 預覽委託，再讓帳戶持股對齊目標 | `OrderExecutor(...).create_orders()` |
| 讓沒成交的限價單追價 | `executor.update_order_price()` |
| 取消所有未成交委託 | `executor.cancel_orders()` |
| 查詢委託單狀態 | `account.get_orders()`，回傳 `Order` |
| 多個策略合併後下單 | `PortfolioSyncManager`，見 [finlab.portfolio](https://studio.finlab.finance/docs/reference/portfolio) |

## 從回測到實盤

```mermaid
graph LR
    A[策略回測] --> B[樣本外測試]
    B --> C[上傳至雲端]
    C --> D[模擬帳戶測試]
    D --> E{測試通過?}
    E -->|是| F[小資金實盤]
    E -->|否| A
    F --> G[逐步增加資金]
```

**建議時程**：

1. 策略回測（1-2 週）：確認邏輯正確
2. 樣本外測試（2-4 週）：使用未見過的資料
3. 模擬帳戶（4-8 週）：真實市場條件，但不用真錢
4. 小資金實盤（8-12 週）：10-20% 資金測試
5. 逐步擴大（視情況）：確認穩定後才增加資金

## 第一次自動下單

執行策略、算出張數、連上券商、預覽委託，四步就能把回測結果送到帳戶。`view_only=True` 只印出委託，確認無誤再拿掉。

```python
from finlab import data
from finlab.backtest import sim
from finlab.online.order_executor import OrderExecutor, Position
from finlab.online.sinopac_account import SinopacAccount

# 1. 執行策略
close = data.get('price:收盤價')
position = (close / close.shift(120)).is_largest(20)
report = sim(position, resample='M', upload=False)

# 2. 把最新的目標權重換算成總資金 100 萬的張數
target = Position.from_report(report, fund=1_000_000)

# 3. 連線永豐證券（先設定 SHIOAJI_API_KEY 等環境變數，見實盤下單教學）
account = SinopacAccount()

# 4. 先預覽委託，確認後再下單
executor = OrderExecutor(target, account=account)
executor.create_orders(view_only=True)  # 只印出委託，不會下單
# executor.create_orders()  # 實際下單
```

## 連上券商帳戶

每家券商有自己的帳戶類別，都實作同一個 `Account` 介面，所以 `OrderExecutor` 和 `PortfolioSyncManager` 換券商也能照用；你也可以繼承 `Account` 接上自己的券商。

| 券商 | 市場 | 帳戶類別 |
|---|---|---|
| 永豐（Shioaji） | 台股 | `finlab.online.sinopac_account.SinopacAccount` |
| 玉山 | 台股 | `finlab.online.esun_account.EsunAccount`（即 `FugleAccount`） |
| 富邦 | 台股 | `finlab.online.fubon_account.FubonAccount` |
| 台新（原元富） | 台股 | `finlab.online.taishin_account.TaishinAccount`（即 `MasterlinkAccount`） |
| 口袋 | 台股 | `finlab.online.pocket_account.PocketAccount` |
| 嘉信（Charles Schwab） | 美股 | `finlab.online.schwab_account.SchwabAccount` |
| 幣安（Binance） | 加密貨幣 | `finlab.online.binance_account.BinanceAccount` |

數量的單位跟著帳戶的市場走：台股帳戶是**張**（1 張 = 1,000 股，小數部分是零股），美股帳戶是**股**。

### 用環境變數保存帳密

帳密不要寫進程式碼。在程式以外（shell 設定檔、密鑰管理服務、CI secrets）設定好環境變數，帳戶類別會自己讀取：

```python
from finlab.online.sinopac_account import SinopacAccount

# 讀取 SHIOAJI_API_KEY、SHIOAJI_SECRET_KEY、SHIOAJI_CERT_PERSON_ID、
# SHIOAJI_CERT_PATH、SHIOAJI_CERT_PASSWORD 後登入
account = SinopacAccount()
```

也可以改成從自己的設定讀出帳密後明確傳入，取代上面的寫法：

```python
import os

from finlab.online.sinopac_account import SinopacAccount

account = SinopacAccount(
    api_key=os.environ['SHIOAJI_API_KEY'],
    secret_key=os.environ['SHIOAJI_SECRET_KEY'],
    certificate_person_id=os.environ['SHIOAJI_CERT_PERSON_ID'],
    certificate_path=os.environ['SHIOAJI_CERT_PATH'],
    certificate_password=os.environ['SHIOAJI_CERT_PASSWORD'],
)
```

各券商要設定哪些變數，見[實盤下單教學](order_api.md)。

### 安裝口袋證券

`PocketAccount` 使用口袋官方的 [`pocketx`](https://felixchih.github.io/PocketxDocs/zh/prepare/)。請在獨立的 **Python 3.12** 環境安裝：

```bash
python -m pip install finlab pocketx==0.0.4
```

```python
from finlab.online import PocketAccount
```

正式下單的憑證簽章**僅支援 Windows**。先依[官方事前準備](https://felixchih.github.io/PocketxDocs/zh/prepare/)完成 API 申請與憑證申請，再設定 `POCKET_API_KEY`、`POCKET_SECRET_KEY`（登入密碼）、`POCKET_CERT_PATH`、`POCKET_CERT_PASSWORD`、`POCKET_CERT_PERSON_ID`。之後呼叫 `PocketAccount()` 會登入並啟用憑證；單純匯入類別不會登入。

<details><summary>為什麼要用 Python 3.12？</summary>

`pocketx` 0.0.4 的預編譯 wheel 僅支援 Python 3.9；Python 3.12 會從原始碼編譯，需先安裝 C 編譯器（Windows 可使用 Visual Studio Build Tools 的 C++ 建置工具）。SDK 使用已於 Python 3.13 移除的 `audioop`，請勿使用 Python 3.13 以上。PyPI 的 `pocket` 是另一個服務的套件，請勿安裝它來連接口袋證券。

</details>

### Account

每個帳戶類別都有下面這些查詢方法；`get_price()` 與下單、改單、刪單見後面幾節。

```python
account.get_position()       # 帳戶目前的持股（Position）
account.get_total_balance()  # 帳戶淨值
```

| 方法 | 回傳 | 說明 |
|---|---|---|
| `get_stocks(stock_ids)` | `dict[str, Stock]` | 即時報價，例如 `get_stocks(['1101', '2330'])`。每檔一個 `Stock`，含開高低收（`open`、`high`、`low`、`close`）與最佳一檔買賣價量（`bid_price`、`bid_volume`、`ask_price`、`ask_volume`）。 |
| `get_position()` | `Position` | 帳戶目前的持股。 |
| `get_total_balance()` | `Number` | 帳戶淨值。 |
| `get_cash()` | `Number` | 現金餘額。 |
| `get_settlement()` | `Number` | 尚未交割的金額。 |
| `support_best_price_limit()` | `bool` | 能不能用 `best_price_limit` 掛漲跌停價；預設 `True`，幣安為 `False`，這時設定 `best_price_limit` 會報錯。 |
| `get_market()` | `Market` | 帳戶所屬的市場：台股券商是 `TWMarket`；券商類別沒有指定時，用 FinLab 的預設市場。 |

### account.get_price()

取得每檔股票的最後成交價；還沒有成交時，改用買賣報價的中間值。

```python
price = account.get_price(['2330', '2317'])
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `stock_ids` | `list[str]` | 必填 | 股票代號清單。 |

### account.create_order()

送出一筆新委託，回傳券商的委託單編號。`OrderExecutor` 會代為呼叫，自己逐筆下單時才需要直接用。

```python
from finlab.online.enums import Action

price = account.get_price(['2330'])['2330']
order_id = account.create_order(Action.BUY, '2330', 1, price=price)  # 以最後成交價買 1 張
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `action` | `Action` | 必填 | `Action.BUY` 或 `Action.SELL`。 |
| `stock_id` | `str` | 必填 | 股票代號，例如 `'2330'`。 |
| `quantity` | `Number` | 必填 | 委託數量：台股整股單是張，`odd_lot=True` 的零股單是股；美股是股。 |
| `price` | `Number` | `None` | 限價。 |
| `odd_lot` | `bool` | `False` | 台股：下零股單。 |
| `market_order` | `bool` | `False` | 盡量立即成交：台股買單掛漲停價、賣單掛跌停價（嘉信改送市價單）。 |
| `best_price_limit` | `bool` | `None` | 掛最有利的漲跌停價（芭樂價）等待成交：買單掛跌停價、賣單掛漲停價。 |
| `order_cond` | `OrderCondition` | `OrderCondition.CASH` | `CASH`（現股）、`MARGIN_TRADING`（融資）、`SHORT_SELLING`（融券）、`DAY_TRADING_LONG`（當沖先買）或 `DAY_TRADING_SHORT`（當沖先賣）。 |

### account.update_order()

修改未成交委託的限價或數量。回傳 `None`，沒有報錯就代表修改成功。

```python
account.update_order(order_id, price=new_price)
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `order_id` | `str` | 必填 | 券商的委託單編號。 |
| `price` | `Number` | `None` | 新的限價。 |
| `quantity` | `Number` | `None` | 新的未成交數量。 |

### account.cancel_order()

取消一筆未成交的委託。

```python
# order_id 來自 create_order() 的回傳值，或 account.get_orders() 的 key
account.cancel_order(order_id)
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `order_id` | `str` | 必填 | 券商的委託單編號。 |

## 設定目標部位

`Position` 是要讓帳戶持有的股票與數量。可以直接寫出張數，也可以從回測報告或權重換算，最常用的是 `Position.from_report()`。

### Position()

直接寫出要持有的股票與張數。每筆部位含 `symbol`（股票代號，也可以用 `stock_id`）、`quantity`（數量）和 `order_condition`（`OrderCondition`）。

```python
from finlab.online.order_executor import Position

# 持有 1 張 2330，以及 1 張又 100 股 1101
manual = Position({'2330': 1, '1101': 1.1})
double = manual * 2  # 部位可以相加、相減，也可以乘除
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `stocks` | `dict[str, Number]` | 必填 | 股票代號對應張數，例如 `{'1101': 1}` 是持有一張 1101 台泥；負數代表做空。 |
| `weights` | `dict[str, float]` 或 `pd.Series` | `None` | 每檔的目標權重，會記在部位裡。 |
| `margin_trading` | `bool` | `False` | 做多部位使用融資。不能和 `day_trading_long` 同時設定。 |
| `short_selling` | `bool` | `False` | 做空部位使用融券。不能和 `day_trading_short` 同時設定。 |
| `day_trading_long` | `bool` | `False` | 做多部位為當沖先買。 |
| `day_trading_short` | `bool` | `False` | 做空部位為當沖先賣。 |

### Position.from_report()

從回測報告算出「現在」該持有的部位。

```python
from finlab import backtest, data
from finlab.online.order_executor import Position

close = data.get('price:收盤價')

report1 = backtest.sim(
    (close / close.shift(120)).is_largest(10), resample='M', upload=False
)  # 半年動能
report2 = backtest.sim(
    (close / close.shift(20)).is_smallest(10), resample='M', upload=False
)  # 一個月反轉

# 策略操作金額各一百萬，兩個部位可以相加
position1 = Position.from_report(report1, 1_000_000)
position2 = Position.from_report(report2, 1_000_000)
total_position = position1 + position2
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `report` | `Report` | 必填 | `backtest.sim()` 的回測報告（或雲端報告）。 |
| `fund` | `int` | 必填 | 要投入的資金，單位是該市場的貨幣。 |
| `**kwargs` | | | 傳給 `Position.from_weight()`，例如 `odd_lot`、`price`、`margin_trading`、`leverage`。 |

下次換股前用 `report.weights`，換股時間一到（與 `report.is_rebalance_due()` 同一個規則）就改用 `report.next_weights`；有停損停利待出場的股票權重為 0。價格預設用該市場最新的參考價，一張幾股由 `report.market` 決定（台股 1,000 股、美股 1 股）。一份報告裡包含多個策略時，請改用 `finlab.portfolio.Portfolio`。

### Position.from_weight()

把權重和資金換算成張數。和 `backtest.sim()` 一樣，權重絕對值總和大於 1 時會等比例縮到 1。

```python
from finlab.online.order_executor import Position

# 100 萬資金，1101 和 2330 各一半
Position.from_weight({'1101': 0.5, '2330': 0.5}, fund=1_000_000)
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `weights` | `dict[str, float]` 或 `pd.Series` | 必填 | 股票代號對應權重。 |
| `fund` | `int` | 必填 | 要投入的資金。 |
| `price` | `pd.Series` 或 `dict[str, float]` | `None` | 每檔的價格；預設用目前市場最新的參考價。 |
| `odd_lot` | `bool` | `False` | 是否買零股。`False` 時只買整張，資金不夠買一張的股票會是 0 股，並發出 `ZeroShareAllocationWarning`。搭配 `margin_trading` 或 `short_selling` 時只有整張用信用交易：多方不足一張的部分用現股買，空方不足一張的部分不放空。 |
| `board_lot_size` | `int` | `None` | 一張幾股；預設用目前市場的設定（台股 1,000、美股 1）。 |
| `allocation` | callable | `greedy_allocation` | 資產配置演算法；預設的 `finlab.online.utils.greedy_allocation` 會盡量把資金用完。 |
| `precision` | `int` | `None` | 只在 `board_lot_size` 為 1 且 `odd_lot=True` 時有效：數量算到小數第幾位。其他情況不看這個參數：`odd_lot=True` 時算到 1 股，否則只買整張。 |
| `leverage` | `float` | `1.0` | 目標槓桿倍數。大於 1.0 時總曝險為 `fund * leverage`，從波動度最低的持股開始配融資，讓現股加上融資自備款不超過 `fund`；不能和 `margin_trading`、`day_trading_long` 同時使用。 |
| `price_history` | `pd.DataFrame` | `None` | 歷史價格，`leverage > 1.0` 時必填（`from_report()` 會自動帶入）。 |
| `margin_ratio` | `float` | `0.6` | 融資成數，只在 `leverage > 1.0` 時使用；上市股票 0.6，上櫃股票請用 0.5。 |
| `**kwargs` | | | `margin_trading`、`short_selling`、`day_trading_long`、`day_trading_short`（見 `Position()`）。 |

### Position.from_list() 與 position.to_list()

用 dict 清單建構部位，或把部位轉回 dict 清單。下單前過濾股票就是用這組，見[過濾處置股](#過濾處置股)。

```python
from finlab.online.enums import OrderCondition
from finlab.online.order_executor import Position

target = Position.from_list([
    {'stock_id': '1101', 'quantity': 1.1, 'order_condition': OrderCondition.CASH},
    {'stock_id': '2330', 'quantity': 1, 'order_condition': OrderCondition.MARGIN_TRADING},
])
entries = target.to_list()
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `position` | `list[dict]` | 必填 | 每個 dict 有 `stock_id`（或 `symbol`）、`quantity`（數量）和 `order_condition`（`OrderCondition`，種類同 `account.create_order()` 的 `order_cond`）。 |

### position.to_json() 與 Position.from_json()

把部位存成 JSON 檔，或從 JSON 檔讀回來。

```python
target.to_json('target.json')
target = Position.from_json('target.json')
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `path` | `str` | 必填 | JSON 檔案路徑。 |

### Position.from_entries() 與 position.to_entries()

和 `finlab.schemas.PositionEntry` 物件互轉。

```python
entries = target.to_entries()
same = Position.from_entries(entries)
```

## 讓帳戶持股對齊目標

### OrderExecutor()

比對目標部位和帳戶目前的持股，算出差額並送出委託。

```python
from finlab.online.order_executor import OrderExecutor

executor = OrderExecutor(target, account=account)
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `target_position` | `Position` 或 `dict[str, Number]` | 必填 | 要持有的部位；傳 dict 時會用 `Position()` 轉換。 |
| `account` | `Account` | 必填 | 已登入的券商帳戶。 |

### executor.create_orders()

先取消帳戶裡未成交的委託，再送出讓帳戶持股變成 `target_position` 的委託，預設以最後一筆成交價掛限價單。回傳送出（或預覽時將送出）的委託清單。

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `market_order` | `bool` | `False` | 盡量立即成交（見 `account.create_order()`）。 |
| `best_price_limit` | `bool` | `False` | 掛最有利的漲跌停價（芭樂價）等待成交；帳戶不支援時會報錯（見 `support_best_price_limit()`）。 |
| `view_only` | `bool` | `False` | 只印出委託，不下單，也不取消現有委託。 |
| `extra_bid_pct` | `float` | `0` | 限價偏離最後成交價的比例，範圍 -0.1 到 0.1：`0.01` 是買單高 1%、賣單低 1% 掛，比較容易成交；`-0.01` 方向相反，等較好的價格。 |
| `progress` | `float` | `1` | 這次送出剩餘差距的多少比例（0 到 1）。 |
| `progress_precision` | `int` | `0` | `progress` 小於 1 時，數量算到小數第幾位（0 是整張）。 |
| `buy_only` / `sell_only` | `bool` | `False` | 只下買單或只下賣單。 |

`market_order`、`best_price_limit`、`extra_bid_pct` 三者只能擇一設定。

#### 調整掛單價格

```python
# 預設以最後成交價掛限價單，extra_bid_pct 可微調價格
# 負值 = 比市價低（較保守），正值 = 比市價高（較積極）
executor.create_orders(
    extra_bid_pct=-0.01  # 比當前價格低 1% 掛單，避免滑價
)

# 類市價單：買單掛漲停價、賣單掛跌停價，盡量即刻成交
executor.create_orders(market_order=True)
```

#### 大額委託分批送出

```python
import time

# 將大額訂單分 3 次執行
# progress 是「剩餘差距」的比例，不是原始目標的比例
# 每輪成交後剩餘量會減少，所以比例要遞增
for i, p in enumerate([1 / 3, 1 / 2, 1]):
    if i > 0:
        time.sleep(60)  # 每批間隔 1 分鐘
    executor.create_orders(
        progress=p  # 依序執行 1/3、1/2、1 的剩餘量
    )
```

#### 分開開發與正式環境

```python
import os

# 開發環境：跑完整流程，但只印出委託
executor = OrderExecutor(target, account=account)
if os.environ.get('ENV') == 'development':
    executor.create_orders(view_only=True)
else:
    executor.create_orders()
```

### executor.update_order_price()

把還沒成交的限價單改到最後成交價（讓沒成交的限價單追價），可以再用 `extra_bid_pct` 調整。

```python
executor.update_order_price(extra_bid_pct=0.01)
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `extra_bid_pct` | `float` | `0` | 新限價偏離最後成交價的比例，範圍 -0.1 到 0.1，方向同 `create_orders()`。 |
| `buy_only` / `sell_only` | `bool` | `False` | 只改買單或只改賣單。 |

### executor.cancel_orders()

取消所有未成交（含部分成交）的委託，或只取消買單、賣單。

```python
executor.cancel_orders(buy_only=True)
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `buy_only` / `sell_only` | `bool` | `False` | 只取消買單或只取消賣單。 |

### executor.generate_orders()

只算出要送的委託（目標部位減去目前持股），不會下單。數量為正是買、為負是賣。

```python
orders = executor.generate_orders()
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `progress` | `float` | `1` | 剩餘差距要算進來的比例。 |
| `progress_precision` | `int` | `0` | `progress` 小於 1 時，數量算到小數第幾位。 |
| `as_entries` | `bool` | `None` | `True` 時回傳 `finlab.schemas.OrderEntry` 物件；預設回傳 dict 清單（finlab 開啟 typed strict 模式時改回傳 `OrderEntry`）。 |
| `quantity_type` | `str` | `'decimal'` | `as_entries` 時數量的型別：`'decimal'`、`'float'` 或 `'string'`。 |

### executor.execute_orders()

送出指定的委託清單，通常來自 `generate_orders()`。

```python
orders = executor.generate_orders()
executor.execute_orders(orders, view_only=True)
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `orders` | `list[dict]` | 必填 | 要送出的委託。 |
| `market_order` / `best_price_limit` / `view_only` | `bool` | `False` | 同 `create_orders()`。 |
| `extra_bid_pct` | `float` | `0` | 同 `create_orders()`。 |
| `cancel_orders` | `bool` | `True` | 送出前先取消未成交的委託（`view_only=True` 時不取消）。 |
| `buy_only` / `sell_only` | `bool` | `False` | 只下買單或只下賣單。 |

### executor.get_order_info()

逐檔列出價格、目前數量、目標數量與要下的數量，依委託金額由大到小排序。

```python
executor.get_order_info()
```

### executor.show_alerting_stocks()

僅限台股：列出待下單股票中屬於處置股或信用交易警示股的標的，這些股票需要事先向券商圈存現金或股票。

```python
executor.show_alerting_stocks()
```

## 下單前要檢查的事

### 過濾處置股

直接下單可能買到處置股。`OrderExecutor` 的目標不是回測用的布林 DataFrame，要先用 `to_list()` 取出部位、過濾後再用 `Position.from_list()` 組回來：

```python
from finlab import data
from finlab.online.order_executor import OrderExecutor, Position

# 使用處置股 filter 過濾目標部位
disposal_stock_filter = data.get('etl:disposal_stock_filter')
latest_filter = disposal_stock_filter.iloc[-1].fillna(False)

filtered_target = Position.from_list(
    [entry for entry in target.to_list() if latest_filter.get(entry['stock_id'], False)]
)

OrderExecutor(filtered_target, account=account).create_orders()
```

需要事先圈存的處置股與警示股，可以用 [`executor.show_alerting_stocks()`](#executorshow_alerting_stocks) 列出。

### 確認資金足夠

下單前比較目標部位市值與 `account.get_total_balance()`，不足時調低 `Position.from_report()` 的 `fund` 或追加資金。檢查函式 `safe_order_check()` 見實盤下單教學的[錯誤 2：下單前安全檢查失敗](order_api.md#錯誤-2下單前安全檢查失敗)。

### 漲跌停鎖死可能整天無法成交

台股有漲跌停限制，`create_orders()` 會用券商回報的漲跌停價夾住限價；股票鎖漲停時的買單、鎖跌停時的賣單可能整天無法成交。隔日的漲跌停價可查參考價表 `reference_price`（每檔股票一列）：

```python
from finlab import data

ref = data.get('reference_price').set_index('stock_id')
print(ref.loc[['2330', '2317'], ['收盤價', '漲停價', '跌停價']])
```

## 查詢委託狀態

### account.get_orders()

回傳目前所有委託單，key 是券商的委託單編號，value 是 `Order`：

```python
for order_id, order in account.get_orders().items():
    print(order_id, order.stock_id, order.status, order.filled_quantity)
```

每個 `Order`（dataclass）有這些欄位：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `order_id` | `str` | 委託單編號，與券商 API 提供的一致。 |
| `stock_id` | `str` | 股票代號，例如 `'2330'`（也可以用 `symbol` 取得）。 |
| `action` | `Action` | `Action.BUY` 或 `Action.SELL`。 |
| `price` | `Number` | 限價。 |
| `quantity` | `Number` | 委託總數量，單位跟著帳戶的市場（台股是張，可有小數）。 |
| `filled_quantity` | `Number` | 已成交數量。 |
| `status` | `OrderStatus` | `NEW`、`PARTIALLY_FILLED`、`FILLED` 或 `CANCEL`。 |
| `order_condition` | `OrderCondition` | 現股、融資、融券或當沖。 |
| `time` | `datetime.datetime` | 委託時間。 |
| `org_order` | `Any` | 券商原本的委託物件。 |

## 常見問題

<details><summary>如何確保下單安全？</summary>

先用 `view_only=True` 預覽委託，並做完[下單前要檢查的事](#下單前要檢查的事)。同時檢查持倉數量、單股權重與可用資金的範例函式 `safe_order_check()`，見實盤下單教學的[錯誤 2：下單前安全檢查失敗](order_api.md#錯誤-2下單前安全檢查失敗)。

</details>

<details><summary>實盤與回測有落差怎麼辦？</summary>

常見原因：

1. **滑價**：實盤成交價與預期不符
   - 解決：使用限價單，或調整 `extra_bid_pct`
2. **成交量不足**：無法全部成交
   - 解決：使用 LiquidityAnalysis 事先檢測（見 [finlab.analysis](https://studio.finlab.finance/docs/reference/analysis)）
3. **交易時間差異**：回測假設即時成交
   - 解決：設定合理的下單時間（如收盤前 30 分鐘）

</details>

<details><summary>如何設定自動下單排程？</summary>

用 `schedule` 套件每天重跑策略、檢查後下單的範例，見實盤下單教學的[設定每日下單排程](order_api.md#設定每日下單排程)。

不想自己維持一個常駐程式，也可以用 [FinLab CLI](https://studio.finlab.finance/docs/cli) 每天重跑策略。

</details>

<details><summary>如何處理下單失敗？</summary>

```python
import time

try:
    executor.create_orders()
    print("✅ 下單成功")
except Exception as e:
    print(f"❌ 下單失敗：{e}")

    # 記錄錯誤
    with open('order_errors.log', 'a') as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {e}\n")

    # 根據錯誤類型決定是否重試
    if "network" in str(e).lower():
        time.sleep(30)  # 網路問題，30 秒後重試
        executor.create_orders()
```

</details>

## 下一步

投入真實資金前，先逐項確認[上線前的檢查清單](order_api.md#上線前的檢查清單)。

- [下單：單一策略](order_api.md) 各券商的帳密設定與基礎下單流程。
- [下單：多策略](order_api2.md) 用 PortfolioSyncManager 合併多個策略的部位後下單。
- [風險管理完整指南](https://studio.finlab.finance/docs/workflows/risk_management) 實盤的部位、停損與資金控管。
- [完整策略開發流程](https://studio.finlab.finance/docs/workflows/complete_strategy_workflow) 從研究、回測到實盤的步驟。

原始碼在 [core/](../../core/) 與 [brokers/](../../brokers/)。
