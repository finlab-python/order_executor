# Real-trade review straight from a broker account

With `finlab-online` connected to your broker account, `TradeReview.from_account()` pulls the fills from the broker and rebuilds daily holdings and net value. `TradeReview` itself lives in the finlab package (`finlab.portfolio`); reviewing exported fills, how returns are computed, and viewing and saving the report in Studio are covered in the FinLab docs page [Real-Trade Review](https://studio.finlab.finance/en/docs/workflows/trade_review).

For setting up the broker account, see [Orders: one strategy](order_api.md).

## Review straight from a broker account

### Connect the broker account

This example uses Charles Schwab. Taiwan brokers and Binance are supported too; see the table below.

```python
from finlab.online.schwab_account import SchwabAccount

acc = SchwabAccount()
```

### Build the review

```python
from finlab.portfolio import TradeReview

review = TradeReview.from_account(acc, start="2026-01-01")
```

`from_account` does four things:

1. Pulls fills from `start` to today through the broker API (see the table below).
2. Rebuilds starting holdings from the broker's **current holdings** (undoing fills, stock dividends and splits in the window), then reconciles the rebuilt ending holdings with the broker; mismatches are listed in `review.limitations`.
3. Applies dividends: Schwab and Binance report them in the account records; for Taiwan accounts FinLab applies its dividend announcements automatically (cash dividends on the ex-dividend date, stock dividends and ETF splits on the ex-rights / resumption date).
4. Values holdings daily at unadjusted close.

### Read the limitations first

```python
review.limitations  # data limitations of this review: always read them
```

Reconciliation mismatches and skipped short-sale or securities-lending fills are listed here. Read them before you trust the numbers that follow.

### Read the results

```python
review.summary()  # start/end NAV, net inflow, dividends, fees and tax, P&L, TWR
review.daily  # daily cash, market value, NAV, flows, return, cumulative P&L
review.holdings  # shares held at each close
review.trades  # FIFO-matched round trips (with dividends); open lots have no exit_date
review.report.display()  # FinLab report: equity curve, metrics, MAE/MFE, trades
```

### Compare with strategy targets

`compare` uses the actual position at the close of each target date, never later fills. Targets can be share counts or weights:

```python
import pandas as pd

target = pd.DataFrame({"AAPL": [20], "MSFT": [10]}, index=["2026-03-02"])
review.compare(target)  # date, stock_id, target, actual, diff (shares)

weights = pd.DataFrame({"AAPL": [0.6], "MSFT": [0.4]}, index=["2026-03-02"])
review.compare(weights, kind="weight")  # or compare weights
```

## Broker support

| Broker | Fill source | Fees / tax | Closed positions | Dividends | Deposits / withdrawals | Default mode |
|---|---|---|---|---|---|---|
| Schwab (U.S.) | `get_transactions` | net amount minus gross | yes | broker records | broker records | account |
| Sinopac (Taiwan) | realized P&L + detail, open lot detail | buys from detail; sells derived from realized P&L (combined in fee) | buy legs recovered | FinLab auto | none | holdings |
| Pocket (Taiwan) | realized P&L, open lot detail | none | as Sinopac when the SDK has the detail call; otherwise shares sold in the window are treated as held at start | FinLab auto | none | holdings |
| Fubon (Taiwan) | `filled_history` (30 days per call, fubon_neo 2.1.1+) | not in API; estimated from `fee_ratio` and statutory tax | yes | FinLab auto | none | holdings |
| Taishin, formerly Masterlink (Taiwan) | statement `account_statment` | actual per fill | yes | FinLab auto | none | holdings |
| E.SUN (Taiwan) | `get_transactions_by_date` (180 days per call) | actual per fill | yes | FinLab auto | none | holdings |
| Binance | `myTrades` (per symbol) | paid in quote or base asset; BNB-paid fees are not counted | only currently held assets and those passed in `symbols=` | quote-asset distributions | quote-asset deposits/withdrawals | account |

Limitations that apply to every broker:

- Only **long** cash and margin positions are reviewed; short-sale and securities-lending fills are skipped and listed in `limitations`. Margin interest is not counted.
- Fills that only have a date (most Taiwan brokers) are processed buys first, then sells, on the same day, which does not affect end-of-day valuation.
- Corporate actions the broker or FinLab does not supply are not applied automatically; add them to `corporate_actions` (columns `stock_id, date, cash, ratio`). Taiwan capital reductions and par value changes fall in this group; Taiwan stock dividends are converted with the par value, rounding fractional shares down.
- When a broker API cannot return data that far back, the review can only start from the earliest available date.
