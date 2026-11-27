# Orders: one strategy

This page turns one strategy into orders in your brokerage account: **backtest → share quantities → connect the broker → preview, then trade**. To run several strategies together, see [Orders: many strategies](order_api2.md).

Live order execution connects to **Charles Schwab** for U.S. stocks and to **E.SUN, SinoPac, Taishin (formerly Masterlink) and Fubon Securities** for Taiwan stocks. The position calculation works for any market; only the last step needs a supported broker.

> [!CAUTION]
> **Live trading uses real money**
>
> Errors can lead to financial losses. Before placing orders:
>
> 1. Run the full workflow with `view_only=True` for at least 1 week to preview the orders
> 2. Initial capital should not exceed **10-20%** of total funds
> 3. Monitor positions and order status daily
> 4. Set stop-loss mechanisms to avoid large single-trade losses

## From backtest to orders

### Install finlab-online

The order code lives in the open-source package `finlab-online`; install it next to finlab:

```bash
pip install finlab finlab-online
```

Code written for `finlab.online` keeps working unchanged.

### Run the strategy before the open

Run your strategy before the next trading day opens:

```python
from finlab import backtest, data

data.set_market('us')
with data.us_universe(index='SP500'):
    close = data.get('price:adj_close')

# Your own strategy goes here; this one holds the 20 strongest 6-month performers
position = (close / close.shift(126)).is_largest(20)
report = backtest.sim(position, resample='M')
```

A backtest reads each signal from data published by that day's close and trades on the next trading day. Live trading follows the same rhythm: work out the holdings before the next open.

| When | What | Detail |
|---|---|---|
| Day T, after the close | Data for day T is published | A row dated T holds only what was known by then. |
| Day T | The signal is read | `position` on day T says what to hold. |
| Next trading day | The trade fills | At `trade_at_price`, the close by default. |
| Until the next rebalance | Holdings stay | |

### Convert weights into share quantities

First check the current positions:

```python
print(report.current_trades)
```

`current_trades` lists the trades that are open or change at the latest signal date, with their entry and exit dates, return, MAE/MFE, the current target `weight` and the `next_weights` for the next rebalance.

Once they look right, calculate the quantity of each stock with `Position.from_report()`:

```python
from finlab.online.order_executor import Position

# total fund, in the market's currency (USD for U.S. stocks)
fund = 100_000
position = Position.from_report(report, fund)
print(position)
```

Each row lists a symbol, the quantity to hold, and the order condition (`CASH` for a regular cash position). For U.S. stocks the quantity is in **shares**; for Taiwan stocks it is in **lots of 1,000 shares**.

Each stock's allocation is floored to whole board lots, so a stock whose allocation is below one lot gets 0. To trade odd lots, set quantities by hand or combine strategies, see [Adjust the position](#adjust-the-position).

### Install the broker package and connect

Install the package of the broker you use and set its credentials as environment variables; configure only that broker.

#### Charles Schwab

For U.S. stocks.

1. Register an app on the [Schwab Developer Portal](https://developer.schwab.com/) to get an app key and secret.
2. Create a token file with the login flow of [schwab-py](https://schwab-py.readthedocs.io/); `SchwabAccount` reads that file.
3. Install the package, set the variables and connect:

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

#### E.SUN

E.SUN Securities, for Taiwan stocks.

1. Follow the [config tutorial](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/quick-start/) to obtain the config file.
2. Log in to the [E.SUN Securities API](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/key/) to get the market data Token.
3. Install the package, set the variables and connect:

```bash
pip install esun-trade
```

```python
from finlab.online.esun_account import EsunAccount
import os

os.environ['ESUN_CONFIG_PATH'] = 'path to config.ini.example'
os.environ['ESUN_MARKET_API_KEY'] = 'E.SUN market API Token'
os.environ['ESUN_ACCOUNT_PASSWORD'] = 'E.SUN account password'
os.environ['ESUN_CERT_PASSWORD'] = 'E.SUN certificate password'

acc = EsunAccount()
```

<details><summary>Legacy Fugle environment variables (still supported)</summary>

```python
from finlab.online.fugle_account import FugleAccount
import os

os.environ['FUGLE_CONFIG_PATH'] = 'path to config.ini.example'
os.environ['FUGLE_MARKET_API_KEY'] = 'market API Token'
os.environ['FUGLE_ACCOUNT_PASSWORD'] = 'account password'
os.environ['FUGLE_CERT_PASSWORD'] = 'certificate password'

acc = FugleAccount()
```

</details>

For error codes, see the [E.SUN Securities documentation](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/reference/error-code/). If you are new to the broker API, practice with the [broker's tutorial](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/quick-start/) first.

#### SinoPac

SinoPac Securities, for Taiwan stocks.

1. Obtain the certificate (see SinoPac's [API key and certificate guide](https://sinotrade.github.io/tutor/prepare/token/)):
    - Click "Download certificate" on the [API management page](https://www.sinotrade.com.tw/newweb/PythonAPIKey/) of SinoPac's website. This works on Windows and macOS.
    - Or download it with eleader, which runs on Windows only.
2. Install the package, set the variables and connect:

```bash
pip install shioaji
```

```python
import os
from finlab.online.sinopac_account import SinopacAccount

os.environ['SHIOAJI_API_KEY'] = 'SinoPac API_KEY'
os.environ['SHIOAJI_SECRET_KEY'] = 'SinoPac SECRET_KEY'
os.environ['SHIOAJI_CERT_PERSON_ID'] = 'National ID number'
os.environ['SHIOAJI_CERT_PATH'] = 'SinoPac certificate path'
os.environ['SHIOAJI_CERT_PASSWORD'] = (
    'SinoPac certificate password'  # defaults to National ID
)

acc = SinopacAccount()
```

If you are new to the broker API, practice with the [broker's tutorial](https://sinotrade.github.io/quickstart/) first.

#### Taishin

Taishin Securities (formerly Masterlink), for Taiwan stocks. Masterlink Securities merged into Taishin Securities on April 6, 2026. Full steps are in Taishin's [preparation guide](https://ml-fugle-api.tssco.com.tw/FugleSDK/docs/trading/prepare/):

1. **Sign**: sign the API risk disclosure online. It takes effect the next day.
2. **Certificate**: apply for and export a .pfx certificate with the certificate e-manager app described in the preparation guide; certificates from the certificate express service cannot be used with the API.
3. **Install**: `taishin_sdk` is not on PyPI. Download the wheel for your platform from [Taishin's SDK page](https://ml-fugle-api.tssco.com.tw/FugleSDK/docs/download/download-sdk) first, then install it. Python 3.8–3.12 is officially supported.

```bash
pip install taishin_sdk-<version>-cp37-abi3-<platform>.whl
```

4. **Connect**: set the variables and create the account:

```python
import os
from finlab.online.taishin_account import TaishinAccount

os.environ['TAISHIN_NATIONAL_ID'] = 'National ID number'
os.environ['TAISHIN_ACCOUNT'] = 'Branch code + account'  # first account if unset
os.environ['TAISHIN_ACCOUNT_PASS'] = 'Login password'
os.environ['TAISHIN_CERT_PATH'] = 'Path to the .pfx certificate'
os.environ['TAISHIN_CERT_PASS'] = 'Certificate password'

acc = TaishinAccount()

# First time only: activate API trading (returns True), then delete this line
# acc.sdk.register_api_auth(acc.target_account)
```

<details><summary>Legacy Masterlink environment variables (still supported)</summary>

`MasterlinkAccount` (`finlab.online.masterlink_account`) and `TaishinAccount` are the same class; when `TAISHIN_*` is not set, the matching `MASTERLINK_*` variable is read, e.g. `MASTERLINK_NATIONAL_ID`. Existing code keeps working once `taishin_sdk` is installed.

</details>

#### Fubon

Fubon Securities, for Taiwan stocks. Refer to the [Fubon Securities tutorial](https://www.fbs.com.tw/TradeAPI/docs/trading/introduction/) to obtain the certificate, place it in the appropriate path, install the required packages, and then run:

```python
import os
from finlab.online.fubon_account import FubonAccount

os.environ['FUBON_NATIONAL_ID'] = "A123456789"
os.environ['FUBON_ACCOUNT_PASS'] = "your_password"
os.environ['FUBON_CERT_PATH'] = "/path/to/cert.pfx"
os.environ['FUBON_CERT_PASS'] = "certificate password"  # optional: passed to the Fubon SDK at login
os.environ['FUBON_ACCOUNT'] = "account number"  # optional: use this account, error if not found; first stock account if unset
# os.environ['FUBON_BASE_URL'] = "connection URL"  # optional: passed to the Fubon SDK (FubonSDK)

acc = FubonAccount()
```

`FUBON_NATIONAL_ID`, `FUBON_ACCOUNT_PASS` and `FUBON_CERT_PATH` are required; a missing one raises an error. The other three are optional.

### Create the order executor

`OrderExecutor` compares the account's current holdings with the target `position` and places the orders that close the gap:

```python
from finlab.online.order_executor import OrderExecutor

# Order Executor
order_executer = OrderExecutor(position, account=acc)
```

For Taiwan stocks, positions in full-delivery, disposition or alert stocks require cash or shares deposited with the broker in advance. `order_executer.show_alerting_stocks()` (Taiwan market only) lists the pending orders affected.

### Preview, then place the orders

Preview first. View-only mode places no orders:

```python
order_executer.create_orders(view_only=True)
```

When the preview matches what you expect, place the orders. By default the latest transaction price is the limit price. For a first run, test while the market is closed.

```python
# Will actually place orders
order_executer.create_orders()
```

For orders that have not filled yet, either update the limit price (the latest transaction price becomes the new limit price):

```python
order_executer.update_order_price()
```

or cancel all pending orders:

```python
order_executer.cancel_orders()
```

## Adjust the position

`Position` objects can be built by hand and added or subtracted, so you can trade odd lots, set quantities yourself or combine strategies.

### Trade odd lots (Taiwan)

U.S. accounts already trade single shares. Taiwan accounts trade whole lots of 1,000 shares by default; to allow odd lots, add `odd_lot=True`:

```python
# Round lots
position = Position.from_report(report, fund)

# Odd lots
position = Position.from_report(report, fund, odd_lot=True)
```

### Set quantities yourself

Construct a `Position` directly:

```python
position = Position({'AAPL': 10, 'MSFT': 5})
```

In a U.S. account this means 10 shares of AAPL and 5 shares of MSFT, both bought with cash.

### Add or remove shares

`Position` objects support addition and subtraction:

```python
# Remove 10 shares of AAPL
new_position = position - Position({'AAPL': 10})
# Add 5 shares of MSFT
new_position = position + Position({'MSFT': 5})
```

### Combine several strategies

Add the positions together and hand the total to one `OrderExecutor`:

```python
from finlab import backtest
from finlab.online.order_executor import Position

report1 = backtest.sim(
    (close / close.shift(126)).is_largest(10), resample='M'
)  # 6-month momentum
report2 = backtest.sim(
    (close / close.shift(20)).is_smallest(10), resample='M'
)  # 1-month reversal

position1 = Position.from_report(report1, 50_000)  # Strategy fund: $50,000
position2 = Position.from_report(report2, 50_000)  # Strategy fund: $50,000

total_position = position1 + position2
```

To manage weights, rebalance dates and stops for several strategies every day, use `PortfolioSyncManager` from [Orders: many strategies](order_api2.md).

## Check the account's holdings

For any supported broker account, you can check positions as follows:

```python
from finlab.online.schwab_account import SchwabAccount

acc = SchwabAccount()
print(acc.get_position())
```

The result is a `Position` with one row per holding: symbol, quantity and order condition. Taiwan accounts work the same way, for example with `SinopacAccount()` or `EsunAccount()`.

## Common errors and solutions

### Error 1: Account connection failure

**Symptom**: `acc = SchwabAccount()` (or a Taiwan broker account) throws an error.

**Causes**:

- Environment variables not set (`SchwabAccount` raises `KeyError` for a missing variable)
- Token or certificate file does not exist, has expired, or the path is wrong
- Network connection issue or broker API service is down

**Solution**: check the environment variables, then the token or certificate file, then try to connect.

<details><summary>Charles Schwab check script</summary>

```python
import os
from finlab.online.schwab_account import SchwabAccount

# Step 1: Check if environment variables are set
# (Taiwan brokers use their own variables, e.g. SinoPac: SHIOAJI_API_KEY,
#  SHIOAJI_SECRET_KEY, SHIOAJI_CERT_PERSON_ID, SHIOAJI_CERT_PATH, SHIOAJI_CERT_PASSWORD)
required_env_vars = ['SCHWAB_API_KEY', 'SCHWAB_SECRET', 'SCHWAB_TOKEN_PATH']

print("=== Environment Variable Check ===")
missing = [var for var in required_env_vars if not os.environ.get(var)]
for var in required_env_vars:
    print(
        f"{'❌' if var in missing else '✅'} {var}: {'NOT SET' if var in missing else 'set'}"
    )
if missing:
    raise SystemExit("Set the missing variables first")

# Step 2: Check if the token file exists
token_path = os.environ['SCHWAB_TOKEN_PATH']
if not os.path.exists(token_path):
    raise SystemExit(
        f"Token file not found: {token_path}. Create it with schwab-py's login flow."
    )

# Step 3: Attempt connection and catch errors
try:
    acc = SchwabAccount()
    print("✅ Account connected successfully")
    print(f"✅ Cash balance: ${acc.get_cash():,.2f}")
except Exception as e:
    print(f"❌ Connection failed: {e}")
    print("Check the app key, secret and token file, then try again later")
```

</details>

<details><summary>E.SUN Securities (Taiwan) check script</summary>

```python
import os
from finlab.online.esun_account import EsunAccount

# Check E.SUN Securities environment variables
required_vars = [
    'ESUN_CONFIG_PATH',
    'ESUN_MARKET_API_KEY',
    'ESUN_ACCOUNT_PASSWORD',
    'ESUN_CERT_PASSWORD',
]

for var in required_vars:
    if not os.environ.get(var):
        print(f"❌ {var} is not set")
        print(
            f"   Reference: https://www.esunsec.com.tw/trading-platforms/api-trading/docs/trading/quick-start/"
        )
        exit(1)

# Check if config.ini exists
config_path = os.environ.get('ESUN_CONFIG_PATH')
if not os.path.exists(config_path):
    print(f"❌ Config file not found: {config_path}")
    exit(1)

try:
    acc = EsunAccount()
    print("✅ E.SUN Securities account connected successfully")
except Exception as e:
    print(f"❌ Connection failed: {e}")
    print("Please verify the contents of config.ini are correct")
```

</details>

### Error 2: Pre-order safety check failure

**Symptom**: Insufficient funds, too many holdings, or single stock weight too high.

**Causes**:

- Available funds insufficient to buy the stocks specified in `position`
- Number of holdings generated by the strategy exceeds risk limits
- Single stock weight too high (risk not diversified)

**Solution**: run layered safety checks before placing orders: number of holdings, weight per stock, then available funds.

<details><summary>Pre-order safety check function</summary>

```python
from finlab.online.order_executor import OrderExecutor, Position
from finlab.online.schwab_account import SchwabAccount

def safe_order_check(
    position, account, max_stocks=50, max_weight=0.15, min_cash_buffer=0.1
):
    """
    Pre-order safety check function

    Args:
        position: Position object
        account: Broker account object
        max_stocks: Maximum number of holdings (default 50)
        max_weight: Maximum weight per stock (default 15%)
        min_cash_buffer: Minimum cash buffer ratio (default 10%)

    Raises:
        ValueError: Raised when any check fails
    """
    print("=== Pre-Order Safety Check ===\n")

    # Market value of each target holding at the latest price
    # (for Taiwan accounts, multiply by 1,000 shares per lot)
    price = account.get_price([p['symbol'] for p in position])
    values = {p['symbol']: float(p['quantity']) * price[p['symbol']] for p in position}
    total_value = sum(values.values())

    # Check 1: Number of holdings
    print(f"Number of holdings: {len(values)}")
    if len(values) > max_stocks:
        raise ValueError(
            f"❌ Too many holdings ({len(values)}), exceeds limit of {max_stocks}\n"
            f"   Suggestion: use .is_largest(N) to limit the number of selected stocks"
        )
    print(f"✅ Holdings count check passed (<= {max_stocks})\n")

    # Check 2: Single stock weight
    for symbol, value in values.items():
        weight = value / total_value if total_value > 0 else 0
        print(f"  {symbol}: ${value:,.0f} ({weight:.1%})")

        if weight > max_weight:
            raise ValueError(
                f"❌ Single stock weight too high: {symbol} accounts for {weight:.1%}, exceeds limit {max_weight:.0%}\n"
                f"   Suggestion: use the position_limit parameter to cap single stock weight"
            )

    print(f"\n✅ Single stock weight check passed (<= {max_weight:.0%})\n")

    # Check 3: Available funds
    available = account.get_total_balance()
    cash_buffer = available * min_cash_buffer
    print(f"Account value: ${available:,.0f}, target value: ${total_value:,.0f}")

    if total_value > (available - cash_buffer):
        raise ValueError(
            f"❌ Insufficient funds!\n"
            f"   Account value: ${available:,.0f}\n"
            f"   Target value: ${total_value:,.0f}\n"
            f"   Cash buffer: ${cash_buffer:,.0f} (reserve {min_cash_buffer:.0%})\n"
            f"   Suggestion: lower the fund passed to Position.from_report() or add more funds"
        )

    print(f"✅ Funds check passed (reserving {min_cash_buffer:.0%} buffer)\n")
    print("=" * 50)
    print("✅ All safety checks passed, ready to place orders")
    print("=" * 50)

# Usage example
try:
    acc = SchwabAccount()
    position = Position.from_report(report, fund=100_000)

    # Run the safety check
    safe_order_check(position, acc, max_stocks=30, max_weight=0.10)

    # After passing the check, execute orders
    order_executor = OrderExecutor(position, account=acc)

    # Preview first (no actual orders)
    print("\n=== Preview Orders ===")
    order_executor.create_orders(view_only=True)

    # After confirmation, execute orders
    # order_executor.create_orders()  # Uncomment to actually place orders

except ValueError as e:
    print(f"\n{e}")
    print("\nPlease fix the issue before placing orders")
```

</details>

### Error 3: Orders rejected

**Symptom**: After executing `create_orders()`, some or all orders are rejected by the broker.

**Common rejection reasons**:

1. **Market closed**: regular U.S. trading hours are 09:30-16:00 New York time
2. **Insufficient buying power**
3. **Symbol halted or not tradable through the API**
4. **Insufficient account permissions** (for example margin or short selling)
5. **Taiwan market only**: disposition stocks without advance deposits, prices locked at the daily limit, or odd-lot orders outside the odd-lot session

**Solution**: check the trading session, preview, confirm, then review the orders that are still open.

<details><summary>Session check and order review script</summary>

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from finlab.online.order_executor import OrderExecutor

order_executor = OrderExecutor(position, account=acc)

# Step 1: Check the trading session (U.S. regular hours, New York time)
now = datetime.now(ZoneInfo('America/New_York'))
if now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 0):
    print("✅ Currently in the regular trading session (09:30-16:00 ET)")
else:
    print("⚠️  Currently outside the regular trading session (09:30-16:00 ET)")

# Step 2: Preview first, then place orders
print("\n=== Preview Orders ===")
order_executor.create_orders(view_only=True)

confirmation = input("\nAfter confirming, type 'YES' to place orders: ")
if confirmation == 'YES':
    try:
        order_executor.create_orders()

        # Step 3: Check the orders that are still open
        print("\n=== Open Orders ===")
        for order_id, order in acc.get_orders().items():
            print(
                f"{order_id} {order.stock_id} {order.action.name} "
                f"{order.filled_quantity}/{order.quantity} {order.status.name}"
            )
    except Exception as e:
        print(f"\n❌ Order placement failed: {e}")
        print(
            "Check the broker's error message, your buying power and the trading session"
        )
else:
    print("Order placement cancelled")
```

</details>

### Error 4: Odd lot order failure (Taiwan)

**Symptom**: Using `odd_lot=True` with a Taiwan account but orders fail:

```python
position = Position.from_report(report, fund, odd_lot=True)
order_executor = OrderExecutor(position, account=acc)
order_executor.create_orders()
# Error: odd lot trading session mismatch
```

**Causes**:

- Odd-lot trading hours in Taiwan (intraday: 09:00-13:30, after-hours: 13:40-14:30, Taiwan time)
- Some brokers do not support odd lot API trading
- Insufficient odd lot trading volume

**Solution**: wait for an odd-lot session, or switch to round-lot trading (remove `odd_lot=True`).

<details><summary>Odd-lot session check script</summary>

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from finlab.online.order_executor import OrderExecutor, Position

now = datetime.now(ZoneInfo('Asia/Taipei'))
minutes = now.hour * 60 + now.minute

is_intraday_odd_lot = 9 * 60 <= minutes <= 13 * 60 + 30
is_afterhours_odd_lot = 13 * 60 + 40 <= minutes <= 14 * 60 + 30

if not (is_intraday_odd_lot or is_afterhours_odd_lot):
    print("⚠️  Currently outside odd lot trading sessions")
    print(
        "Wait for an odd lot session, or switch to round-lot trading (remove odd_lot=True)"
    )
else:
    position = Position.from_report(report, fund=500_000, odd_lot=True)
    order_executor = OrderExecutor(position, account=acc)
    order_executor.create_orders(view_only=True)  # Preview first
    # order_executor.create_orders()  # Uncomment after confirmation
```

</details>

### Error 5: Signal but no orders

**Symptom**: The strategy selects stocks, but the position from `Position.from_report()` / `Position.from_weight()` is empty (or missing some stocks), `create_orders()` places nothing, and a `ZeroShareAllocationWarning` is shown:

```text
ZeroShareAllocationWarning: 2 of 2 stocks with a non-zero target weight get 0 shares because their allocated fund cannot buy one board lot (1 shares): <symbol> (one lot <price> vs allocated <amount>), ... The position is empty, so no orders will be placed. Use odd_lot=True to trade odd lots, or increase fund.
```

**Cause**: Each stock's allocated fund (`fund × weight`) is floored to whole board lots. A U.S. board lot is one share, so a stock whose allocation is below its share price gets 0 shares. A Taiwan board lot is 1,000 shares (`price × 1000`) unless `odd_lot=True`. If every stock falls short, the position is empty.

**Solution**: Increase `fund` or hold fewer stocks. For Taiwan accounts, you can also trade odd lots:

```python
position = Position.from_report(report, fund=30_000, odd_lot=True)
```

## Run it reliably

### Preview before trading

Run the whole workflow daily with `create_orders(view_only=True)` for 1-2 weeks, and confirm the printed orders match your expectations before using real funds.

### Schedule a daily run

```python
import time
from datetime import datetime

import schedule

def daily_rebalance():
    """Rebalance once a day"""
    try:
        # 1. Run strategy (your own function returning backtest.sim(...))
        report = run_strategy()

        # 2. Calculate positions
        position = Position.from_report(report, fund=100_000)

        # 3. Execute orders
        order_executor = OrderExecutor(position, account=acc)
        order_executor.create_orders()

        print(f"{datetime.now()} - Orders completed")

    except Exception as e:
        print(f"{datetime.now()} - Order failed: {e}")
        # Send notification (Email, chat webhook)

# Run daily at 15:30, 30 minutes before the 16:00 U.S. close (machine clock on New York time)
schedule.every().day.at("15:30").do(daily_rebalance)

while True:
    schedule.run_pending()
    time.sleep(60)
```

### Log every trade

```python
import json
from datetime import datetime

def log_trade(position, orders, status):
    """Record trade log"""
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'position': position,
        'orders': orders,
        'status': status,
    }

    with open('trade_log.json', 'a') as f:
        f.write(json.dumps(log_entry, default=str) + '\n')
```

## Checklist before going live

**Always preview orders and start small before using real funds!** Recommended testing checklist:

- Account connection is stable and error-free
- Order workflow executes completely
- Position calculations are correct (match expectations)
- Capital controls work normally (no overspending)
- Exception handling mechanisms are effective
- Runs continuously for 1-2 weeks without issues

**Only consider using real funds after all items above are confirmed!**

## Next steps

- [Orders: many strategies](order_api2.md) Combine strategies into one portfolio and sync the account daily.
- [finlab.online API](online.md) Every OrderExecutor and Position parameter.
- [Risk management](https://studio.finlab.finance/en/docs/workflows/risk_management) Risk controls for live trading.
- [From research to live trading](https://studio.finlab.finance/en/docs/workflows/complete_strategy_workflow) The full workflow from backtest to live trading.

For more troubleshooting, see the [FAQ](https://studio.finlab.finance/en/docs/faq).
