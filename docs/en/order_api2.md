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

### Your own backtest

Write your own strategies following [Backtesting](https://studio.finlab.finance/en/docs/details/backtest) and get reports by backtesting:

```python
from finlab import backtest

# Write your strategies

report1 = backtest.sim(...)
report2 = backtest.sim(...)
```

This approach runs the complete code and may take some time.

### Strategies in Studio

Select strategies from [Strategies](https://studio.finlab.finance/en/strategies) in FinLab Studio, note their names, and download the reports:

```python
from finlab.portfolio import create_report_from_cloud

report1 = create_report_from_cloud('NAME_OF_STRATEGY1')
report2 = create_report_from_cloud('NAME_OF_STRATEGY2')
```

### Set weights directly

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

Create a new PM the first time:

```python
from finlab.portfolio import PortfolioSyncManager

# Create a new database and save it, so later runs can load it
pm = PortfolioSyncManager()
pm.to_local()
```

After that, load the existing positions from local storage or from the cloud:

```python
from finlab.portfolio import PortfolioSyncManager

# Load existing positions from local storage
pm = PortfolioSyncManager.from_local()
# or from cloud
# pm = PortfolioSyncManager.from_cloud()
```

### Update the holdings

Pass the portfolio and your total balance to `pm.update()`, in the way that fits your account (pick one):

```python
# The program will only rebalance on scheduled rebalancing dates.
# On first creation, positions will be empty.
pm.update(port, total_balance=100_000)

# Or odd lot trading (Taiwan)
# pm.update(port, total_balance=1_000_000, odd_lot=True)

# Or margin / short selling
# pm.update(port, total_balance=100_000, margin_trading=True)
```

Check the result:

```python
print(pm.get_position())
```

`get_position()` returns the combined target `Position`: one row per symbol with its quantity and order condition. For Taiwan portfolios, `print(pm)` also prints an estimated value and a holdings table priced with Taiwan market data (quantity, price, weight, close price, volume, the strategies holding each stock, and the order type).

Please run `PortfolioSyncManager.update` daily to ensure positions remain accurate.

### A script to run every day

After the first-time setup in [Create or load the PortfolioSyncManager](#create-or-load-the-portfoliosyncmanager), run this every day: load the PM, update it, sync the account, and save the positions to the cloud or to local storage (the same place you load them from):

```python
from finlab.online.schwab_account import SchwabAccount
from finlab.portfolio import PortfolioSyncManager

# Load the positions saved by the previous run
pm = PortfolioSyncManager.from_local()
# or from the cloud
# pm = PortfolioSyncManager.from_cloud()

# port: today's Portfolio, built as in "Combine them into one portfolio" above
pm.update(port, total_balance=100_000)

# Your broker account, set up as in "Connect your broker account" below
account = SchwabAccount()
pm.sync(account)

# Save the positions for the next run
pm.to_local()
# or to the cloud
# pm.to_cloud()
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

Supported brokers are Charles Schwab for U.S. stocks and E.SUN, SinoPac, Taishin (formerly Masterlink) and Fubon Securities for Taiwan stocks. Setup is identical to a single strategy: install the broker package, set its credentials as environment variables and create the account, as described in [Orders: one strategy](order_api.md#install-the-broker-package-and-connect). The examples there name the account object `acc`; this page calls it `account`. For example, with Charles Schwab, once its environment variables are set:

```python
from finlab.online.schwab_account import SchwabAccount

account = SchwabAccount()
```

### Sync the account

Preview with simulated orders first:

```python
# Simulation only, no actual orders placed
pm.sync(account, view_only=True)
```

Then pick how orders are priced:

```python
# Latest price orders (default): uses the latest transaction price as limit price
pm.sync(account)

# Or market orders on Schwab; Taiwan brokers buy at the upper and sell at the
# lower price limit. Suitable for highly liquid stocks
# pm.sync(account, market_order=True)

# Or an aggressive limit order at 1% above current price (easier to fill)
# pm.sync(account, extra_bid_pct=0.01)

# Or a conservative limit order at 1% below current price (harder to fill)
# pm.sync(account, extra_bid_pct=-0.01)
```

### Update the limit price or cancel orders

For orders that have not filled yet, get an order executor from the PM, then either update the limit price or cancel the orders (pick one):

```python
order_executor = pm.create_order_executor(account)

# Update limit price
order_executor.update_order_price()

# Or cancel all pending orders
# order_executor.cancel_orders()
```

### Deposit in advance for restricted Taiwan stocks

For Taiwan stocks, positions in full-delivery, disposition or alert stocks require cash or shares deposited with the broker in advance; `order_executor.show_alerting_stocks()` (Taiwan market only) lists the pending orders affected.

## Next steps

- [Orders: one strategy](order_api.md) How Position and OrderExecutor work, and fixes for common order errors.
- [Multi-strategy portfolios](https://studio.finlab.finance/en/docs/workflows/multi_strategy_portfolio) Weight allocation, risk parity and rebalancing for a combined portfolio.
- [finlab.portfolio API](https://studio.finlab.finance/en/docs/reference/portfolio) Every Portfolio and PortfolioSyncManager parameter.
- [finlab.online API](online.md) Position, OrderExecutor and the broker account classes.
