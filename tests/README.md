# 測試說明文件

本專案提供完整的測試架構，涵蓋單元測試和整合測試，確保交易系統的穩定性和可靠性。

## 📁 測試目錄結構

```
tests/
├── README.md                          # 本文件
├── conftest.py                        # pytest 全域配置
├── test_config.py                     # 測試配置和環境變數管理
├── unit/                              # 單元測試（快速，使用 mock）
│   ├── __init__.py
│   ├── test_fubon_account_unit.py     # 富邦帳戶單元測試
│   ├── test_order_executor_unit.py    # OrderExecutor 單元測試
│   ├── test_position_utilities.py     # Position 與權重配置測試
│   └── test_calculate_price_with_extra_bid.py  # 加減價測試
├── integration/                       # 整合測試（需要真實 API 憑證）
│   ├── __init__.py
│   ├── real_order_helpers.py          # 真實下單流程共用 helper
│   ├── test_fubon_account_integration.py  # 富邦帳戶整合測試
│   ├── test_real_order_accounts.py    # 永豐/玉山真實下單流程測試
│   └── test_position_from_report.py   # from_report 策略整合測試
├── fixtures/                          # 測試數據和 mock 物件
│   ├── __init__.py
│   ├── fubon_sdk_responses.py         # 富邦 SDK 標準回應格式
│   ├── fubon_test_data.py             # 富邦測試數據
│   └── fubon_mocks.py                 # 富邦 SDK mock 物件
└── utils/                             # 測試工具
    ├── __init__.py
    ├── test_base.py                   # 測試基礎類
    └── mock_helpers.py                # Mock 輔助函數
```

## 🚀 快速開始

### 1. 檢查測試環境
```bash
python run_tests.py --env-check
```

### 2. 運行單元測試（推薦開始）
```bash
# 運行所有單元測試
python run_tests.py --unit

# 運行富邦帳戶單元測試
python run_tests.py --fubon unit

# 運行 Position/價格工具單元測試
python -m pytest tests/unit/test_position_utilities.py tests/unit/test_calculate_price_with_extra_bid.py -v
```

### 3. 運行整合測試（需要憑證）
```bash
# 運行富邦帳戶整合測試
python run_tests.py --fubon integration

# 運行真實券商下單流程測試（需券商憑證）
python -m pytest tests/integration/test_real_order_accounts.py -v -s
```

## 🧪 測試類型說明

### 單元測試 (Unit Tests)
- **位置**: `tests/unit/`
- **特點**: 快速執行（< 1秒），使用 mock，無外部依賴
- **目的**: 測試核心邏輯和數據處理
- **運行**: `python run_tests.py --unit`

**測試內容**：
- 數據解析邏輯（時間、狀態、數量轉換）
- API 回應映射（BSAction → Action，OrderType → OrderCondition）
- 錯誤處理機制
- 邊緣案例處理

### 整合測試 (Integration Tests)
- **位置**: `tests/integration/`
- **特點**: 使用真實 API，需要有效憑證
- **目的**: 測試完整工作流程和 API 整合
- **運行**: `python run_tests.py --integration`

**測試內容**：
- 帳戶登入和初始化
- 餘額和持倉查詢
- 股票報價查詢
- 委託單操作（建立、更新、取消）
- OrderExecutor 整合功能

## 🔑 環境設定

### 富邦證券測試憑證
```bash
export FUBON_NATIONAL_ID="你的身分證字號"
export FUBON_ACCOUNT_PASS="你的登入密碼"
export FUBON_CERT_PATH="/path/to/your/cert.pfx"

# 可選設定
export FUBON_CERT_PASS="憑證密碼"
export FUBON_ACCOUNT="特定帳號"
export FUBON_BASE_URL="API基地址"
```

### 檢查環境設定
```bash
python run_tests.py --env-check
```
會顯示：
```
富邦證券測試環境: ✅ 已配置 / ❌ 未配置
測試目錄: ✅ 存在
```

## 🎯 常用測試命令

### 基本測試執行
```bash
# 運行所有測試
python run_tests.py --all

# 運行單元測試
python run_tests.py --unit

# 運行整合測試
python run_tests.py --integration
```

### 富邦帳戶專用測試
```bash
# 富邦單元測試
python run_tests.py --fubon unit

# 富邦整合測試
python run_tests.py --fubon integration

# 富邦所有測試
python run_tests.py --fubon all
```

### 特定測試執行
```bash
# 運行特定測試檔案
python run_tests.py --test tests/unit/test_fubon_account_unit.py

# 運行特定測試方法
python run_tests.py --test tests/integration/test_fubon_account_integration.py::TestFubonAccountIntegration::test_get_cash

# 使用關鍵字過濾
python run_tests.py --unit --filter "parse_order"
```

### 顯示詳細日誌
```bash
# 單元測試不需要日誌，但整合測試建議加上 -s 參數
python -m pytest tests/integration/test_fubon_account_integration.py::TestFubonAccountIntegration::test_get_cash -v -s
```

## 📊 測試覆蓋範圍

### 富邦帳戶單元測試 (25 測試案例)
| 測試類別 | 測試內容 | 案例數 |
|---------|---------|--------|
| 帳戶初始化 | 成功/失敗/憑證缺失 | 3 |
| 數據解析 | 狀態/時間/數量/買賣別/委託條件 | 12 |
| 股票數據 | 價格提取/委買委賣/Stock 物件創建 | 6 |
| 錯誤處理 | 異常處理裝飾器/API 失敗 | 3 |
| Order 創建 | finlab Order 物件轉換 | 1 |

### 富邦帳戶整合測試
| 測試類別 | 測試內容 |
|---------|---------|
| 基本功能 | 帳戶初始化、餘額查詢、持倉查詢 |
| 市場數據 | 股票報價、委託單查詢 |
| 委託操作 | 建立/取消/更新委託單、零股交易 |
| OrderExecutor | 多股票組合、價格更新、當沖交易 |
| 安全測試 | 錯誤情境、餘額一致性 |

## ⚠️ 重要注意事項

### 整合測試安全提醒
1. **會使用真實 API**：整合測試連接真實的富邦證券 API
2. **可能創建委託單**：某些測試會創建真實委託單（但設計為低價避免成交）
3. **自動清理**：測試完成後會自動取消所有委託單
4. **建議環境**：建議在測試環境或小額帳戶中運行

### 測試設計原則
- **單元測試**：快速、隔離、無副作用
- **整合測試**：真實、完整、有清理機制
- **錯誤處理**：涵蓋各種異常情況
- **日誌記錄**：提供詳細的執行信息

## 🔧 故障排除

### 常見問題

#### 1. 單元測試失敗
```bash
# 檢查依賴
pip install pytest unittest-mock

# 檢查路徑
python -c "import sys; print(sys.path)"
```

#### 2. 整合測試跳過
```bash
# 檢查環境變數
python run_tests.py --env-check

# 設定憑證
export FUBON_NATIONAL_ID="A123456789"
# ... 其他環境變數
```

#### 3. API 連線問題
- 檢查網路連線
- 確認憑證檔案路徑正確
- 檢查富邦證券 API 服務狀態

#### 4. 委託單相關錯誤
- 確認帳戶有足夠餘額
- 檢查市場開放時間
- 確認股票代碼有效

### 日誌級別設定
- **INFO**: 一般操作資訊（預設）
- **DEBUG**: 詳細調試資訊
- **WARNING**: 警告訊息
- **ERROR**: 錯誤訊息

## 🚧 未來擴展

目前測試架構主要針對富邦證券，但設計為可擴展：

```
tests/
├── unit/
│   ├── test_fubon_account_unit.py     ✅ 已完成
│   ├── test_masterlink_account_unit.py  🚧 計劃中
│   └── test_fugle_account_unit.py       🚧 計劃中
├── fixtures/
│   ├── fubon/                         ✅ 已完成
│   ├── masterlink/                    🚧 計劃中
│   └── fugle/                         🚧 計劃中
```

## 📞 支援

如有測試相關問題，可以：
1. 檢查本文件的故障排除章節
2. 運行 `python run_tests.py --env-check` 檢查環境
3. 查看測試日誌輸出獲取詳細錯誤信息

---

**祝測試順利！** 🎉
