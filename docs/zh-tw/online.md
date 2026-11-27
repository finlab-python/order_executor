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

帳密不要寫進程式碼。在程式以外設定好環境變數（shell 設定檔、密鑰管理服務、CI secrets），帳戶類別會自己讀取；也可以從你的設定明確傳入：

```python
import os

from finlab.online.sinopac_account import SinopacAccount

# 在程式碼以外設定 SHIOAJI_API_KEY、SHIOAJI_SECRET_KEY、SHIOAJI_CERT_PERSON_ID、
# SHIOAJI_CERT_PATH、SHIOAJI_CERT_PASSWORD（shell 設定檔、密鑰管理服務、CI secrets）
account = SinopacAccount()

# 或從自己的設定明確傳入
account = SinopacAccount(
    api_key=os.environ['SHIOAJI_API_KEY'],
    secret_key=os.environ['SHIOAJI_SECRET_KEY'],
    certificate_person_id=os.environ['SHIOAJI_CERT_PERSON_ID'],
    certificate_path=os.environ['SHIOAJI_CERT_PATH'],
    certificate_password=os.environ['SHIOAJI_CERT_PASSWORD'],
)
# 不要在程式碼中硬編碼帳密！
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

### finlab.online.core.account.Account

```python
Account()
```

#### finlab.online.core.account.Account.create_order

```python
create_order(action, stock_id, quantity, price, odd_lot, market_order, best_price_limit, order_cond) -> str
```

產生新的委託單

**Parameters**

- `action` (Action): 買賣方向，通常為 'BUY' 或是 'SELL'
- `stock_id` (str): 股票代號 ex: '2330'
- `quantity` (Number): 委託股票的總數量（張數），允許小數點
- `price` (Number): 股票買賣的價格(限價單)
- `force` (bool): 是否用最差之價格（長跌停）強制成交? 當成交量足夠時，可以比較快成交，然而當成交量低時，容易有大的滑價
- `wait_for_best_price` (bool): 是否用最佳之價格（長跌停），無限時間等待？當今天要出場時，可以開啟等漲停價來購買，當今天要買入時，可以掛跌停價等待買入時機。

**Returns**

- `` (str): order id 券商提供的委託單編號

#### finlab.online.core.account.Account.update_order

```python
update_order(order_id, price, quantity) -> None
```

產生新的委託單

**Attributes**

- `order_id` (str): 券商所提供的委託單 ID
- `price` (Number): 更新的限價
- `quantity` (Number): 更新的待成交量

**Returns**

- `` (None): 無跳出 erorr 代表成功更新委託單

#### finlab.online.core.account.Account.cancel_order

```python
cancel_order(order_id) -> None
```

刪除委託單

建議使用 刪除委託單此功能前，先使用 update_order() 來更新委託單的狀況！如下
```py
acc.update_order()
acc.cancel_order('ORDER_ID')
```

**Attributes**

- `order_id` (str): 券商所提供的委託單 ID

**Returns**

- `` (None): 代表成功更新委託單

#### finlab.online.core.account.Account.get_orders

```python
get_orders() -> dict[str, Order]
```

拿到現在所有委託單

**Returns**

- `` (Dict[str, Order]): 所有委託單 id 與委託單資料 例如 `{'12345A': Order(order_id='12345A', stock_id='5410',...),...}`

#### finlab.online.core.account.Account.get_stocks

```python
get_stocks(stock_ids) -> dict[str, Stock]
```

拿到現在股票報價

**Attributes**

- `stock_ids` (`list` of `str`): 一次拿取所有股票的報價，ex: ['1101', '2330']

**Returns**

- `` (dict): 報價資料， 例如 `{'1101': Stock(stock_id='1101', open=31.15, high=31.85, low=31.1, close=31.65, bid_price=31.6, bid_volume=728.0, ask_price=31.65, ask_volume=202)}`

#### finlab.online.core.account.Account.get_position

```python
get_position() -> Position
```

拿到當前帳戶的股票部位

**Returns**

- `` (Position): 當前股票部位

#### finlab.online.core.account.Account.get_total_balance

```python
get_total_balance() -> int
```

拿到當前帳戶的股票部位淨值

#### finlab.online.core.account.Account.get_cash

```python
get_cash() -> int
```

拿到當前帳戶的現金

#### finlab.online.core.account.Account.get_settlement

```python
get_settlement() -> int
```

拿到當前帳戶的結算資料

#### finlab.online.core.account.Account.support_best_price_limit

```python
support_best_price_limit() -> bool
```

是否能以漲跌停價掛單（best_price_limit）

#### finlab.online.core.account.Account.get_market

```python
get_market() -> Market
```

拿到當前帳戶的市場

### account.get_price()

取得每檔股票的最後成交價；還沒有成交時，改用買賣報價的中間值。

```python
price = account.get_price(['2330', '2317'])
```

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `stock_ids` | `list[str]` | 必填 | 股票代號清單。 |

## 設定目標部位

`Position` 是要讓帳戶持有的股票與數量。最常用的是從回測報告直接換算：

```python
from finlab.online.order_executor import Position

# 策略操作金額各一百萬，兩個部位可以相加
position1 = Position.from_report(report1, 1_000_000)
position2 = Position.from_report(report2, 1_000_000)
total_position = position1 + position2

# 也可以直接寫：持有 1 張 2330，以及 1 張又 100 股 1101
manual = Position({'2330': 1, '1101': 1.1})
```

`Position.from_report()` 算的是「現在」該持有的部位：下次換股前用 `report.weights`，換股時間一到（與 `report.is_rebalance_due()` 同一個規則）就改用 `report.next_weights`；有停損停利待出場的股票權重為 0。一份報告裡包含多個策略時，請改用 `finlab.portfolio.Portfolio`。

`Position.from_weight()` 和 `backtest.sim()` 一樣，權重絕對值總和大於 1 時會等比例縮到 1。`odd_lot=False`（預設）只買整張，資金不夠買一張的股票會是 0 股，並發出 `ZeroShareAllocationWarning`。
### finlab.online.core.position.Position

```python
Position(stocks, weights, margin_trading, short_selling, day_trading_long, day_trading_short)
```

使用者可以利用 Position 輕鬆建構股票的部位，並且利用 OrderExecuter 將此部位同步於實際的股票帳戶。

**Attributes**

- `stocks` (`dict` of `str`): `number.Number`): 股票代號與張數 ex: {'1101': 1} 是指持有一張 1101 台泥，可以接受負數，代表做空。
- `margin_trading` (bool, default False): 做多部位是否使用融資
- `short_selling` (bool, default False): 做空部位是否使用融券
- `day_trading_long` (bool, default False): 做多部位為當沖先做多
- `day_trading_short` (bool, default False): 做空部位為當沖先做空

**Examples**

設計部位，持有一張和 100 股 1101
```py
from finlab.online.order_executor import Position

Position({'1101': 1.1})
```
output
```json
[
    {'stock_id': '1101',
     'quantity': 1.1,
     'order_condition': <OrderCondition.CASH: 1>
    }
]
```

將兩個部位相加
```py
from finlab.online.order_executor import Position

p1 = Position({'1101': 1})
p2 = Position({'2330': 1})
p1 + p2
```
output
```json
[
    {'stock_id': '1101', 'quantity': 1.0, 'order_condition': <OrderCondition.CASH: 1>},
    {'stock_id': '2330', 'quantity': 1.0, 'order_condition': <OrderCondition.CASH: 1>}
]
```

#### finlab.online.core.position.Position.from_list

```python
from_list(position) -> Position
```

利用 `dict` 建構股票部位

**Attributes**

- `position` (`list` of `dict`): 股票詳細部位 ```py from finlab.online.enums import OrderCondition from finlab.online.order_executor import Position Position.from_list( [{   'stock_id': '1101', # 股票代號   'quantity': 1.1, # 張數   'order_condition': OrderCondition.CASH # 現股融資融券、先買後賣 }]) ``` 其中 OrderCondition 除了 `CASH` 外，還有 `MARGIN_TRADING`、`DAY_TRADING_LONG`、`SHORT_SELLING`、`DAY_TRADING_SHORT`。

#### finlab.online.core.position.Position.from_entries

```python
from_entries(entries) -> Position
```

Build Position from schema entries (e.g. finlab.schemas.PositionEntry).

#### finlab.online.core.position.Position.to_entries

```python
to_entries() -> list[Any]
```

Convert Position internal payload to schema entries.

#### finlab.online.core.position.Position.from_weight

```python
from_weight(weights, fund, price, odd_lot, board_lot_size, allocation, precision, leverage, price_history, margin_ratio, **kwargs) -> Position
```

利用 `weight` 建構股票部位

**Attributes**

- `weights` (dict[str, float] 或 pd.Series): 股票詳細部位，股票代號對應權重。 與 `backtest.sim()` 相同，若權重絕對值總和大於 1，會等比例縮放至總和為 1。
- `fund` (int): 資金大小
- `price` (None 或 pd.Series 或 dict[str, float]): 股票代號對應到的價格，若無則使用最近個交易日的收盤價。
- `odd_lot` (bool, default False): 是否考慮零股。為 False 時只買整張，資金不足一張的股票會是 0 股， 並發出 `ZeroShareAllocationWarning`。
- `board_lot_size` (None 或 int): 一張股票等於幾股
- `allocation` (function, default greedy_allocation): 資產配置演算法選定，預設為`finlab.online.utils.greedy_allocation`（最大資金部屬貪婪法）。 呼叫方式為 `allocation(weights, price * board_lot_size, effective_fund * 10**precision)`， 其中 effective_fund 在 leverage > 1 時為 fund * leverage，否則為 fund； precision 為依零股與 board_lot_size 調整後的有效精度。 需回傳 `(dict[股票代號, 張數 * 10**precision], 剩餘資金)`。
- `precision` (None 或 int): board_lot_size 為 1 且 odd_lot=True 時，計算張數的精度，1 代表 0.1 張，2 代表 0.01 張，以此類推。 其他情況只買整數張，精度為 0。
- `leverage` (float, default 1.0): 目標槓桿倍數，預設為1.0（不使用融資）。若>1.0，會根據波動度分配融資， 總曝險為 fund * leverage，自備款（現股加融資自備款）不超過 fund。
- `price_history` (None 或 pd.DataFrame): 股票歷史價格，若 leverage > 1.0 時必須提供。
- `margin_ratio` (float, default 0.6): 融資成數，預設 0.6（上市股票）；上櫃股票為 0.5。只在 leverage > 1.0 時使用。
- `margin_trading` (bool): 做多部位是否使用融資。odd_lot=True 時零股不能融資，不足一張的部分用現股。
- `short_selling` (bool): 做空部位是否使用融券。odd_lot=True 時零股不能融券，不足一張的部分不放空。
- `day_trading_long` (bool): 做多部位為當沖先做多

**Examples**

例如，用 100 萬的資金，全部投入，持有 1101 和 2330 各一半：
```py
from finlab.online.order_executor import Position

Position.from_weight({
'1101': 0.5,
'2330': 0.5,
}, fund=1000000)

```
output
```
[

    {'stock_id': '1101', 'quantity': 13, 'order_condition': <OrderCondition.CASH: 1>},
    {'stock_id': '2330', 'quantity': 1, 'order_condition': <OrderCondition.CASH: 1>}
      ]
      ```

#### finlab.online.core.position.Position.from_report

```python
from_report(report, fund, **kwargs) -> Position
```

利用回測完的報告 `finlab.report.Report` 建構股票部位。

**Attributes**

- `report` (finlab.report.Report): 回測完的結果報告。
- `fund` (int): 希望部屬的資金。
- `price` (pd.Series or `dict` of `float`): 股票代號對應到的價格，若無則使用最近個交易日的收盤價。
- `odd_lot` (bool): 是否考慮零股。預設為 False，只使用整張操作。
- `board_lot_size` (int): 一張股票等於幾股。預設為1000，一張等於1000股。
- `allocation` (func): 資產配置演算法選定，預設為`finlab.online.utils.greedy_allocation`（最大資金部屬貪婪法）。
- `margin_trading` (bool): 做多部位是否使用融資
- `short_selling` (bool): 做空部位是否使用融券
- `day_trading_long` (bool): 做多部位為當沖先做多
- `day_trading_short` (bool): 做空部位為當沖先做空
- `leverage` (float): 目標槓桿倍數，預設為1.0（不使用融資）。若>1.0，會根據波動度分配融資。

> **Example**
>
> ```py
> from finlab import backtest
> from finlab.online.order_executor import Position
> 
> report1 = backtest.sim(...)
> report2 = backtest.sim(...)
> 
> position1 = Position.from_report(report1, 1000000) # 策略操作金額一百萬
> position2 = Position.from_report(report2, 1000000) # 策略操作金額一百萬
> 
> total_position = position1 + position2
> ```

#### finlab.online.core.position.Position.to_json

```python
to_json(path) -> None
```

Converts the position dictionary to a JSON file and saves it to the specified path.

**Parameters**

- `path` (str): The path where the JSON file will be saved.

**Returns**

- `` (None): None

#### finlab.online.core.position.Position.from_json

```python
from_json(path) -> Position
```

Load a JSON file from the given path and convert it to a list of positions.

**Parameters**

- `path` (str): The path to the JSON file.

**Returns**

- `` (Position): None

## 讓帳戶持股對齊目標

`create_orders()` 會先取消帳戶裡未成交的委託，再送出讓帳戶持股變成目標部位的委託，預設以最後一筆成交價掛限價單，回傳送出（或預覽時將送出）的委託清單。`market_order`、`best_price_limit`、`extra_bid_pct` 三者只能擇一設定。

### 調整掛單價格

```python
# 預設以最後成交價掛限價單，extra_bid_pct 可微調價格
# 負值 = 比市價低（較保守），正值 = 比市價高（較積極）
executor.create_orders(
    extra_bid_pct=-0.01  # 比當前價格低 1% 掛單，避免滑價
)

# 類市價單：買單掛漲停價、賣單掛跌停價，盡量即刻成交
executor.create_orders(market_order=True)
```

### 大額委託分批送出

```python
import time

# 將大額訂單分 3 次執行
# progress 是「剩餘差距」的比例，不是原始目標的比例
# 每輪成交後剩餘量會減少，所以比例要遞增
for p in [1 / 3, 1 / 2, 1]:
    executor.create_orders(
        progress=p  # 依序執行 1/3、1/2、1 的剩餘量
    )
    time.sleep(60)  # 間隔 1 分鐘
```

### 分開開發與正式環境

```python
import os

# 開發環境：跑完整流程，但只印出委託
executor = OrderExecutor(target, account=account)
if os.environ.get('ENV') == 'development':
    executor.create_orders(view_only=True)
else:
    executor.create_orders()
```
### finlab.online.core.executor.OrderExecutor

```python
OrderExecutor(target_position, account)
```

對比實際帳戶與欲部屬的股票部位，進行同步

**Parameters**

- `target_position` (Position): 想要部屬的股票部位。
- `account` (Account): 目前支援永豐與富果帳戶，請參考 Account 來實做。

#### finlab.online.core.executor.OrderExecutor.show_alerting_stocks

```python
show_alerting_stocks() -> None
```

產生下單部位是否有警示股，以及相關資訊

#### finlab.online.core.executor.OrderExecutor.cancel_orders

```python
cancel_orders(buy_only, sell_only) -> None
```

刪除所有未實現委託單

**Attributes**

- `buy_only` (bool, default False): 若設為 True，只取消買單
- `sell_only` (bool, default False): 若設為 True，只取消賣單

#### finlab.online.core.executor.OrderExecutor.generate_orders

```python
generate_orders(progress, progress_precision, as_entries, quantity_type, _internal) -> list[dict[str, Any]] | list[Any]
```

Generate orders based on the difference between target position and present position.

**Returns**

- `orders` (dict): Orders to be executed.

#### finlab.online.core.executor.OrderExecutor.execute_orders

```python
execute_orders(orders, market_order, best_price_limit, view_only, extra_bid_pct, cancel_orders, buy_only, sell_only) -> list[dict[str, Any]]
```

產生委託單，將部位同步成 self.target_position
預設以該商品最後一筆成交價設定為限價來下單

**Attributes**

- `orders` (list): 欲下單的部位，通常是由 `self.generate_orders` 產生。
- `market_order` (bool, default False): 以類市價盡量即刻成交：所有買單掛漲停價，所有賣單掛跌停價
- `best_price_limit` (bool, default False): 掛芭樂價：所有買單掛跌停價，所有賣單掛漲停價
- `view_only` (bool, default False): 預設為 False，會實際下單。若設為 True，不會下單，只會回傳欲執行的委託單資料(dict)
- `extra_bid_pct` (float, default 0): 以該百分比值乘以價格進行追價下單，如設定為 0.05 時，將以當前價的 +(-)5% 的限價進買入(賣出)，也就是更有機會可以成交，但是成交價格可能不理想； 假如設定為 -0.05 時，將以當前價的 -(+)5% 進行買入賣出，也就是限價單將不會立即成交，然而假如成交後，價格比較理想。參數有效範圍為 -0.1 到 0.1 內。
- `buy_only` (bool, default False): 若設為 True，只下買單
- `sell_only` (bool, default False): 若設為 True，只下賣單

#### finlab.online.core.executor.OrderExecutor.create_orders

```python
create_orders(market_order, best_price_limit, view_only, extra_bid_pct, progress, progress_precision, buy_only, sell_only) -> list[dict[str, Any]]
```

產生委託單，將部位同步成 self.target_position
預設以該商品最後一筆成交價設定為限價來下單

**Attributes**

- `market_order` (bool, default False): 以類市價盡量即刻成交：所有買單掛漲停價，所有賣單掛跌停價
- `best_price_limit` (bool, default False): 掛芭樂價：所有買單掛跌停價，所有賣單掛漲停價
- `view_only` (bool, default False): 預設為 False，會實際下單。若設為 True，不會下單，只會回傳欲執行的委託單資料(dict)
- `extra_bid_pct` (float, default 0): 以該百分比值乘以價格進行追價下單，如設定為 0.05 時，將以當前價的 +(-)5% 的限價進買入(賣出)，也就是更有機會可以成交，但是成交價格可能不理想； 假如設定為 -0.05 時，將以當前價的 -(+)5% 進行買入賣出，也就是限價單將不會立即成交，然而假如成交後，價格比較理想。參數有效範圍為 -0.1 到 0.1 內。
- `progress` (float, default 1): 進度，預設為 1，即全部下單。若設定為 0.5，則只下一半的單。
- `progress_precision` (int, default 0): 進度的精度，預設為 0，即只下整數張。若設定為 1，則下到 0.1 張。
- `buy_only` (bool, default False): 若設為 True，只下買單
- `sell_only` (bool, default False): 若設為 True，只下賣單

#### finlab.online.core.executor.OrderExecutor.update_order_price

```python
update_order_price(extra_bid_pct, buy_only, sell_only) -> None
```

更新委託單，將委託單的限價調整成當天最後一筆價格。
（讓沒成交的限價單去追價）

**Attributes**

- `extra_bid_pct` (float, default 0): 以該百分比值乘以價格進行追價下單，如設定為 0.1 時，將以超出(低於)現價之10%價格下單，以漲停(跌停)價為限。參數有效範圍為 0 到 0.1 內
- `buy_only` (bool, default False): 若設為 True，只更新買單
- `sell_only` (bool, default False): 若設為 True，只更新賣單

## 下單前要檢查的事

### 過濾處置股

直接下單可能買到處置股。`OrderExecutor` 的目標不是回測用的布林 DataFrame，要先用 `to_list()` 取出部位、過濾後再用 `Position.from_list()` 組回來：

```python
from finlab import data
from finlab.online.order_executor import OrderExecutor, Position

# 錯誤：直接下單可能買到處置股
# OrderExecutor(target, account=account).create_orders()  # ❌

# 正確：使用處置股 filter 過濾 finlab.online.Position
disposal_stock_filter = data.get('etl:disposal_stock_filter')
latest_filter = disposal_stock_filter.iloc[-1].fillna(False)

filtered_target = Position.from_list(
    [entry for entry in target.to_list() if latest_filter.get(entry['stock_id'], False)]
)

OrderExecutor(filtered_target, account=account).create_orders()  # ✅
```

`executor.show_alerting_stocks()` 會列出委託中屬於處置股或信用交易警示股的標的，這些股票需要事先向券商圈存現金或股票（僅限台股）。

### 確認資金足夠

下單前比較目標部位市值與 `account.get_total_balance()`，不足時調低 `Position.from_report()` 的 `fund` 或追加資金。檢查方式見下方常見問題「如何確保下單安全？」的 `safe_order_check()`。

### 漲跌停鎖死可能整天無法成交

台股有漲跌停限制，`create_orders()` 會用券商回報的漲跌停價夾住限價；股票鎖漲停時的買單、鎖跌停時的賣單可能整天無法成交。隔日的漲跌停價可查參考價表 `reference_price`（每檔股票一列）：

```python
from finlab import data

ref = data.get('reference_price').set_index('stock_id')
print(ref.loc[['2330', '2317'], ['收盤價', '漲停價', '跌停價']])
```

## 查詢委託狀態

`account.get_orders()` 回傳目前所有委託單，key 是券商的委託單編號，value 是 `Order`：

```python
for order_id, order in account.get_orders().items():
    print(order_id, order.stock_id, order.status, order.filled_quantity)
```

`status` 是 `NEW`、`PARTIALLY_FILLED`、`FILLED` 或 `CANCEL`；`stock_id` 也可以用 `symbol` 取得。
### finlab.online.core.account.Order

```python
Order(order_id, stock_id, action, price, quantity, filled_quantity, status, order_condition, time, org_order)
```

Order status

委託單的狀態

**Attributes**

- `order_id` (str): 委託單的 id，與券商 API 所提供的 id 一致
- `stock_id` (str): 股票代號 ex: '2330' (亦可透過 symbol 屬性存取)
- `action` (Action): 買賣方向，通常為 'BUY' 或是 'SELL'
- `price` (Number): 股票買賣的價格(限價單)
- `quantity` (Number): 委託股票的總數量（張數），允許小數點
- `filled_quantity` (Number): 以成交股票的數量（張數），允許小數點
- `status` (OrderStatus): 委託狀態，可以設定為：'NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCEL'
- `time` (datetime.datetime): 委託時間
- `org_order` (Any = None): 券商所提供的委託物件格式

## 常見問題

<details><summary>如何確保下單安全？</summary>

實施以下檢查機制：

```python
def safe_order_check(target, account, max_stocks=50, max_weight=0.15):
    """下單前安全檢查"""
    price = account.get_price([p['symbol'] for p in target])
    # 台股的 quantity 單位是張（1 張 = 1000 股）
    values = [abs(float(p['quantity'])) * 1000 * price[p['symbol']] for p in target]
    total = sum(values)

    # 1. 檢查持倉數量
    if len(values) > max_stocks:
        raise ValueError(f"❌ 持倉過多（{len(values)} 檔），超過限制 {max_stocks} 檔")

    # 2. 檢查單一持股權重
    largest = max(values) / total if total else 0
    if largest > max_weight:
        raise ValueError(f"❌ 單股權重過高（{largest:.1%}），超過限制 {max_weight:.0%}")

    # 3. 檢查可用資金
    available = account.get_total_balance()
    if total > available * 1.1:  # 留 10% 緩衝
        raise ValueError(f"❌ 資金不足！需要 {total:,.0f}，可用 {available:,.0f}")

    print("✅ 安全檢查通過")
    return True

# 使用
if safe_order_check(target, account):
    executor.create_orders()
```

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

```python
import time

import schedule
from finlab import data
from finlab.backtest import sim
from finlab.online.order_executor import OrderExecutor, Position

def auto_trade():
    """每日自動下單"""
    try:
        # 1. 重新執行策略，取得最新目標部位
        close = data.get('price:收盤價')
        position = (close / close.shift(120)).is_largest(20)
        report = sim(position, resample='M', upload=False)
        target = Position.from_report(report, fund=1_000_000)

        # 2. 安全檢查
        if safe_order_check(target, account):
            # 3. 執行下單
            OrderExecutor(target, account=account).create_orders()
            print(f"✅ 下單完成：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        # 4. 錯誤通知（Email、聊天群組 webhook）
        print(f"❌ 下單失敗：{e}")

# 每日 13:00 執行（台股 13:30 收盤前 30 分鐘）
schedule.every().day.at("13:00").do(auto_trade)

while True:
    schedule.run_pending()
    time.sleep(60)
```

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

> [!CAUTION]
> **最後提醒**
>
> **請務必在模擬帳戶充分測試後，才使用真實資金！**
>
> **建議測試清單**：
> - 下單流程完整執行無錯誤
> - 持倉計算正確（與預期一致）
> - 資金控制正常（不超支）
> - 異常處理機制有效
> - 通知機制正常運作
> - 連續運行 1 個月無問題
>
> **只有在以上項目全部確認後，才考慮使用真實資金！**

## 下一步

- [實盤下單（單策略）](order_api.md) 各券商的帳密設定與基礎下單流程。
- [實盤下單（多策略）](order_api2.md) 用 PortfolioSyncManager 合併多個策略的部位後下單。
- [風險管理完整指南](https://studio.finlab.finance/docs/workflows/risk_management) 實盤的部位、停損與資金控管。
- [完整策略開發流程](https://studio.finlab.finance/docs/workflows/complete_strategy_workflow) 從研究、回測到實盤的步驟。

原始碼在 [GitHub](https://github.com/finlab-python/finlab/blob/main/finlab/online/)。
