import numpy as np
import pandas as pd

def greedy_allocation(weights, latest_prices, total_portfolio_value=10000):

    """
    original source code: PyPortfolioOpt
    https://pypi.org/project/pyportfolioopt/
    """

    weights = pd.Series(weights)

    weights.index = weights.index.to_series().astype(str)\
            .str.split(' ').str[0]
    weights = list(weights.items())
    latest_prices = latest_prices

    if len(weights) == 0:
        return {}, total_portfolio_value

    """
    Convert continuous weights into a discrete portfolio allocation
    using a greedy iterative approach.

    :param reinvest: whether or not to reinvest cash gained from shorting
    :type reinvest: bool, defaults to False
    :param verbose: print error analysis?
    :type verbose: bool, defaults to False
    :return: the number of shares of each ticker that should be purchased,
             along with the amount of funds leftover.
    :rtype: (dict, float)
    """
    reinvest = False
    verbose = False
    # Sort in descending order of weight
    weights.sort(key=lambda x: x[1], reverse=True)

    # If portfolio contains shorts
    if weights[-1][1] < 0:
        longs = {t: w for t, w in weights if w >= 0}
        shorts = {t: -w for t, w in weights if w < 0}

        # Make them sum to one
        long_total_weight = sum(longs.values())
        short_total_weight = sum(shorts.values())
        longs = {t: w / long_total_weight for t, w in longs.items()}
        shorts = {t: w / short_total_weight for t, w in shorts.items()}

        # Construct long-only discrete allocations for each
        short_val = total_portfolio_value * short_total_weight
        long_val = total_portfolio_value * long_total_weight

        if verbose:
            print("\nAllocating long sub-portfolio...")
        # da1 = DiscreteAllocation(
        #     longs, latest_prices[longs.keys()], total_portfolio_value=long_val
        # )
        long_alloc, long_leftover = greedy_allocation(longs, latest_prices, long_val)

        if verbose:
            print("\nAllocating short sub-portfolio...")
        # da2 = DiscreteAllocation(
        #     shorts,
        #     latest_prices[shorts.keys()],
        #     total_portfolio_value=short_val,
        # )
        short_alloc, short_leftover = greedy_allocation(shorts, latest_prices, short_val)
        short_alloc = {t: -w for t, w in short_alloc.items()}

        # Combine and return
        allocation = long_alloc.copy()
        allocation.update(short_alloc)
        allocation = {t:w for t, w in allocation.items() if w != 0}

        return allocation, long_leftover + short_leftover

    # Otherwise, portfolio is long only and we proceed with greedy algo
    available_funds = total_portfolio_value
    shares_bought = []
    buy_prices = []

    # First round
    for ticker, weight in weights:
        price = latest_prices[ticker]
        # Attempt to buy the lower integer number of shares, which could be zero.
        n_shares = int(weight * total_portfolio_value / price)
        cost = n_shares * price
        # As weights are all > 0 (long only) we always round down n_shares
        # so the cost is always <= simple weighted share of portfolio value,
        # so we can not run out of funds just here.
        assert cost <= available_funds, "Unexpectedly insufficient funds."
        available_funds -= cost
        shares_bought.append(n_shares)
        buy_prices.append(price)

    # Second round
    while available_funds > 0:
        # Calculate the equivalent continuous weights of the shares that
        # have already been bought
        current_weights = np.array(buy_prices) * np.array(shares_bought)
        wsum = current_weights.sum()
        if wsum != 0:
            current_weights = current_weights / wsum
        ideal_weights = np.array([i[1] for i in weights])
        deficit = ideal_weights - current_weights

        # Attempt to buy the asset whose current weights deviate the most
        idx = np.argmax(deficit)
        ticker, weight = weights[idx]
        price = latest_prices[ticker]

        # If we can't afford this asset, search for the next highest deficit that we
        # can purchase.
        counter = 0
        while price > available_funds:
            deficit[idx] = 0  # we can no longer purchase the asset at idx
            idx = np.argmax(deficit)  # find the next most deviant asset

            # If either of these conditions is met, we break out of both while loops
            # hence the repeated statement below
            if deficit[idx] < 0 or counter == 10:
                break

            ticker, weight = weights[idx]
            price = latest_prices[ticker]
            counter += 1

        if deficit[idx] <= 0 or counter == 10:  # pragma: no cover
            # Dirty solution to break out of both loops
            break

        # Buy one share at a time
        shares_bought[idx] += 1
        available_funds -= price

    allocation = dict(zip([i[0] for i in weights], shares_bought))

    if verbose:
        print("Funds remaining: {:.2f}".format(available_funds))
    return allocation, available_funds


