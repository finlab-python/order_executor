# 下單：單一策略

這一頁帶你把一個策略變成證券帳戶裡的委託：**回測 → 換算張數 → 連接券商 → 預覽後下單**。要同時跑好幾個策略，請看[下單：多策略](order_api2.md)。

> [!CAUTION]
> **實盤交易用的是真錢**
>
> 程式或設定出錯，都可能造成財務損失。下單前務必：
>
> 1. 先在**模擬帳戶**測試至少 1 週
> 2. 初期資金不超過總資金的 **10-20%**
> 3. 使用 `view_only=True` 預覽訂單
> 4. 每日監控持倉與訂單狀態
> 5. 設定停損機制，避免單次巨大虧損

## 從回測到下單

### 安裝 finlab-online

下單程式在開源套件 `finlab-online`，和 finlab 一起安裝：

```bash
pip install finlab finlab-online
```

原本寫 `finlab.online` 的程式不用改。

### 在開盤前跑一次策略

在下一個交易日開盤前執行你的策略，取得回測報告：

```python
from finlab import backtest

# 寫你自己的策略
report = backtest.sim(...)
```

回測用 T 日收盤後已公布的資料產生訊號，在下一個交易日成交；實盤也照這個節奏，在開盤前算好要持有的股票：

| 時間 | 發生什麼 | 說明 |
|---|---|---|
| T 日收盤後 | 當天資料更新 | 日期是 T 的那一列，只用到 T 日已公布的資料。 |
| T 日 | 產生訊號 | `position` 在 T 日那一列，決定要持有哪些股票。 |
| 下一個交易日 | 成交 | 價格依 `trade_at_price`，預設收盤價。 |
| 到下次換股 | 持有 | |

### 換算每檔股票的張數

先看最近一期的部位：

```python
print(report.current_trades)
```

`current_trades` 列出最新訊號日仍持有或有變動的交易，包含進出場日期、報酬率、MAE/MFE、目前的目標權重 `weight`，以及下次換股的 `next_weights`。

確認沒問題後，用 `Position.from_report()` 依投入的總資金換算每檔股票的張數：

```python
from finlab.online.order_executor import Position

# 總資金
fund = 1000000
position = Position.from_report(report, fund)
print(position)
```

```text
[{'stock_id': '2330', 'quantity': 1, 'order_condition': <OrderCondition.CASH: 1>}]
```

這個 `Position` 代表：你的帳戶中只希望有一張 `2330` 台積電，並且是現貨。台股的 `quantity` 單位是張（1,000 股）；美股帳戶是股數。

預設只買整張：每檔先用分到的資金買整張，剩下的錢再一張一張補給離目標比例最遠、還買得起的股票，所以分到的資金不足一張的股票可能補到一張，也可能是 0 張。想買零股、自己指定張數或合併多個策略，見下方[調整部位](#調整部位)。

### 安裝券商套件並連接帳戶

台股支援玉山證券、永豐證券、台新證券（原元富證券）及富邦證券，美股支援嘉信（Charles Schwab），擇一使用即可。帳號密碼設成環境變數，只需設定你要用的券商。

#### 玉山證券

[▶ YouTube](https://www.youtube.com/watch?v=AAGcIgJAUVY)

1. 照 [config 教學](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/quick-start/)取得 config 設定檔。
2. 登入[玉山證券 API](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/key/)，取得市場行情 Token。
3. 安裝套件，設定環境變數並連線：

```bash
pip install esun-trade
```

```python
from finlab.online.esun_account import EsunAccount
import os

os.environ['ESUN_CONFIG_PATH'] = '玉山證券交易設定檔(config.ini.example)路徑'
os.environ['ESUN_MARKET_API_KEY'] = '玉山證券的行情API Token'
os.environ['ESUN_ACCOUNT_PASSWORD'] = '玉山證券的帳號密碼'
os.environ['ESUN_CERT_PASSWORD'] = '玉山證券的憑證密碼'

acc = EsunAccount()
```

<details><summary>舊版 Fugle 環境變數（仍可使用）</summary>

```python
from finlab.online.fugle_account import FugleAccount
import os

os.environ['FUGLE_CONFIG_PATH'] = '玉山證券交易設定檔(config.ini.example)路徑'
os.environ['FUGLE_MARKET_API_KEY'] = '玉山證券的行情API Token'
os.environ['FUGLE_ACCOUNT_PASSWORD'] = '玉山證券的帳號密碼'
os.environ['FUGLE_CERT_PASSWORD'] = '玉山證券的憑證密碼'

acc = FugleAccount()
```

</details>

下單錯誤代碼請見[玉山證券文件](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/reference/error-code/)。若不熟券商 API，可先照[券商教學](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/quick-start/)練習；那邊串接成功，FinLab 套件的串接也是如法炮製。

#### 永豐證券

[▶ YouTube](https://www.youtube.com/watch?v=BDsVOI4cZNk)

1. 取得憑證（見永豐官方的[金鑰與憑證申請](https://sinotrade.github.io/zh/tutor/prepare/token/)）：
    - 到永豐理財網的 [API 管理頁面](https://www.sinotrade.com.tw/newweb/PythonAPIKey/)點「下載憑證」，Windows、macOS 都可以下載。
    - 也可以用 eleader 下載憑證，eleader 只支援 Windows。
2. 安裝套件，設定環境變數並連線：

```bash
pip install shioaji
```

```python
import os
from finlab.online.sinopac_account import SinopacAccount

os.environ['SHIOAJI_API_KEY'] = '永豐證券API_KEY'
os.environ['SHIOAJI_SECRET_KEY'] = '永豐證券SECRET_KEY'
os.environ['SHIOAJI_CERT_PERSON_ID'] = '身份證字號'
os.environ['SHIOAJI_CERT_PATH'] = '永豐證券憑證路徑'
os.environ['SHIOAJI_CERT_PASSWORD'] = '永豐證券憑證密碼'  # 預設與身份證字號相同

acc = SinopacAccount()
```

若不熟券商 API，可先照[券商教學](https://sinotrade.github.io/quickstart/)練習；那邊串接成功，FinLab 套件的串接就很簡單。

#### 台新證券（原元富）

元富證券已於 2026 年 4 月 6 日併入台新證券。詳細步驟見台新官方的[事前準備](https://ml-fugle-api.tssco.com.tw/FugleSDK/docs/trading/prepare/)：

1. **簽署**：線上簽署「API 使用風險暨聲明書」，簽署隔天才生效。
2. **憑證**：用「憑證e管家」申請並匯出 .pfx 憑證檔；用「憑證快遞」申請的憑證不能用在 API。
3. **安裝**：`taishin_sdk` 不在 PyPI，先到[台新 SDK 下載頁](https://ml-fugle-api.tssco.com.tw/FugleSDK/docs/download/download-sdk)下載對應平台的 whl 再安裝。官方支援 Python 3.8～3.12。

```bash
pip install taishin_sdk-<版本>-cp37-abi3-<平台>.whl
```

4. **連線**：設定環境變數並建立帳戶：

```python
import os
from finlab.online.taishin_account import TaishinAccount

os.environ['TAISHIN_NATIONAL_ID'] = '身分證字號'
os.environ['TAISHIN_ACCOUNT'] = '分公司代號加帳號'  # 不設定就用第一個帳號
os.environ['TAISHIN_ACCOUNT_PASS'] = '登入密碼'
os.environ['TAISHIN_CERT_PATH'] = '憑證檔（.pfx）路徑'
os.environ['TAISHIN_CERT_PASS'] = '憑證密碼'

acc = TaishinAccount()

# 第一次使用台新 API 時執行一次，開通 API 資格（成功回傳 True），之後可以刪掉
# acc.sdk.register_api_auth(acc.target_account)
```

<details><summary>舊版元富環境變數（仍可使用）</summary>

`MasterlinkAccount`（`finlab.online.masterlink_account`）與 `TaishinAccount` 是同一個類別，沒有設定 `TAISHIN_*` 時會讀對應的 `MASTERLINK_*`，例如 `MASTERLINK_NATIONAL_ID`。原本的程式不用改，只要把套件換成 `taishin_sdk`。

</details>

#### 富邦證券

請參考[富邦證券的教學](https://www.fbs.com.tw/TradeAPI/docs/trading/introduction/)取得憑證，把憑證放在對應的路徑，安裝相對應的套件後執行：

```python
import os
from finlab.online.fubon_account import FubonAccount

os.environ['FUBON_NATIONAL_ID'] = "A123456789"
os.environ['FUBON_ACCOUNT_PASS'] = "your_password"
os.environ['FUBON_CERT_PATH'] = "/path/to/cert.pfx"
os.environ['FUBON_CERT_PASS'] = "憑證密碼"  # 選填：登入時傳給富邦 SDK 的憑證密碼
os.environ['FUBON_ACCOUNT'] = "帳號"  # 選填：指定帳號，找不到會報錯；不設定就用第一個證券帳戶
# os.environ['FUBON_BASE_URL'] = "連線網址"  # 選填：傳給富邦 SDK（FubonSDK）的連線網址

acc = FubonAccount()
```

`FUBON_NATIONAL_ID`、`FUBON_ACCOUNT_PASS`、`FUBON_CERT_PATH` 必須設定，缺少時會報錯；其餘三個是選填。

#### Charles Schwab

嘉信（Charles Schwab）用於美股帳戶：

1. 到 [Schwab Developer Portal](https://developer.schwab.com/) 註冊 app，取得 app key 與 secret。
2. 用 [schwab-py](https://schwab-py.readthedocs.io/) 的登入流程建立 token 檔，`SchwabAccount` 會讀取這個檔案。
3. 安裝套件，設定環境變數並連線：

```bash
pip install schwab-py
```

```python
import os
from finlab.online.schwab_account import SchwabAccount

os.environ['SCHWAB_API_KEY'] = 'Schwab app key'
os.environ['SCHWAB_SECRET'] = 'Schwab app secret'
os.environ['SCHWAB_TOKEN_PATH'] = '/path/to/token.json'

acc = SchwabAccount()
```

### 檢查處置股與警示股

用 `OrderExecutor` 比對帳戶現有部位與 `position`，之後的下單都由它執行：

```python
from finlab.online.order_executor import OrderExecutor

order_executer = OrderExecutor(position, account=acc)

# 顯示下單部位是否有警示股及相關資訊
order_executer.show_alerting_stocks()
```

```text
=== 處置股/警示股警告 ===
以下待下單股票在處置股或信用警示名單中：
買入 8101 0.429 張 - 總價約         2672.67
請注意：處置股可能有預收款券、分盤交易等限制。
```

若沒有待下單股票落在名單中，則只會顯示「待下單股票中無處置股或警示股。」

下單部位含有「全額交割股」、「處置股」、「警示股」時，需先於證券帳戶圈存，作法依券商而定，例如[富果圈存](https://support.fugle.tw/trading/trading-troubleshoot/5231/)、[永豐圈存](https://www.sinotrade.com.tw/richclub/freshman/%E6%B0%B8%E8%B1%90%E9%87%91%E8%AD%89%E5%88%B8-%E9%A0%90%E6%94%B6%E6%AC%BE%E5%88%B8-%E6%95%B8%E4%BD%8D%E5%B9%B3%E5%8F%B0%E6%9C%8D%E5%8B%99%E5%85%A5%E5%8F%A3%E4%BB%8B%E7%B4%B9-%E6%83%B3%E8%B2%B7%E8%99%95%E7%BD%AE%E8%82%A1%E5%85%88%E7%9C%8B%E9%80%99%E4%B8%80%E7%AF%87--60ee886daefbe326a0c7bb1b)。依 `show_alerting_stocks()` 的結果圈存後，再繼續下單。

### 先預覽，再下單

先用瀏覽模式看會送出哪些委託，這一步不會真的下單：

```python
order_executer.create_orders(view_only=True)
```

確認無誤後才實際下單。預設使用最近一筆成交價當成限價；初次使用建議收市時測試。

```python
# 會真的下單
order_executer.create_orders()
```

委託送出後還沒成交時，可以擇一更新限價（將最後一筆成交價當成新的限價）：

```python
order_executer.update_order_price()
```

或刪除所有委託單：

```python
order_executer.cancel_orders()
```

## 調整部位

`Position` 可以直接建構，也可以相加減，用來改買零股、指定張數或合併策略。

### 改買零股

在 `from_report()` 加上 `odd_lot=True`：

```python
# 整股
position = Position.from_report(report, fund)

# 零股
position = Position.from_report(report, fund, odd_lot=True)
```

### 自己指定張數

直接用「股票代號: 張數」建構 `Position`：

```python
position = Position({'2330': 1, '1101': 1.001})
```

```text
[{'stock_id': '2330', 'quantity': 1, 'order_condition': <OrderCondition.CASH: 1>}
 {'stock_id': '1101', 'quantity': 1.001, 'order_condition': <OrderCondition.CASH: 1>}]
```

### 增減部位

`Position` 可以相加減：

```python
# 減一張 2330 股票
new_position = position - Position({'2330': 1})
# 增加一張 1101 股票
new_position = position + Position({'1101': 1})
```

### 合併多個策略

多個策略的部位直接相加，再交給同一個 `OrderExecutor`：

```python
from finlab import backtest
from finlab.online.order_executor import Position

report1 = backtest.sim(...)
report2 = backtest.sim(...)

position1 = Position.from_report(report1, 1000000)  # 策略操作金額一百萬
position2 = Position.from_report(report2, 1000000)  # 策略操作金額一百萬

total_position = position1 + position2
```

要每天管理多個策略的權重、換股日與停損停利，請用[下單：多策略](order_api2.md)的 `PortfolioSyncManager`。

## 查看帳戶目前的部位

連線後的帳戶物件都可以用 `get_position()` 查目前的部位，例如永豐證券：

```python
from finlab.online.sinopac_account import SinopacAccount

acc = SinopacAccount()
print(acc.get_position())
```

```text
[{'stock_id': '2330', 'quantity': 1, 'order_condition': <OrderCondition.CASH: 1>}
 {'stock_id': '1101', 'quantity': 1.001, 'order_condition': <OrderCondition.CASH: 1>}]
```

其他券商的用法相同，例如玉山證券改用 `EsunAccount()`（`finlab.online.esun_account`）。

## 常見錯誤與解決方法

### 錯誤 1：帳戶連線失敗

**現象**：執行 `acc = SinopacAccount()` 或 `acc = EsunAccount()` 時拋出連線錯誤：

```python
from finlab.online.sinopac_account import SinopacAccount

acc = SinopacAccount()
# ConnectionError: 無法連線至券商 API
```

**原因**：

- 環境變數未正確設定（API KEY、憑證路徑等）
- 憑證檔案不存在或路徑錯誤
- 憑證密碼錯誤
- 網路連線問題或券商 API 服務暫停

**解決方法**：依序檢查環境變數、憑證檔案，再試著連線並看錯誤類型。

<details><summary>永豐證券的檢查程式</summary>

```python
import os
from finlab.online.sinopac_account import SinopacAccount

# 步驟 1：檢查環境變數是否設定
required_env_vars = [
    'SHIOAJI_API_KEY',
    'SHIOAJI_SECRET_KEY',
    'SHIOAJI_CERT_PERSON_ID',
    'SHIOAJI_CERT_PATH',
    'SHIOAJI_CERT_PASSWORD',
]

print("=== 環境變數檢查 ===")
for var in required_env_vars:
    value = os.environ.get(var)
    if value:
        # 隱藏敏感資訊
        if 'KEY' in var or 'PASSWORD' in var:
            print(f"✅ {var}: {'*' * 8} (已設定)")
        else:
            print(f"✅ {var}: {value}")
    else:
        print(f"❌ {var}: 未設定")

# 步驟 2：檢查憑證檔案是否存在
cert_path = os.environ.get('SHIOAJI_CERT_PATH')
if cert_path and os.path.exists(cert_path):
    print(f"\n✅ 憑證檔案存在：{cert_path}")
else:
    print(f"\n❌ 憑證檔案不存在：{cert_path}")
    print("請確認憑證路徑是否正確")
    exit(1)

# 步驟 3：嘗試連線並捕捉錯誤
try:
    acc = SinopacAccount()
    print("\n✅ 帳戶連線成功")

    # 驗證帳戶狀態
    print(f"✅ 現金餘額：NT$ {acc.get_cash():,.0f}")

except FileNotFoundError as e:
    print(f"\n❌ 憑證檔案錯誤：{e}")
    print("請檢查 SHIOAJI_CERT_PATH 是否正確")

except PermissionError as e:
    print(f"\n❌ 憑證權限錯誤：{e}")
    print("請確認憑證密碼是否正確（SHIOAJI_CERT_PASSWORD）")

except ConnectionError as e:
    print(f"\n❌ 網路連線錯誤：{e}")
    print("可能原因：")
    print("1. 網路連線不穩定")
    print("2. 券商 API 服務暫時無法使用")
    print("3. API KEY 或 SECRET KEY 錯誤")
    print("請稍後再試或聯繫券商客服")

except Exception as e:
    print(f"\n❌ 未知錯誤：{e}")
    print("請檢查所有環境變數是否正確設定")
```

</details>

<details><summary>玉山證券的檢查程式</summary>

```python
import os
from finlab.online.esun_account import EsunAccount

# 檢查玉山證券環境變數
required_vars = [
    'ESUN_CONFIG_PATH',
    'ESUN_MARKET_API_KEY',
    'ESUN_ACCOUNT_PASSWORD',
    'ESUN_CERT_PASSWORD',
]

for var in required_vars:
    if not os.environ.get(var):
        print(f"❌ {var} 未設定")
        print(
            f"   請參考：https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/quick-start/"
        )
        exit(1)

# 檢查 config.ini 是否存在
config_path = os.environ.get('ESUN_CONFIG_PATH')
if not os.path.exists(config_path):
    print(f"❌ Config 檔案不存在：{config_path}")
    exit(1)

try:
    acc = EsunAccount()
    print("✅ 玉山證券帳戶連線成功")
except Exception as e:
    print(f"❌ 連線失敗：{e}")
    print("請檢查 config.ini 內容是否正確")
```

</details>

### 錯誤 2：下單前安全檢查失敗

**現象**：資金不足、持倉過多或單股權重過高。

**原因**：

- 可用資金不足以買入 `position` 指定的股票
- 策略產生的持股數量超過風險限制
- 單一股票權重過高（未分散風險）

**解決方法**：下單前實施多層安全檢查：持倉數量、單股權重、可用資金，最後再檢查處置股。

<details><summary>下單前安全檢查的範例函式</summary>

```python
from finlab.online.order_executor import OrderExecutor, Position
from finlab.online.sinopac_account import SinopacAccount

def safe_order_check(
    position, account, max_stocks=50, max_weight=0.15, min_cash_buffer=0.1
):
    """
    下單前安全檢查函數

    Args:
        position: Position 物件
        account: 券商帳戶物件
        max_stocks: 最大持股數量（預設 50 檔）
        max_weight: 單股最大權重（預設 15%）
        min_cash_buffer: 最小現金緩衝比例（預設 10%）

    Raises:
        ValueError: 檢查不通過時拋出錯誤
    """
    print("=== 下單安全檢查 ===\n")

    # 以最新價格計算每檔目標持股的市值（台股一張 1,000 股）
    price = account.get_price([p['symbol'] for p in position])
    values = {
        p['symbol']: float(p['quantity']) * 1000 * price[p['symbol']] for p in position
    }
    total_value = sum(values.values())

    # 檢查 1：持倉數量
    print(f"持倉數量：{len(values)} 檔")
    if len(values) > max_stocks:
        raise ValueError(
            f"❌ 持倉過多（{len(values)} 檔），超過限制 {max_stocks} 檔\n"
            f"   建議：使用 .is_largest(N) 限制選股數量"
        )
    print(f"✅ 持倉數量檢查通過（<= {max_stocks} 檔）\n")

    # 檢查 2：單一持股權重
    for symbol, value in values.items():
        weight = value / total_value if total_value > 0 else 0
        print(f"  {symbol}: NT$ {value:,.0f} ({weight:.1%})")

        if weight > max_weight:
            raise ValueError(
                f"❌ 單股權重過高：{symbol} 佔 {weight:.1%}，超過限制 {max_weight:.0%}\n"
                f"   建議：使用 position_limit 參數限制單股權重"
            )

    print(f"\n✅ 單股權重檢查通過（<= {max_weight:.0%}）\n")

    # 檢查 3：可用資金
    available = account.get_total_balance()
    cash_buffer = available * min_cash_buffer
    print(f"帳戶淨值：NT$ {available:,.0f}，目標市值：NT$ {total_value:,.0f}")

    if total_value > (available - cash_buffer):
        raise ValueError(
            f"❌ 資金不足！\n"
            f"   帳戶淨值：NT$ {available:,.0f}\n"
            f"   目標市值：NT$ {total_value:,.0f}\n"
            f"   現金緩衝：NT$ {cash_buffer:,.0f}（保留 {min_cash_buffer:.0%}）\n"
            f"   建議：降低傳給 Position.from_report() 的 fund 或追加資金"
        )

    print(f"✅ 資金檢查通過（保留 {min_cash_buffer:.0%} 緩衝）\n")

    # 檢查 4：處置股/警示股
    print("⚠️  提醒：下單前請執行 order_executer.show_alerting_stocks() 檢查處置股\n")

    print("=" * 50)
    print("✅ 所有安全檢查通過，可以執行下單")
    print("=" * 50)

# 使用範例
try:
    acc = SinopacAccount()
    position = Position.from_report(report, fund=1000000)

    # 執行安全檢查
    safe_order_check(position, acc, max_stocks=30, max_weight=0.10)

    # 通過檢查後，執行下單
    order_executor = OrderExecutor(position, account=acc)

    # 先預覽（不會真的下單）
    print("\n=== 預覽訂單 ===")
    order_executor.create_orders(view_only=True)

    # 確認無誤後，執行下單
    # order_executor.create_orders()  # 取消註解以實際下單

except ValueError as e:
    print(f"\n{e}")
    print("\n請修正問題後再執行下單")

except Exception as e:
    print(f"\n❌ 未預期的錯誤：{e}")
    print("請聯繫技術支援或查看詳細錯誤訊息")
```

</details>

### 錯誤 3：訂單被拒絕

**現象**：執行 `create_orders()` 後，部分或全部訂單被券商拒絕：

```python
order_executor.create_orders()
# 訂單狀態：部分成功、部分失敗
```

**常見拒單原因**：

1. **處置股未圈存**
2. **股票暫停交易**
3. **漲跌停鎖死**
4. **零股交易時段錯誤**
5. **帳戶權限不足**

**解決方法**：先檢查處置股並圈存，確認在交易時段內，預覽後再下單，最後查看仍在委託中的訂單。

<details><summary>下單前檢查並逐筆確認的範例</summary>

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from finlab.online.order_executor import OrderExecutor

# 建立 OrderExecutor
order_executor = OrderExecutor(position, account=acc)

# 步驟 1：檢查處置股/警示股（結果直接印出，沒有回傳值）
print("=== 檢查處置股 ===")
order_executor.show_alerting_stocks()
print("若上面列出處置股/警示股，請至券商平台圈存後再下單")
# 等待用戶手動圈存後再繼續
input("圈存完成（或不需圈存）後，按 Enter 繼續...")

# 步驟 2：檢查交易時段（台北時間）
now = datetime.now(ZoneInfo('Asia/Taipei'))
minutes = now.hour * 60 + now.minute

if now.weekday() < 5 and 9 * 60 <= minutes <= 13 * 60 + 30:
    print("✅ 當前為交易時段（09:00-13:30）")
else:
    print("⚠️  當前為非交易時段")
    print("   整股交易時段：09:00-13:30")
    print("   零股交易時段：09:00-13:30（盤中）、13:40-14:30（盤後）")

# 步驟 3：先預覽，再下單
print("\n=== 預覽訂單 ===")
order_executor.create_orders(view_only=True)

confirmation = input("\n確認無誤後輸入 'YES' 執行下單：")
if confirmation == 'YES':
    try:
        order_executor.create_orders()

        # 步驟 4：查看仍在委託中的訂單
        print("\n=== 委託中的訂單 ===")
        for order_id, order in acc.get_orders().items():
            print(
                f"{order_id} {order.stock_id} {order.action.name} "
                f"{order.filled_quantity}/{order.quantity} {order.status.name}"
            )
    except Exception as e:
        print(f"\n❌ 下單失敗：{e}")
        print("請檢查券商的錯誤訊息、可用資金與交易時段")
else:
    print("已取消下單")
```

</details>

### 錯誤 4：零股下單失敗

**現象**：使用 `odd_lot=True` 但訂單失敗：

```python
position = Position.from_report(report, fund, odd_lot=True)
order_executor = OrderExecutor(position, account=acc)
order_executor.create_orders()
# 錯誤：零股交易時段不符
```

**原因**：

- 零股交易時段限制（盤中 09:00-13:30、盤後 13:40-14:30，台北時間）
- 部分券商不支援零股 API 交易
- 零股成交量不足

**解決方法**：在零股交易時段內下單，或改用整股交易（移除 `odd_lot=True`）。

<details><summary>檢查零股交易時段的範例</summary>

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from finlab.online.order_executor import OrderExecutor, Position

# 檢查是否在零股交易時段（台北時間）
now = datetime.now(ZoneInfo('Asia/Taipei'))
minutes = now.hour * 60 + now.minute

# 盤中零股：09:00-13:30
is_intraday_odd_lot = 9 * 60 <= minutes <= 13 * 60 + 30

# 盤後零股：13:40-14:30
is_afterhours_odd_lot = 13 * 60 + 40 <= minutes <= 14 * 60 + 30

if not (is_intraday_odd_lot or is_afterhours_odd_lot):
    print("⚠️  當前不在零股交易時段")
    print("   盤中零股：09:00-13:30")
    print("   盤後零股：13:40-14:30")
    print("\n建議：")
    print("1. 等待零股交易時段再下單")
    print("2. 改用整股交易（移除 odd_lot=True）")
else:
    # 建立零股部位
    position = Position.from_report(report, fund=500000, odd_lot=True)
    print("✅ 當前在零股交易時段，可執行下單")

    # 執行下單
    try:
        order_executor = OrderExecutor(position, account=acc)
        order_executor.create_orders(view_only=True)  # 先預覽
        # order_executor.create_orders()  # 確認後取消註解

    except Exception as e:
        print(f"❌ 零股下單失敗：{e}")
        print("\n可能原因：")
        print("1. 券商不支援零股 API 交易（請聯繫券商確認）")
        print("2. 零股成交量不足（建議改用整股）")
        print("3. 網路連線問題")
```

</details>

### 錯誤 5：有訊號但沒有下單

**現象**：策略有選股，但 `Position.from_report()` / `Position.from_weight()` 產生的部位是空的（或少了幾檔），`create_orders()` 沒有送出任何委託，並出現 `ZeroShareAllocationWarning`：

```text
ZeroShareAllocationWarning: 2 of 2 stocks with a non-zero target weight get 0 shares because their allocated fund cannot buy one board lot (1000 shares): 2330 (one lot 900,000 vs allocated 15,000), 1101 (one lot 40,000 vs allocated 15,000). The position is empty, so no orders will be placed. Use odd_lot=True to trade odd lots, or increase fund.
```

**原因**：`odd_lot=False`（預設）時只買整張，每檔股票分到的資金（`fund × 權重`）會無條件捨去成整張。分到的資金不足一張（`股價 × 1000`）的股票就是 0 股；全部都不足時部位就是空的。

**解決方法**：改用零股，或提高 `fund`。

```python
position = Position.from_report(report, fund=30000, odd_lot=True)
```

## 讓實盤穩定執行

### 先用模擬帳戶測試

大多數券商提供模擬帳戶，建議先測試 1-2 週，確認所有流程正常後再使用真實帳戶。

### 設定每日下單排程

```python
import time
from datetime import datetime

import schedule
from finlab.online.order_executor import OrderExecutor, Position

# acc 是前面建立的券商帳戶；safe_order_check 見上方錯誤 2

def daily_rebalance():
    """每日收盤後自動調倉"""
    try:
        # 1. 執行策略（你自己的函式，回傳 backtest.sim(...) 的報告）
        report = run_strategy()

        # 2. 計算部位
        position = Position.from_report(report, fund=1000000)

        # 3. 安全檢查
        safe_order_check(position, acc)

        # 4. 執行下單
        order_executor = OrderExecutor(position, account=acc)
        order_executor.create_orders()

        print(f"✅ {datetime.now()} - 下單完成")

    except Exception as e:
        print(f"❌ {datetime.now()} - 下單失敗：{e}")
        # 發送通知（LINE/Email）

# 每日 14:00 執行（13:30 收盤後；以電腦的時鐘為準，請設為台北時間）
schedule.every().day.at("14:00").do(daily_rebalance)

while True:
    schedule.run_pending()
    time.sleep(60)
```

### 記錄所有交易

```python
import json
from datetime import datetime

def log_trade(position, orders, status):
    """記錄交易日誌"""
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'position': position,
        'orders': orders,
        'status': status,
    }

    with open('trade_log.json', 'a') as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
```

## 上線前的檢查清單

**請務必在模擬帳戶充分測試後，才使用真實資金！** 建議測試清單：

- 帳戶連線穩定無錯誤
- 下單流程完整執行
- 持倉計算正確（與預期一致）
- 資金控制正常（不超支）
- 異常處理機制有效
- 連續運行 1-2 週無問題

**只有在以上項目全部確認後，才考慮使用真實資金！**

## 下一步

- [下單：多策略](order_api2.md) 多個策略組成投資組合，每天換算張數並同步帳戶。
- [finlab.online API](online.md) OrderExecutor 與 Position 的完整參數說明。
- [風險管理](https://studio.finlab.finance/docs/workflows/risk_management) 實盤的風險控制。
- [從研究到實盤](https://studio.finlab.finance/docs/workflows/complete_strategy_workflow) 從回測到實盤的完整流程。

更多疑難排解請看[常見問題 FAQ](https://studio.finlab.finance/docs/faq)。
