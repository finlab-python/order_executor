import copy
import datetime
import json
import uuid

import pandas as pd
import pytest
import requests
from finlab import data, get_token
from finlab.backtest import sim
from finlab.core.firestore_rest import _get_firestore_url, extract_uid_from_id_token
from finlab.markets.tw import TWMarket
from finlab.portfolio import (
    Portfolio,
    PortfolioSyncManager,
    create_custom_report,
    create_report_from_cloud,
)
from finlab.portfolio.portfolio import PositionScheduler


def series_equal(s1, s2):
    # if index exists in both s1 and s2, then compare the values
    intersection = s1.index.intersection(s2.index)
    ret1 = True
    if len(intersection) > 0:
        ret1 = s1[intersection].equals(s2[intersection])

    ret2 = True
    ret2 &= s1[s1.index.difference(s2.index)].sum() == 0
    ret2 &= s2[s2.index.difference(s1.index)].sum() == 0

    return ret1 & ret2


def create_strategy():
    close = data.get("price:收盤價")
    vol = data.get("price:成交股數")
    rev = data.get("monthly_revenue:當月營收")
    rev_yoy_growth = data.get("monthly_revenue:去年同月增減(%)")

    # 近2月平均營收
    rev_ma = rev.average(2)

    # 近2月平均營收創12個月來新高
    condition1 = rev_ma == rev_ma.rolling(12, min_periods=6).max()
    # 近5日內有2日股價創新高
    condition2 = (close == close.rolling(200).max()).sustain(5, 2)
    # 五日成交均量大於500張
    condition3 = vol.average(5) > 500 * 1000
    conditions = condition1 & condition2 & condition3

    # 符合選股條件的名單中，再選出單月營收年增率前10強，並在營收公告截止日換股。
    position = rev_yoy_growth * conditions
    position = (
        position[position > 0]
        .is_largest(10)
        .reindex(rev.index_str_to_date().index, method="ffill")
    )

    # 設定position_limit避免重壓
    return sim(
        position=position,
        stop_loss=0.2,
        take_profit=0.8,
        position_limit=0.25,
        fee_ratio=1.425 / 1000 * 0.3,
        upload=False,
        live_performance_start="2022-10-01",
    )


def _unique_cloud_name(prefix):
    return f"pytest_{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def uploaded_cloud_name(request):
    token, token_type = get_token()
    uid = extract_uid_from_id_token(token) if token_type == "id_token" else None
    if not uid:
        pytest.fail(
            "Cloud upload tests need Firebase authentication for cleanup; "
            "run finlab.login() or set FINLAB_ID_TOKEN before running them. "
            "No reports were uploaded."
        )

    def reserve(prefix):
        sid = _unique_cloud_name(prefix)

        def cleanup():
            # Remove the report and its list entry, even when upload partly failed.
            current_token, current_type = get_token()
            if (
                current_type != "id_token"
                or extract_uid_from_id_token(current_token) != uid
            ):
                pytest.fail(
                    "Cloud cleanup authentication no longer belongs to the upload owner"
                )
            headers = {"Authorization": f"Bearer {current_token}"}
            response = requests.post(
                "https://studio.finlab.finance/api/strategy-delete",
                headers=headers,
                json={"uid": uid, "sids": [sid]},
                timeout=60,
            )
            response.raise_for_status()
            assert response.json()["results"] == [{"sid": sid, "ok": True}]
            response = requests.delete(
                _get_firestore_url(f"users/{uid}/reports/{sid}"),
                headers=headers,
                timeout=60,
            )
            if response.status_code != 404:
                response.raise_for_status()

        request.addfinalizer(cleanup)
        return sid

    return reserve


@pytest.fixture
def uploaded_strategy_report(uploaded_cloud_name):
    strategy_id = uploaded_cloud_name("strategy")
    report = create_strategy()
    report.upload(strategy_id)
    return strategy_id, report


@pytest.fixture
def uploaded_strategy_id(uploaded_strategy_report):
    return uploaded_strategy_report[0]


def test_pm(uploaded_strategy_id):
    report1 = create_report_from_cloud(uploaded_strategy_id)
    report2 = create_custom_report(
        {"2023-01-31": ["1101", "2330"], "2023-06-30": ["1101"], "2023-12-31": ["1101"]}
    )

    portfolio = Portfolio({"test": (report1, 0.8), "custom": (report2, 0.2)})
    pm = PortfolioSyncManager()
    pm.update(portfolio, total_balance=1000000, smooth_transition=False)
    for d in pm.data["position"].values():
        assert "market" in d


def compare_nested_structures(struct1, struct2):
    str1 = json.dumps(struct1, sort_keys=True)
    str2 = json.dumps(struct2, sort_keys=True)
    return str1 == str2


def test_stoploss(uploaded_strategy_id):
    # test pm at stop loss
    now = pd.Timestamp(datetime.datetime.now(datetime.timezone.utc))

    # Create next_weights with a future date as the name to avoid triggering is_rebalance_due()
    next_weights = pd.Series([], index=[], dtype="float64")
    next_weights.name = now + datetime.timedelta(days=14)

    ps = PositionScheduler(
        weights=pd.Series([0.1], index=["2330"], dtype="float64"),
        actions=pd.Series(["sl"], index=["2330"], dtype="object"),
        next_weights=next_weights,
        resample="W",
        stop_loss=0.2,
        take_profit=0.8,
        trail_stop=0.2,
        trade_at="close",
        next_trading_date=(now + datetime.timedelta(days=14)),
        market=TWMarket(),
    )
    report1 = create_report_from_cloud(uploaded_strategy_id)
    report1.position_schedulers = ps
    assert series_equal(report1.execution.actions, ps.actions)

    port = Portfolio({"A1": (report1, 1)})
    pm = PortfolioSyncManager(
        {
            "position": {
                "A1": {
                    "timestamp": now.isoformat(),
                    "next_trading_time": (
                        now + datetime.timedelta(days=14)
                    ).isoformat(),
                    "position": [
                        {"stock_id": "2330", "quantity": 3, "order_condition": 1}
                    ],
                    "allocation": 1000000,
                    "weight": 1,
                    "entry_at": "close",
                    "exit_at": "close",
                    "stop": [],
                    "stop_loss": 0.2,
                    "take_profit": 0.2,
                    "trail_stop": 0.2,
                    "market": "tw_stock",
                }
            },
            "history": {},
        }
    )
    pm.update(port, total_balance=1000000, smooth_transition=True)

    pmdata = copy.deepcopy(pm.data)
    del pmdata["position"]["A1"]["next_trading_time"]
    del pmdata["position"]["A1"]["timestamp"]
    del pmdata["position"]["A1"]["stop"][0]["timestamp"]

    assert compare_nested_structures(
        pmdata,
        {
            "position": {
                "A1": {
                    "position": [
                        {"stock_id": "2330", "quantity": 0, "order_condition": 1}
                    ],
                    "allocation": 1000000,
                    "weight": 1,
                    "entry_at": "close",
                    "exit_at": "close",
                    "stop": [
                        {
                            "stock_id": "2330",
                            "quantity": 3,
                            "order_condition": 1,
                            "reason": "sl",
                        }
                    ],
                    "stop_loss": 0.2,
                    "take_profit": 0.2,
                    "trail_stop": 0.2,
                    "market": "tw_stock",
                }
            },
            "history": {},
            "config": {
                "weights": {"A1": 1.0},
                "params": {
                    "total_balance": 1000000,
                    "rebalance_safety_weight": 0.2,
                    "smooth_transition": True,
                    "force_override_difference": False,
                    "kwargs": {},
                },
            },
        },
    )


def remove_time(data):
    data = copy.deepcopy(data)
    data.pop("timestamp")
    data.pop("next_trading_time")
    return data


def test_combination(uploaded_strategy_id, uploaded_cloud_name):
    report1 = create_report_from_cloud(uploaded_strategy_id)
    report2 = create_custom_report(
        {"2023-01-31": ["1101", "2330"], "2023-06-30": ["1101"], "2023-12-31": ["1101"]}
    )

    portfolio = Portfolio({"test": (report1, 0.8), "custom": (report2, 0.2)})
    pm = PortfolioSyncManager()
    pm.update(portfolio, total_balance=1000000, smooth_transition=False)

    portfolio_name = uploaded_cloud_name("portfolio")
    portfolio.upload(portfolio_name)
    portfolio2 = create_report_from_cloud(portfolio_name)

    pm2 = PortfolioSyncManager()
    pm2.update(portfolio2, total_balance=1000000, smooth_transition=False)

    assert compare_nested_structures(
        remove_time(pm.data["position"]["custom"]),
        remove_time(pm2.data["position"][("strategy|custom")]),
    )
    assert compare_nested_structures(
        remove_time(pm.data["position"]["test"]),
        remove_time(pm2.data["position"][("strategy|test")]),
    )


def test_pm_empty():
    pm = PortfolioSyncManager()
    pm.__str__()


def test_pm_odd_lot():
    from finlab.portfolio.portfolio import PositionScheduler

    from finlab_online.portfolio import PortfolioSyncManager

    weights = pd.Series([0.1], index=["2330 台積電"])
    next_weights = pd.Series([0.2], index=["1101 台泥"])
    resample = None
    actions = pd.Series(["exit", "enter"], index=["2330 台積電", "1101 台泥"])
    trade_at = "close"
    market = TWMarket()
    stop_loss = 0.2
    take_profit = 0.2
    trail_stop = 0.2
    total_weight = 1.0

    pm = PortfolioSyncManager()
    t = TWMarket().get_price("close").index[-1]

    def create_ps():
        return PositionScheduler(
            weights=weights,
            next_weights=next_weights,
            resample=resample,
            actions=actions,
            next_trading_date=t,
            trade_at=trade_at,
            market=market,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trail_stop=trail_stop,
            total_weight=total_weight,
        )

    class Test(Portfolio):
        def __init__(self):
            pass

    port = Test()
    port.position_schedulers = {"1": create_ps()}

    pm = PortfolioSyncManager()

    pm.update(port, total_balance=1000000, odd_lot=True)
    port = Test()
    port.position_schedulers = {"1": create_ps(), "2": create_ps()}
    pm.update(port, total_balance=1000000, odd_lot=True)

    print(pm.__str__())


def make_sched(resample=None, is_rebalance_due=False):
    last_market_date = TWMarket().get_price("close").index[-1]

    if resample is None:
        if is_rebalance_due:
            weights = pd.Series([0.1], index=["2330 台積電"], name=last_market_date)
            next_weights = pd.Series(
                [0.2], index=["1101 台泥"], name=pd.Timestamp("2023-01-01")
            )
        else:
            weights = pd.Series(
                [0.2], index=["2330 台積電"], name=pd.Timestamp("2023-01-01")
            )
            next_weights = pd.Series(
                [0.1], index=["1101 台泥"], name=pd.Timestamp("2023-01-01")
            )
        next_trading_date = last_market_date

    elif isinstance(resample, str):
        weights = pd.Series(
            [0.2], index=["2330 台積電"], name=pd.Timestamp("2023-01-01")
        )
        next_weights = pd.Series(
            [0.1], index=["1101 台泥"], name=pd.Timestamp("2023-01-02")
        )

        if is_rebalance_due:
            next_trading_date = last_market_date - pd.Timedelta("10 days")
        else:
            next_trading_date = last_market_date + pd.Timedelta("10 days")

    actions = pd.Series(["exit", "enter"], index=["2330 台積電", "1101 台泥"])
    trade_at = "close"
    market = TWMarket()
    stop_loss = 0.2
    take_profit = 0.2
    trail_stop = 0.2
    total_weight = 1.0

    return PositionScheduler(
        weights=weights,
        next_weights=next_weights,
        resample=resample,
        actions=actions,
        next_trading_date=next_trading_date,
        trade_at=trade_at,
        market=market,
        stop_loss=stop_loss,
        take_profit=take_profit,
        trail_stop=trail_stop,
        total_weight=total_weight,
    )


def test_not_resample():
    class Test(Portfolio):
        def __init__(self):
            pass

    port = Test()

    # change date

    TWMarket().get_price("close").index[-1]

    # when resample=None, the next_trading_date is in pass
    # so make sure it does not update when smooth_transition is True

    port.position_schedulers = {
        "test": make_sched(resample=None, is_rebalance_due=False)
    }
    pm = PortfolioSyncManager(start_with_empty=True)
    pm.update(port, total_balance=1000000)
    assert "test" not in pm.data["position"]

    # it should update if smooth_transition is False
    port.position_schedulers = {
        "test": make_sched(resample=None, is_rebalance_due=False)
    }
    pm = PortfolioSyncManager()
    pm.update(port, total_balance=1000000, smooth_transition=False)
    assert "test" in pm.data["position"]

    # when the next trading date is changed
    port.position_schedulers = {
        "test": make_sched(resample=None, is_rebalance_due=True)
    }
    pm = PortfolioSyncManager()
    pm.update(port, total_balance=1000000)
    assert "test" in pm.data["position"]

    # when the next trading date is in future,
    # it should not update
    port.position_schedulers = {
        "test": make_sched(resample=None, is_rebalance_due=False)
    }
    pm = PortfolioSyncManager(start_with_empty=True)
    pm.update(port, total_balance=1000000)
    assert "test" not in pm.data["position"]

    pm.update(port, total_balance=1000000, smooth_transition=False)
    assert "test" in pm.data["position"]

    # --------------------------------------------------
    # when pm already has position
    # it should update if smooth_transition is False
    # --------------------------------------------------
    port.position_schedulers = {
        "test": make_sched(resample=None, is_rebalance_due=True)
    }
    pm = PortfolioSyncManager()
    pm.update(port, total_balance=1000000, smooth_transition=False)

    assert pm.data["position"]["test"]["position"][0]["stock_id"] == "1101"
    data.truncate_end = None


def test_pm_reduce_strategy():
    from finlab.portfolio.portfolio import PositionScheduler

    from finlab_online.portfolio import PortfolioSyncManager

    weights = pd.Series([0.1], index=["2330 台積電"])
    next_weights = pd.Series([0.2], index=["1101 台泥"])
    resample = "W"
    actions = pd.Series(["exit", "enter"], index=["2330 台積電", "1101 台泥"])
    trade_at = "close"
    market = TWMarket()
    stop_loss = 0.2
    take_profit = 0.2
    trail_stop = 0.2

    class Test(Portfolio):
        def __init__(self):
            pass

    port = Test()

    # change date

    last_market_date = TWMarket().get_price("close").index[-1]

    def create_ps(t, w=1):
        return PositionScheduler(
            weights=weights,
            next_weights=next_weights,
            resample=resample,
            actions=actions,
            next_trading_date=t,
            trade_at=trade_at,
            market=market,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trail_stop=trail_stop,
            total_weight=w,
        )

    ps = create_ps(last_market_date, 0)
    assert ps.total_weight == 0

    port.position_schedulers = {
        "test1": create_ps(last_market_date - datetime.timedelta(days=10)),
        "test2": create_ps(last_market_date - datetime.timedelta(days=10)),
        "test3": create_ps(last_market_date - datetime.timedelta(days=10)),
    }

    pm = PortfolioSyncManager()
    pm.update(port, total_balance=1000000)
    assert "test1" in pm.data["position"]

    port.position_schedulers = {
        "test1": create_ps(last_market_date - datetime.timedelta(days=10)),
        "test2": create_ps(last_market_date - datetime.timedelta(days=10)),
        "test3": create_ps(last_market_date - datetime.timedelta(days=10)),
    }

    pm.update(port, total_balance=1000000, smooth_transition=False)
    assert "test3" in pm.data["position"]
    assert pm.data["position"]["test3"]["allocation"] != 0

    port.position_schedulers = {
        "test1": create_ps(last_market_date),
        "test2": create_ps(last_market_date),
        "test3": create_ps(last_market_date, 0),
    }

    pm.update(port, total_balance=1000000, smooth_transition=False)
    assert "test3" not in pm.data["position"]


def test_custom_position():
    from finlab.portfolio.portfolio import PositionScheduler

    from finlab_online.portfolio import PortfolioSyncManager

    weights = pd.Series([0.1], index=["2330 台積電"])
    next_weights = pd.Series([0.2], index=["1101 台泥"])
    resample = "W"
    actions = pd.Series(["exit", "enter"], index=["2330 台積電", "1101 台泥"])
    trade_at = "close"
    market = TWMarket()
    stop_loss = 0.2
    take_profit = 0.2
    trail_stop = 0.2

    class Test(Portfolio):
        def __init__(self):
            pass

    port = Test()

    # change date

    last_market_date = TWMarket().get_price("close").index[-1]

    def create_ps(t, w=1):
        return PositionScheduler(
            weights=weights,
            next_weights=next_weights,
            resample=resample,
            actions=actions,
            next_trading_date=t,
            trade_at=trade_at,
            market=market,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trail_stop=trail_stop,
            total_weight=w,
        )

    port.position_schedulers = {
        "test1": create_ps(last_market_date),
    }

    pm = PortfolioSyncManager()
    pm.update(port, total_balance=10000000, custom_position={"2454": 1})
    pos = pm.get_position()

    # find ele in pos where ele['stock_id'] == '2454'
    ele = [ele for ele in pos.position if ele["stock_id"] == "2454"]
    assert len(ele) == 1
    assert ele[0]["quantity"] == 1

    pm.update(
        port,
        total_balance=10000000,
        custom_position={"2454": 1},
        excluded_stock_ids=["2454"],
    )

    pos = pm.get_position()
    ele = [ele for ele in pos.position if ele["stock_id"] == "2454"]
    assert len(ele) == 0


def test_has_market_name_and_last_market_close_and_trade_at():
    from finlab.portfolio.portfolio import PositionScheduler

    from finlab_online.portfolio import PortfolioSyncManager

    weights = pd.Series([0.1], index=["2330 台積電"])
    next_weights = pd.Series([0.2], index=["1101 台泥"])
    resample = None
    actions = pd.Series(["exit", "enter"], index=["2330 台積電", "1101 台泥"])
    trade_at = "close"
    market = TWMarket()
    stop_loss = 0.2
    take_profit = 0.2
    trail_stop = 0.2
    total_weight = 1.0

    class Test(Portfolio):
        def __init__(self):
            pass

    port = Test()

    # change date

    last_market_date = TWMarket().get_price("close").index[-1]

    def create_ps(t):
        return PositionScheduler(
            weights=weights,
            next_weights=next_weights,
            resample=resample,
            actions=actions,
            next_trading_date=t,
            trade_at=trade_at,
            market=market,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trail_stop=trail_stop,
            total_weight=total_weight,
        )

    create_ps(last_market_date)

    port.position_schedulers = {
        "test1": create_ps(last_market_date),
    }

    pm = PortfolioSyncManager()
    pm.update(port, total_balance=1000000, smooth_transition=False)

    assert pm.data["position"]["test1"]["market"] == "tw_stock"
    assert pm.data["position"]["test1"]["last_market_timestamp"]

    assert pm.get_position(market_name="tw_stock").position[0]["stock_id"] == "1101"
    assert len(pm.get_position(market_name="abc").position) == 0

    # test trade_at
    assert len(pm.get_position(at="open").position) == 1
    assert len(pm.get_position(at="close").position) == 1


def test_init_pm():
    report1 = create_custom_report(
        {"2023-01-31": ["1101", "2330"], "2023-06-30": ["1101"], "2023-12-31": ["1101"]}
    )
    report2 = create_custom_report(
        {"2023-01-31": ["1101", "2330"], "2023-06-30": ["1101"], "2023-12-31": ["1101"]}
    )

    portfolio = Portfolio({"test": (report1, 0.8), "custom": (report2, 0.2)})
    pm = PortfolioSyncManager()
    pm.update(portfolio, total_balance=100000000)
    assert len(pm.data["position"]) == 2


def test_rebalance_due_and_stop_triggered(monkeypatch):
    import datetime as dt
    import io
    import logging

    from finlab import data
    from finlab.backtest import sim
    from finlab.core.report import ReportExecution
    from finlab.portfolio import Portfolio

    from finlab_online.portfolio import PortfolioSyncManager

    # This covers PM sync and stop logic with the signal-label rules; the TW
    # calendar window closes weeks-old boundaries and has its own unit tests.
    monkeypatch.setattr(
        ReportExecution,
        "rebalance_timing",
        lambda self, now=None, calendar=None: {"status": "unknown"},
    )

    today = dt.date.today()
    # report: truncate to end of last month → next_weights in the past → rebalance due
    last_month_end = today.replace(day=1) - dt.timedelta(days=1)
    # report2: truncate to 3rd of current month → next_weights at end of month → not yet due
    current_month_3rd = today.replace(day=3)

    def build_buy():
        close = data.get("price:收盤價")
        vol = data.get("price:成交股數")
        vol_ma = vol.average(10)
        rev = data.get("monthly_revenue:當月營收")
        rev_year_growth = data.get("monthly_revenue:去年同月增減(%)")
        rev_month_growth = data.get("monthly_revenue:上月比較增減(%)")
        cond1 = close == close.rolling(250).max()
        cond2 = ~(rev_year_growth < -10).sustain(3)
        cond3 = ~(rev_year_growth > 60).sustain(12, 8)
        cond4 = ((rev.rolling(12).min()) / (rev) < 0.8).sustain(3)
        cond5 = (rev_month_growth > -40).sustain(3)
        cond6 = vol_ma > 200 * 1000
        buy = cond1 & cond2 & cond3 & cond4 & cond5 & cond6
        buy = vol_ma * buy
        buy = buy[buy > 0]
        return buy.is_smallest(5)

    data.truncate_end = last_month_end.strftime("%Y-%m-%d")
    buy = build_buy()
    report = sim(
        buy,
        resample="M",
        upload=True,
        position_limit=1 / 3,
        fee_ratio=1.425 / 1000 / 3,
        stop_loss=0.08,
        trade_at_price="open",
        name="藏獒",
        live_performance_start="2022-05-01",
    )

    data.truncate_end = current_month_3rd.strftime("%Y-%m-%d")
    buy2 = build_buy()
    report2 = sim(
        buy2,
        resample="M",
        upload=True,
        position_limit=1 / 3,
        fee_ratio=1.425 / 1000 / 3,
        stop_loss=0.08,
        trade_at_price="open",
        name="藏獒",
        live_performance_start="2022-05-01",
    )
    # Live data may lag the current month; force the second report's scheduled
    # rebalance into the future so this test only covers portfolio sync logic.
    future_rebalance = dt.datetime.now() + dt.timedelta(days=14)
    report2.next_weights.name = future_rebalance
    report2.next_trading_date = future_rebalance

    # report's next rebalance is in the past, report2's is explicitly in the future.
    assert report.is_rebalance_due()
    assert not report2.is_rebalance_due()

    port = Portfolio({"r": (report, 1)})

    pm = PortfolioSyncManager()

    # Setup log capture
    log_capture_string = io.StringIO()
    ch = logging.StreamHandler(log_capture_string)
    ch.setLevel(logging.INFO)

    # Get the logger and add the handler
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(ch)

    # Run the update
    pm.update(port, total_balance=20000000)

    # Extract the string
    captured_log = log_capture_string.getvalue()

    assert "today is trading date" in captured_log

    port = Portfolio({"r": (report2, 1)})
    scheduler = port.position_schedulers["r"]
    stop_actions = scheduler.actions[scheduler.actions.isin(["sl", "tp"])]
    if not stop_actions.empty:
        stop_symbol = stop_actions.index[0].split(" ")[0]
        pm.data["position"]["r"]["position"] = [
            {"stock_id": stop_symbol, "quantity": 1}
        ]

    pm.update(port, total_balance=20000000)

    captured_log2 = log_capture_string.getvalue()
    if not stop_actions.empty:
        assert f"has a {stop_actions.iloc[0]} signal" in captured_log2
    else:
        assert "has a sl signal" not in captured_log2
        assert "has a tp signal" not in captured_log2
    logger.removeHandler(ch)


def _make_pm_with_strategy(
    strategy_name, entry_at, position, history=None, last_market_timestamp=None
):
    """Helper to build a PortfolioSyncManager with hand-crafted data."""
    from finlab.markets.tw import TWMarket

    from finlab_online.portfolio import PortfolioSyncManager

    market = TWMarket()
    if last_market_timestamp is None:
        last_market_timestamp = market.market_close_at_timestamp(
            market.get_price("close").index[-1]
        ).isoformat()

    pm = PortfolioSyncManager()
    pm.data = {
        "position": {
            strategy_name: {
                "position": position,
                "market": "tw_stock",
                "entry_at": entry_at,
                "exit_at": entry_at,
                "last_market_timestamp": last_market_timestamp,
            }
        },
        "history": {strategy_name: history} if history is not None else {},
        "market": None,
        "config": {},
    }
    return pm


def test_strategy_position_close_at_open_empty_history():
    """Close-strategy queried at='open' with empty history → returns current position."""
    position = [{"stock_id": "1101", "weight": 0.5}]
    pm = _make_pm_with_strategy("s1", entry_at="close", position=position, history=[])
    result = pm.get_strategy_position("s1", at="open")
    assert result == position


def test_strategy_position_close_at_open_single_same_day_history():
    """Close-strategy queried at='open' with single same-day history entry → returns current position."""
    from finlab.markets.tw import TWMarket

    market = TWMarket()
    ts = market.market_close_at_timestamp(
        market.get_price("close").index[-1]
    ).isoformat()

    position = [{"stock_id": "2330", "weight": 0.3}]
    history = [
        {"position": [{"stock_id": "9999", "weight": 1.0}], "last_market_timestamp": ts}
    ]
    pm = _make_pm_with_strategy(
        "s1", entry_at="close", position=position, history=history
    )
    result = pm.get_strategy_position("s1", at="open")
    assert result == position


def test_strategy_position_close_at_open_normal_history():
    """Close-strategy queried at='open' with normal history → returns history[-1] (unchanged behavior)."""
    from finlab.markets.tw import TWMarket

    market = TWMarket()
    ts = market.market_close_at_timestamp(
        market.get_price("close").index[-1]
    ).isoformat()

    old_position = [{"stock_id": "1101", "weight": 0.5}]
    prev_position = [{"stock_id": "2330", "weight": 0.3}]
    position = [{"stock_id": "3008", "weight": 0.2}]
    history = [
        {"position": old_position, "last_market_timestamp": "2020-01-01T00:00:00"},
        {"position": prev_position, "last_market_timestamp": ts},
    ]
    pm = _make_pm_with_strategy(
        "s1", entry_at="close", position=position, history=history
    )
    result = pm.get_strategy_position("s1", at="open")
    assert result == old_position


def test_strategy_position_open_at_open():
    """Open-strategy queried at='open' → returns current position (not use_previous_position)."""
    position = [{"stock_id": "1101", "weight": 0.5}]
    pm = _make_pm_with_strategy("s1", entry_at="open", position=position, history=[])
    result = pm.get_strategy_position("s1", at="open")
    assert result == position


def test_strategy_position_mixed_portfolio():
    """Mixed portfolio: get_strategy_position at='open' returns holdings from both strategies."""
    from finlab.markets.tw import TWMarket

    from finlab_online.portfolio import PortfolioSyncManager

    market = TWMarket()
    ts = market.market_close_at_timestamp(
        market.get_price("close").index[-1]
    ).isoformat()

    close_pos = [{"stock_id": "1101", "weight": 0.5}]
    open_pos = [{"stock_id": "2330", "weight": 0.3}]

    pm = PortfolioSyncManager()
    pm.data = {
        "position": {
            "close_strat": {
                "position": close_pos,
                "market": "tw_stock",
                "entry_at": "close",
                "exit_at": "close",
                "last_market_timestamp": ts,
            },
            "open_strat": {
                "position": open_pos,
                "market": "tw_stock",
                "entry_at": "open",
                "exit_at": "open",
                "last_market_timestamp": ts,
            },
        },
        "history": {},
        "market": None,
        "config": {},
    }

    # Close-strategy at open with empty history → returns current position (not [])
    close_result = pm.get_strategy_position("close_strat", at="open")
    assert close_result == close_pos

    # Open-strategy at open → returns current position directly
    open_result = pm.get_strategy_position("open_strat", at="open")
    assert open_result == open_pos

    # Both strategies retain their holdings at open
    assert len(close_result) + len(open_result) == 2
