# finlab-online

Open-source broker connectors and order executor for [FinLab](https://finlab.finance) strategies: turn a strategy's positions into orders on your own brokerage account, from your own machine, with your own credentials.

FinLab 策略的開源下單套件：在自己的電腦、用自己的券商帳號，把策略部位轉成委託。

## Install

```bash
pip install finlab finlab-online
```

Code written for `finlab.online` keeps working unchanged: `from finlab.online import OrderExecutor` and the older paths such as `finlab.online.order_executor` and `finlab.online.sinopac_account` load this package, and so do `from finlab.portfolio import PortfolioSyncManager` and `TradeReview.from_account()`. The broker SDKs (for example `shioaji` for Sinopac) are installed separately, as before.

原本寫 `finlab.online`、`PortfolioSyncManager` 或 `TradeReview.from_account()` 的程式不用改，裝好這個套件就能照常執行。

## Supported Brokers

| Broker | Module | Realtime |
|--------|--------|----------|
| Fugle | `brokers.fugle` | Yes |
| Sinopac (Shioaji) | `brokers.sinopac` | Yes |
| Fubon | `brokers.fubon` | Yes |
| Taishin (formerly Masterlink) | `brokers.taishin` (alias of `brokers.masterlink`) | Yes |
| Schwab | `brokers.schwab` | No |
| Binance | `brokers.binance` | No |
| Pocket | `brokers.pocket` | No |
| E.SUN | `brokers.esun` | Yes (via Fugle) |

## Package Structure

```
finlab_online/
├── core/               # Abstract interfaces, position, executor, enums, realtime
├── brokers/            # Broker-specific Account implementations
├── portfolio/          # PortfolioSyncManager: keep a finlab Portfolio in sync with an account
├── dashboard.py        # Cloud-connected multi-strategy rebalancing engine
├── panel.py            # Jupyter notebook GUI for interactive order placement
└── tests/              # Unit and integration tests
```

## Usage

```python
from finlab.online import OrderExecutor, Position

# See https://doc.finlab.tw/details/order_api/ for full documentation.
```

## Testing

```bash
# Unit tests (fast, mocked)
pytest tests/unit/ -v

# Integration tests (requires broker credentials)
pytest tests/integration/ -v -s
```

See [tests/README.md](tests/README.md) for credential setup and details.

## Contributing

Contributions are welcome. All changes must pass the existing test suite.
