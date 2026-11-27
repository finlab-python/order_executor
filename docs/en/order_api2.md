# Orders: many strategies

This guide is for users with well-defined trading strategies who want to run several at once: combine them into one portfolio, work out the quantities the whole account should hold each day, and sync the account in one go. It covers four steps:

1. Execute trading strategies
2. Combine trading positions
3. Calculate share quantities
4. Place orders

With a single strategy, [Orders: one strategy](order_api.md) is simpler.

> [!WARNING]
> **This feature is in BETA**
>
> This feature already manages real capital, but for first-time use, please execute outside trading hours (after the close or before the open) to avoid unexpected errors during trading sessions.

## Get a report for each strategy

Before the next trading day opens, run your strategies and obtain their reports. Use any one of these three approaches:

**Your own backtest**

Write your own strategies following [Backtesting](https://studio.finlab.finance/en/docs/details/backtest) and get reports by backtesting:

```python
from finlab import backtest

# Write your strategies

report1 = backtest.sim(...)
report2 = backtest.sim(...)
```

This approach runs the complete code and may take some time.
**Strategies in Studio**

Select strategies from [Strategies](https://studio.finlab.finance/en/strategies) in FinLab Studio, note their names, and download the reports:

```python
from finlab.portfolio import create_report_from_cloud

report1 = create_report_from_cloud('NAME_OF_STRATEGY1')
report2 = create_report_from_cloud('NAME_OF_STRATEGY2')
```
**Set weights directly**

Suitable for users who already hold positions and want to rebalance periodically:

```python
from finlab import data
from finlab.portfolio import create_multi_asset_report

data.set_market('us')
report1 = create_multi_asset_report({'AAPL': 0.5, 'MSFT': 0.5}, resample='Q')
report2 = create_multi_asset_report({'AAPL': 0.7, 'MSFT': 0.3}, resample='M')
```

The `resample` parameter is the rebalancing frequency. For example, `Q` means quarterly rebalancing.

## Combine them into one portfolio

Give `Portfolio` each strategy's report and weight to simulate the combined performance:

```python
from finlab.portfolio import Portfolio

port = Portfolio({'strategy1': (report1, 0.5), 'strategy2': (report2, 0.5)})
port.display()
```

This simulates the combined portfolio and displays the same interactive report as a single backtest: cumulative return against the benchmark, risk and return metrics, and the holdings of every strategy.

When several strategies hold the same stock, its weight in the portfolio is each strategy's weight × its weight in that strategy, added up.

## Calculate share quantities

`PortfolioSyncManager` (the PM) turns the portfolio into quantities: shares for U.S. stocks, lots of 1,000 shares for Taiwan stocks. It can:

- Determine whether positions need updating
- On rebalancing days, recalculate the quantity of each stock
- After each trading day, check if stop-loss or take-profit needs to be triggered
- During rebalancing, ensure trading stays within the specified `total_balance`

> [!CAUTION]
> **One broker account, one PortfolioSyncManager**
>
> `sync()` treats the whole account as that PM's holdings, sells any position that is not in the target, and cancels the account's open orders before placing new ones. Combine multiple strategies into one `Portfolio` for a single PM; keep holdings you manage by hand in a separate account.

### Create or load the PortfolioSyncManager

Create a new PM the first time; after that, load the existing positions from the cloud or from local storage:

**First-time setup**

```python
from finlab.portfolio import PortfolioSyncManager

# Create a new database and save it, so later runs can load it
pm = PortfolioSyncManager()
pm.to_local()
```
**Load from cloud**

```python
from finlab.portfolio import PortfolioSyncManager

# Load existing positions from cloud
pm = PortfolioSyncManager.from_cloud()
```
**Load from local**

```python
from finlab.portfolio import PortfolioSyncManager

# Load existing positions from local storage
pm = PortfolioSyncManager.from_local()
```

### Update the holdings

Pass the portfolio and your total balance to `pm.update()`, in the way that fits your account:

**Rebalance only on scheduled dates**

```python
# The program will only rebalance on scheduled rebalancing dates.
# On first creation, positions will be empty.
pm.update(port, total_balance=100_000)
```
**Odd lots**

```python
# Odd lot trading (Taiwan)
pm.update(port, total_balance=1_000_000, odd_lot=True)
```
**Margin trading**

```python
# Margin / short selling
pm.update(port, total_balance=100_000, margin_trading=True)
```

Check the result:

```python
print(pm.get_position())
```

`get_position()` returns the combined target `Position`: one row per symbol with its quantity and order condition. For Taiwan portfolios, `print(pm)` also prints an estimated value and a holdings table priced with Taiwan market data (quantity, price, weight, close price, volume, the strategies holding each stock, and the order type).

Please run `PortfolioSyncManager.update` daily to ensure positions remain accurate.

### Save the positions

**Save to cloud**

```python
pm.to_cloud()
```
**Save to local**

```python
pm.to_local()
```

### A script to run every day

First-time setup:

```python
# Initialize PortfolioSyncManager
pm = PortfolioSyncManager()
pm.to_local()
```

Then run daily:

```python
# Initialize PortfolioSyncManager
pm = PortfolioSyncManager.from_local()

# Perform operations
# pm.update(...)

# Save results
pm.to_local()
```

> [!NOTE]
> **Adding or removing strategies**
>
> When using `pm.update` daily, you can pass different strategies and parameters. It will always update positions in the most reasonable way. To switch strategies immediately without waiting for the next rebalancing date, set `pm.update(..., smooth_transition=False)`.

<details><summary>PortfolioSyncManager.update parameters</summary>

`PortfolioSyncManager.update` has the following parameters. Please read carefully to ensure your position updates are correct:

**portfolio (Portfolio or Report)**

The portfolio containing investment positions. This is the core data structure for stock synchronization, and all share quantity calculations reference this portfolio.

**total_balance (float)**

A float value representing total assets, including all cash, assets, and stocks combined.

`total_balance` is supplied by the caller; the PM never reads it from the broker. On a rebalance, available funds are the smaller of `total_balance` minus the holdings' market value in sleeves not being updated and the updated sleeves' weighted budget, less the safety reserve.

When this update actually rebuilds a positive-weight sleeve and `total_balance` minus the holdings' market value in sleeves not being updated is <= `1e-6`, `update()` raises `finlab.exceptions.PortfolioError` before writing state or rebuilding positions. The absolute currency tolerance `1e-6`, far below 0.01, treats equality and small floating-point differences from decimal-price multiplication consistently as no usable capital. It does not scale with portfolio value. Daily calls with no rebuild, removal-only calls, and stop-loss/take-profit-only calls remain allowed when holdings appreciate above a fixed `total_balance`. An explicit zero budget with zero retained asset value keeps its previous behavior.

The error aborts the **entire** `update()`: no config/history writes, sleeve removals or rebuilds, and no stop-loss/take-profit processing in any sleeve, including other sleeves. Immediately raise `total_balance` according to the lower bound in the exception and retry `update()` before saving or calling `sync()`; do not catch the exception and sync the old target. For example, retained holdings worth 600000 require at least 600001 in whole currency units to pass this boundary check. Also budget enough for target securities and the safety reserve; the lower bound does not guarantee a tradable lot. Empty positions caused by a genuinely positive balance too small to buy one share are tracked separately in [Issue #296](https://github.com/finlab-python/finlab/issues/296). To let capital grow with the account, pass `account.get_total_balance()`.

**rebalance_safety_weight (float)**

The cash weight that ensures the total value of the new strategy portfolio does not exceed the original portfolio value when buying/selling at market prices. For example, if set to 20%, then 20% of sold assets will be retained as cash, and the rest will be used to purchase new assets. This helps manage investment risk and ensure liquidity. If using limit orders, this can be set to around 5%.

**smooth_transition (bool)**

Determines whether to use smooth transition for portfolio updates. When adding/removing strategies or updating weights, if set to True, the portfolio will not change immediately but will update at each strategy's next scheduled date. This avoids frequent trading, reduces transaction costs, and helps portfolio stability. Default is True.

**force_override_difference (bool)**

Determines whether to force override existing different positions. If it is not a rebalancing day and there is no stop-loss/take-profit trigger, the program will still verify whether current positions match simulated positions (they should theoretically match, but may differ due to delayed data registration, user forgetting to run the strategy, or running the strategy before data registration). If set to True, any detected differences will be forcibly adjusted according to the new strategy. Default is False to avoid unnecessary trading and potential risks.

These parameters are crucial for portfolio synchronization and rebalancing. Properly setting and understanding them helps investors achieve more effective asset management and risk control.

</details>

<details><summary>How update reallocates capital: steps and an example</summary>

The `update` function keeps the portfolio balanced and rebalances investments when necessary to follow strategy allocations.

**Steps**

1. **Identify strategies that need updating**
    - The function first checks which strategies need updating based on their next scheduled trading dates. If the next trading date has arrived or passed, or strategy weights have changed, an update is needed.
    - It also considers whether smooth transition is enabled, meaning updates will only occur on the next scheduled trading date to avoid immediate changes.
2. **Check current holdings**
    - The function checks the current stock holdings and confirms whether they match the strategy report. If there are discrepancies, warnings are logged and forced updates may occur.
3. **Calculate asset value and liquid funds**
    - **Total asset value**: Sum of all current holding values.
    - **Liquid funds**: Funds available from selling current positions of strategies due for rebalancing, plus remaining balance.
    - **Limited liquid funds**: Capped to not exceed total_balance * sum of strategy weights.
    - **Safety funds**: A percentage of liquid funds retained for stability (e.g., 20%).
    - **Investable funds**: Liquid funds minus safety funds.
4. **Update each strategy's holdings**
    - For each strategy needing update, funds are allocated based on strategy weight and investable funds.
    - Old holdings are liquidated and new holdings created. Stocks appearing in both old and new are retained.
    - Stocks triggering stop-loss/take-profit have positions set to zero without rebalancing the entire strategy.
5. **Save updated portfolio**
    - Updated portfolio information is saved locally or to the cloud.

**Example**

- **Initial setup**: Portfolio with strategies A and B, each weighted 50%.
- **Current value**: Total NAV is $1,000,000. Strategy A = $300,000, Strategy B = $600,000. Strategy A is lower due to stop-loss liquidations; Strategy B is higher due to gains.
- **Rebalancing condition**: Strategy B has a scheduled rebalancing tomorrow; A does not.

Update process:

1. Strategy B is identified for update.
2. Liquid funds from Strategy B: $600,000 + $100,000 remaining = $700,000, capped at $500,000 (50% weight).
3. Safety funds: $500,000 * 20% = $100,000.
4. Investable funds: $500,000 - $100,000 = $400,000.
5. Since idle funds ($200,000) exceed safety funds ($100,000), no safety reserve needed. Investable = $500,000.
6. Strategy B's $600,000 holdings are liquidated and $500,000 is reinvested per Strategy B.
7. Stop-loss/take-profit triggered stocks in Strategy A are set to zero without rebalancing B.

</details>

## Place orders and sync the account

### Connect your broker account

Connect the account of the broker you use: Charles Schwab for U.S. stocks, or E.SUN, SinoPac, Taishin (formerly Masterlink) or Fubon Securities for Taiwan stocks. Set the credentials as environment variables; you only need the broker you use.

**Charles Schwab**

For U.S. stocks.

1. Register an app on the [Schwab Developer Portal](https://developer.schwab.com/) to get an app key and secret.
2. Create a token file with the login flow of [schwab-py](https://schwab-py.readthedocs.io/) (`pip install schwab-py`); `SchwabAccount` reads that file.
3. Set the variables and connect:

```python
import os
from finlab.online.schwab_account import SchwabAccount

os.environ['SCHWAB_API_KEY'] = 'Schwab app key'
os.environ['SCHWAB_SECRET'] = 'Schwab app secret'
os.environ['SCHWAB_TOKEN_PATH'] = '/path/to/token.json'

account = SchwabAccount()
```
**E.SUN**

E.SUN Securities, for Taiwan stocks.

1. Follow the [config tutorial](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/quick-start/) to obtain the config file.
2. Log in to the [E.SUN Securities API](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/key/) to get the market data Token.
3. Set the variables and connect:

```python
from finlab.online.esun_account import EsunAccount
import os

os.environ['ESUN_CONFIG_PATH'] = 'path to config.ini.example'
os.environ['ESUN_MARKET_API_KEY'] = 'E.SUN market API Token'
os.environ['ESUN_ACCOUNT_PASSWORD'] = 'E.SUN account password'
os.environ['ESUN_CERT_PASSWORD'] = 'E.SUN certificate password'

account = EsunAccount()
```

<details><summary>Legacy Fugle environment variables (still supported)</summary>

```python
from finlab.online.fugle_account import FugleAccount
import os

os.environ['FUGLE_CONFIG_PATH'] = 'path to config.ini.example'
os.environ['FUGLE_MARKET_API_KEY'] = 'market API Token'
os.environ['FUGLE_ACCOUNT_PASSWORD'] = 'account password'
os.environ['FUGLE_CERT_PASSWORD'] = 'certificate password'

account = FugleAccount()
```

</details>

If you encounter error codes, check the [E.SUN Securities documentation](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/reference/error-code/).
**SinoPac**

SinoPac Securities, for Taiwan stocks.

1. Obtain the certificate (see SinoPac's [API key and certificate guide](https://sinotrade.github.io/tutor/prepare/token/)):
    - Click "Download certificate" on the [API management page](https://www.sinotrade.com.tw/newweb/PythonAPIKey/) of SinoPac's website. This works on Windows and macOS.
    - Or download it with eleader, which runs on Windows only.
2. Set the variables and connect:

```python
import os
from finlab.online.sinopac_account import SinopacAccount

os.environ['SHIOAJI_API_KEY'] = 'SinoPac API_KEY'
os.environ['SHIOAJI_SECRET_KEY'] = 'SinoPac SECRET_KEY'
os.environ['SHIOAJI_CERT_PERSON_ID'] = 'National ID number'
os.environ['SHIOAJI_CERT_PATH'] = 'SinoPac certificate path'
os.environ['SHIOAJI_CERT_PASSWORD'] = 'SinoPac certificate password'  # defaults to National ID

account = SinopacAccount()
```
**Taishin**

Taishin Securities (formerly Masterlink), for Taiwan stocks. Masterlink Securities merged into Taishin Securities on April 6, 2026. Full steps are in Taishin's [preparation guide](https://ml-fugle-api.tssco.com.tw/FugleSDK/docs/trading/prepare/):

1. **Sign**: sign the API risk disclosure online. It takes effect the next day.
2. **Certificate**: apply for and export a .pfx certificate with the certificate e-manager app described in the preparation guide; certificates from the certificate express service cannot be used with the API.
3. **Install**: download the wheel for your platform from [Taishin's SDK page](https://ml-fugle-api.tssco.com.tw/FugleSDK/docs/download/download-sdk/) and install it with `pip install taishin_sdk-<version>-cp37-abi3-<platform>.whl`. Python 3.8–3.12 is officially supported.
4. **Connect**:

```python
import os
from finlab.online.taishin_account import TaishinAccount

os.environ['TAISHIN_NATIONAL_ID'] = 'National ID number'
os.environ['TAISHIN_ACCOUNT'] = 'Branch code + account'  # first account if unset
os.environ['TAISHIN_ACCOUNT_PASS'] = 'Login password'
os.environ['TAISHIN_CERT_PATH'] = 'Path to the .pfx certificate'
os.environ['TAISHIN_CERT_PASS'] = 'Certificate password'

account = TaishinAccount()

# First time only: activate API trading (returns True), then delete this line
# account.sdk.register_api_auth(account.target_account)
```

<details><summary>Legacy Masterlink environment variables (still supported)</summary>

`MasterlinkAccount` (`finlab.online.masterlink_account`) and `TaishinAccount` are the same class; when `TAISHIN_*` is not set, the matching `MASTERLINK_*` variable is read, e.g. `MASTERLINK_NATIONAL_ID`. Existing code keeps working once `taishin_sdk` is installed.

</details>

**Fubon**

Fubon Securities, for Taiwan stocks. Refer to the [Fubon Securities tutorial](https://www.fbs.com.tw/TradeAPI/docs/trading/introduction/):

```python
import os
from finlab.online.fubon_account import FubonAccount

os.environ['FUBON_NATIONAL_ID'] = "A123456789"
os.environ['FUBON_ACCOUNT_PASS'] = "your_password"
os.environ['FUBON_CERT_PATH'] = "/path/to/cert.pfx"
os.environ['FUBON_CERT_PASS'] = "certificate password"  # optional: passed to the Fubon SDK at login
os.environ['FUBON_ACCOUNT'] = "account number"  # optional: use this account, error if not found; first stock account if unset
# os.environ['FUBON_BASE_URL'] = "connection URL"  # optional: passed to the Fubon SDK (FubonSDK)

account = FubonAccount()
```

`FUBON_NATIONAL_ID`, `FUBON_ACCOUNT_PASS` and `FUBON_CERT_PATH` are required; a missing one raises an error. The other three are optional.

### Sync the account

Preview with simulated orders first, then pick how orders are priced:

**Simulated orders**

```python
# Simulation only, no actual orders placed
pm.sync(account, view_only=True)
```
**Latest price orders**

```python
# Default: uses the latest transaction price as limit price
pm.sync(account)
```
**Market orders**

```python
# Market orders on Schwab; Taiwan brokers buy at the upper and sell at the
# lower price limit. Suitable for highly liquid stocks
pm.sync(account, market_order=True)
```
**Aggressive 1% limit orders**

```python
# Limit order at 1% above current price (easier to fill)
pm.sync(account, extra_bid_pct=0.01)
```
**Conservative 1% limit orders**

```python
# Limit order at 1% below current price (harder to fill)
pm.sync(account, extra_bid_pct=-0.01)
```

### Update the limit price or cancel orders

For orders that have not filled yet:

```python
# Update limit price
order_executor = pm.create_order_executor(account)
order_executor.update_order_price()

# Cancel all pending orders
order_executor.cancel_orders()
```

### Deposit in advance for restricted Taiwan stocks

For Taiwan stocks, positions in full-delivery, disposition or alert stocks require cash or shares deposited with the broker in advance; `order_executor.show_alerting_stocks()` (Taiwan market only) lists the pending orders affected.

## Next steps

- [Orders: one strategy](order_api.md) How Position and OrderExecutor work, and fixes for common order errors.
- [Multi-strategy portfolios](https://studio.finlab.finance/en/docs/workflows/multi_strategy_portfolio) Weight allocation, risk parity and rebalancing for a combined portfolio.
- [finlab.portfolio API](https://studio.finlab.finance/en/docs/reference/portfolio) Every Portfolio and PortfolioSyncManager parameter.
- [finlab.online API](online.md) Position, OrderExecutor and the broker account classes.
