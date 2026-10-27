"""
OrderExecutor 單元測試

測試 OrderExecutor 的核心邏輯，使用 mock 來隔離外部依賴
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

# 導入被測試的模組
from finlab.online.enums import Action, OrderCondition, OrderStatus
from finlab.online.order_executor import OrderExecutor, Position

# 導入測試基礎設施
from ..utils.test_base import AccountTestMixin, MockTestCase


class TestOrderExecutorUnit(MockTestCase, AccountTestMixin):
    """OrderExecutor 單元測試類"""

    def setUp(self) -> None:
        super().setUp()
        # 創建 mock account
        self.mock_account = Mock()
        self.setup_mock_account_defaults()

    def setup_mock_account_defaults(self) -> None:
        """設置 mock account 的默認行為"""
        # 默認空持倉
        self.mock_account.get_position.return_value = Position({})

        # 默認空委託單
        self.mock_account.get_orders.return_value = {}

        # 默認成功的下單回應
        self.mock_account.create_order.return_value = "test_order_001"

        # 默認取消委託單成功
        self.mock_account.cancel_order.return_value = None

        # 默認支援當沖
        self.mock_account.support_day_trade_condition.return_value = True

        # 默認支援零股
        self.mock_account.sep_odd_lot_order.return_value = True

        # 默認空股票數據
        self.mock_account.get_stocks.return_value = {}

        # 默認不是加密貨幣帳戶（無 base_currency 屬性）
        if hasattr(self.mock_account, "base_currency"):
            delattr(self.mock_account, "base_currency")

        # 默認沒有價格資訊功能
        if hasattr(self.mock_account, "get_price_info"):
            delattr(self.mock_account, "get_price_info")

    def test_init_with_dict_position(self) -> None:
        """測試用字典初始化 OrderExecutor"""
        target_dict = {"2330": 1, "2881": 2}
        oe = OrderExecutor(target_dict, self.mock_account)

        self.assertIsInstance(oe.target_position, Position)
        self.assertEqual(oe.account, self.mock_account)
        self.assertEqual(len(oe.target_position.position), 2)

    def test_init_with_position_object(self) -> None:
        """測試用 Position 物件初始化 OrderExecutor"""
        target_position = Position({"2330": 1, "2881": 2})
        oe = OrderExecutor(target_position, self.mock_account)

        self.assertEqual(oe.target_position, target_position)
        self.assertEqual(oe.account, self.mock_account)

    def test_generate_orders_empty_difference(self) -> None:
        """測試當目標持倉與現有持倉相同時，不產生訂單"""
        # 設置現有持倉與目標持倉相同
        current_position = Position({"2330": 1, "2881": 2})
        self.mock_account.get_position.return_value = current_position

        target_position = Position({"2330": 1, "2881": 2})
        oe = OrderExecutor(target_position, self.mock_account)

        orders = oe.generate_orders()
        self.assertEqual(len(orders), 0)

    def test_generate_orders_buy_orders(self) -> None:
        """測試產生買單"""
        # 設置空持倉
        self.mock_account.get_position.return_value = Position({})

        # 目標持倉要買進股票
        target_position = Position({"2330": 1, "2881": 2})
        oe = OrderExecutor(target_position, self.mock_account)

        orders = oe.generate_orders()

        # 應該產生 2 個買單
        self.assertEqual(len(orders), 2)

        # 檢查訂單內容
        stock_orders = {o["stock_id"]: o for o in orders}

        self.assertIn("2330", stock_orders)
        self.assertIn("2881", stock_orders)

        self.assertEqual(stock_orders["2330"]["quantity"], 1)
        self.assertEqual(stock_orders["2881"]["quantity"], 2)

        # 所有都應該是買單
        for order in orders:
            self.assertGreater(order["quantity"], 0)

    def test_generate_orders_sell_orders(self) -> None:
        """測試產生賣單"""
        # 設置現有持倉
        current_position = Position({"2330": 2, "2881": 1})
        self.mock_account.get_position.return_value = current_position

        # 目標持倉為空（全部賣出）
        target_position = Position({})
        oe = OrderExecutor(target_position, self.mock_account)

        orders = oe.generate_orders()

        # 應該產生 2 個賣單
        self.assertEqual(len(orders), 2)

        # 檢查訂單內容
        stock_orders = {o["stock_id"]: o for o in orders}

        self.assertEqual(stock_orders["2330"]["quantity"], -2)  # 賣出 2 張
        self.assertEqual(stock_orders["2881"]["quantity"], -1)  # 賣出 1 張

    def test_generate_orders_mixed_orders(self) -> None:
        """測試產生混合買賣單"""
        # 設置現有持倉
        current_position = Position({"2330": 1, "2881": 3})
        self.mock_account.get_position.return_value = current_position

        # 目標持倉：增加 2330，減少 2881，新增 0050
        target_position = Position({"2330": 3, "2881": 1, "0050": 2})
        oe = OrderExecutor(target_position, self.mock_account)

        orders = oe.generate_orders()

        # 應該產生 3 個訂單
        self.assertEqual(len(orders), 3)

        stock_orders = {o["stock_id"]: o for o in orders}

        self.assertEqual(stock_orders["2330"]["quantity"], 2)  # 買進 2 張
        self.assertEqual(stock_orders["2881"]["quantity"], -2)  # 賣出 2 張
        self.assertEqual(stock_orders["0050"]["quantity"], 2)  # 買進 2 張

    def test_generate_orders_with_progress(self) -> None:
        """測試部分執行進度"""
        # 設置空持倉
        self.mock_account.get_position.return_value = Position({})

        # 目標持倉
        target_position = Position({"2330": 10})
        oe = OrderExecutor(target_position, self.mock_account)

        # 執行 50% 進度
        orders = oe.generate_orders(progress=0.5)

        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["quantity"], 5)  # 10 * 0.5 = 5

    def test_generate_orders_progress_does_not_round_past_difference(self) -> None:
        """progress 進位後超過剩餘差額時往零捨去"""
        # (現有部位, 目標部位, progress, 預期下單量)
        cases = [
            ({"2330": 0.2}, {"2330": 1.0}, 0.7, 0),
            ({"2330": 0.6}, {}, 0.9, 0),
            ({}, {"2330": 2.9}, 0.9, 2),
            ({"2330": 0.4}, {"2330": 1.4}, 0.9, 1),
            ({"2330": 1.4}, {"2330": 0.4}, 0.9, -1),
        ]
        for present, target, progress, expected in cases:
            with self.subTest(present=present, target=target, progress=progress):
                self.mock_account.get_position.return_value = Position(present)
                oe = OrderExecutor(Position(target), self.mock_account)
                orders = oe.generate_orders(progress=progress)
                self.assertEqual(orders[0]["quantity"], expected)

    def test_generate_orders_day_trading_long_filled_as_cash(self) -> None:
        """現沖先買成交後券商回報成現股，盤中再同步不再一賣一買"""
        target = Position({"2330": 1}, day_trading_long=True)
        self.mock_account.get_position.return_value = Position({"2330": 1})
        orders = OrderExecutor(target, self.mock_account).generate_orders()
        self.assertEqual(orders, [])

        # 目標同檔也有現股時照舊分開比對（數量型別混用也不出錯）
        mixed = Position.from_list(
            [
                {"stock_id": "2330", "quantity": q, "order_condition": oc}
                for q, oc in [
                    (Decimal("1"), OrderCondition.CASH),
                    (1.0, OrderCondition.DAY_TRADING_LONG),
                ]
            ]
        )
        orders = OrderExecutor(mixed, self.mock_account).generate_orders()
        self.assertEqual(
            [(o["quantity"], o["order_condition"]) for o in orders],
            [(1.0, OrderCondition.DAY_TRADING_LONG)],
        )

        # 還沒成交時照舊送現沖先買
        self.mock_account.get_position.return_value = Position({})
        orders = OrderExecutor(target, self.mock_account).generate_orders()
        self.assertEqual(orders[0]["order_condition"], OrderCondition.DAY_TRADING_LONG)

    def test_generate_orders_cash_short_held_as_short_selling(self) -> None:
        """空單目標是現股、券商回報成融券時，同步不再一賣一買"""
        short = Position({"AAPL": -26}, short_selling=True)
        # (現有部位, 目標部位, 預期委託)；沒有融券部位時照舊送現股賣出
        for present, target, expected in [
            (short, Position({"AAPL": -26}), []),
            (short, Position({"AAPL": -26}, short_selling=True), []),
            (short, Position({"AAPL": -30}), [(-4, OrderCondition.SHORT_SELLING)]),
            (Position({}), Position({"AAPL": -26}), [(-26, OrderCondition.CASH)]),
        ]:
            with self.subTest(present=present, target=target):
                self.mock_account.get_position.return_value = present
                orders = OrderExecutor(target, self.mock_account).generate_orders()
                self.assertEqual(
                    [(o["quantity"], o["order_condition"]) for o in orders], expected
                )

    def test_cancel_orders(self) -> None:
        """測試取消委託單"""
        # 設置現有委託單
        mock_orders = {
            "order1": Mock(status=OrderStatus.NEW),
            "order2": Mock(status=OrderStatus.NEW),
            "order3": Mock(status=OrderStatus.FILLED),  # 已成交，不應取消
        }
        self.mock_account.get_orders.return_value = mock_orders

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.cancel_orders()

        # 應該只取消 NEW 狀態的訂單
        expected_cancel_calls = ["order1", "order2"]
        actual_cancel_calls = [
            call[0][0] for call in self.mock_account.cancel_order.call_args_list
        ]

        self.assertEqual(len(actual_cancel_calls), 2)
        for order_id in expected_cancel_calls:
            self.assertIn(order_id, actual_cancel_calls)

    def test_cancel_orders_buy_only_sell_only(self) -> None:
        """測試 cancel_orders 只取消買單或只取消賣單"""
        mock_orders = {
            "buy1": Mock(status=OrderStatus.NEW, action=Action.BUY),
            "buy2": Mock(status=OrderStatus.PARTIALLY_FILLED, action=Action.BUY),
            "sell1": Mock(status=OrderStatus.NEW, action=Action.SELL),
            "filled": Mock(status=OrderStatus.FILLED, action=Action.BUY),
        }
        self.mock_account.get_orders.return_value = mock_orders
        oe = OrderExecutor(Position({}), self.mock_account)

        oe.cancel_orders(buy_only=True)
        cancelled = [c[0][0] for c in self.mock_account.cancel_order.call_args_list]
        self.assertEqual(sorted(cancelled), ["buy1", "buy2"])

        self.mock_account.cancel_order.reset_mock()
        oe.cancel_orders(sell_only=True)
        cancelled = [c[0][0] for c in self.mock_account.cancel_order.call_args_list]
        self.assertEqual(cancelled, ["sell1"])

        with self.assertRaises(ValueError):
            oe.cancel_orders(buy_only=True, sell_only=True)

    def test_execute_orders_view_only(self) -> None:
        """測試 view_only 模式"""
        orders = [
            {"stock_id": "2330", "quantity": 1, "order_condition": OrderCondition.CASH}
        ]
        self.mock_account.get_orders.return_value = {
            "order1": Mock(status=OrderStatus.NEW, action=Action.BUY)
        }
        self.mock_account.get_stocks.return_value = {
            "2330": Mock(close=580.0, bid_price=579.0, ask_price=581.0)
        }

        oe = OrderExecutor(Position({}), self.mock_account)
        result = oe.execute_orders(orders, view_only=True)

        # view_only 模式應該返回訂單列表，不實際下單
        self.assertEqual(result, orders)
        self.mock_account.create_order.assert_not_called()
        self.mock_account.cancel_order.assert_not_called()

    def test_execute_orders_normal(self) -> None:
        """測試正常下單執行"""
        orders = [
            {"stock_id": "2330", "quantity": 1, "order_condition": OrderCondition.CASH},
            {
                "stock_id": "2881",
                "quantity": -1,
                "order_condition": OrderCondition.CASH,
            },
        ]

        # Mock 股票報價
        mock_stocks = {
            "2330": Mock(close=580.0, bid_price=579.0, ask_price=581.0),
            "2881": Mock(close=66.0, bid_price=65.5, ask_price=66.5),
        }
        self.mock_account.get_stocks.return_value = mock_stocks

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.execute_orders(orders)

        # 應該調用 create_order 兩次
        self.assertEqual(self.mock_account.create_order.call_count, 2)

        # 檢查下單參數
        call_args_list = self.mock_account.create_order.call_args_list

        # 第一筆：買單
        buy_call = call_args_list[0]
        self.assertEqual(buy_call.kwargs["action"], Action.BUY)
        self.assertEqual(buy_call.kwargs["stock_id"], "2330")
        self.assertEqual(buy_call.kwargs["quantity"], 1)

        # 第二筆：賣單
        sell_call = call_args_list[1]
        self.assertEqual(sell_call.kwargs["action"], Action.SELL)
        self.assertEqual(sell_call.kwargs["stock_id"], "2881")
        self.assertEqual(sell_call.kwargs["quantity"], 1)

    def test_execute_orders_with_extra_bid_pct(self) -> None:
        """測試額外競價百分比"""
        orders = [
            {"stock_id": "2330", "quantity": 1, "order_condition": OrderCondition.CASH}
        ]

        # Mock 股票報價
        mock_stocks = {"2330": Mock(close=100.0, bid_price=99.0, ask_price=101.0)}
        self.mock_account.get_stocks.return_value = mock_stocks

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.execute_orders(orders, extra_bid_pct=0.05)  # 5% 額外競價

        # 檢查價格計算
        call_args = self.mock_account.create_order.call_args
        actual_price = call_args.kwargs["price"]

        # 買單應該是 close * (1 + 0.05) = 100.0 * 1.05 = 105.0
        # 實際上 OrderExecutor 使用 close 價格而不是 ask_price
        expected_price = 100.0 * 1.05
        self.assertAlmostEqual(actual_price, expected_price, places=2)

    def test_execute_orders_float_error_not_split_into_1000_odd_lot(self) -> None:
        """張數有浮點誤差時，不拆出 1000 股的零股單"""
        orders = [
            {
                "stock_id": "2330",
                "quantity": 0.9999999999999999,
                "order_condition": OrderCondition.CASH,
            }
        ]
        mock_stocks = {"2330": Mock(close=580.0, bid_price=579.0, ask_price=581.0)}
        self.mock_account.get_stocks.return_value = mock_stocks

        OrderExecutor(Position({}), self.mock_account).execute_orders(orders)

        self.mock_account.create_order.assert_called_once()
        call_args = self.mock_account.create_order.call_args
        self.assertEqual(call_args.kwargs["quantity"], 1)
        self.assertNotIn("odd_lot", call_args.kwargs)

    def test_execute_orders_extra_bid_pct_uses_us_tick(self) -> None:
        """美股帳戶追價用美股跳動單位"""
        from finlab.markets.us import USMarket

        self.mock_account.get_market.return_value = USMarket()
        self.mock_account.sep_odd_lot_order.return_value = False
        mock_stocks = {"AAPL": Mock(close=157.3, bid_price=157.2, ask_price=157.4)}
        self.mock_account.get_stocks.return_value = mock_stocks
        orders = [
            {"stock_id": "AAPL", "quantity": 1, "order_condition": OrderCondition.CASH}
        ]

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.execute_orders(orders, extra_bid_pct=0.001)

        self.assertEqual(self.mock_account.create_order.call_args.kwargs["price"], 157.45)

    def test_execute_orders_extra_bid_pct_uses_etf_tick(self) -> None:
        """台股 ETF 追價用 ETF 跳動單位，買價不低於、賣價不高於現價"""
        self.mock_account.get_stocks.return_value = {
            "006208": Mock(close=120.15),
            "00878": Mock(close=21.33),
        }
        orders = [
            {"stock_id": sid, "quantity": qty, "order_condition": OrderCondition.CASH}
            for sid, qty in [("006208", 1), ("00878", -1)]
        ]

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.execute_orders(orders, extra_bid_pct=0.002)

        calls = self.mock_account.create_order.call_args_list
        self.assertEqual([c.kwargs["price"] for c in calls], [120.35, 21.29])

    def test_execute_orders_market_order(self) -> None:
        """測試市價單"""
        orders = [
            {"stock_id": "2330", "quantity": 1, "order_condition": OrderCondition.CASH}
        ]

        # Mock 股票報價
        mock_stocks = {"2330": Mock(close=580.0, bid_price=579.0, ask_price=581.0)}
        self.mock_account.get_stocks.return_value = mock_stocks

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.execute_orders(orders, market_order=True)

        # 檢查市價單參數
        call_args = self.mock_account.create_order.call_args
        self.assertTrue(call_args.kwargs["market_order"])

    def test_execute_orders_best_price_limit(self) -> None:
        """測試最佳價格限制"""
        orders = [
            {"stock_id": "2330", "quantity": 1, "order_condition": OrderCondition.CASH}
        ]

        # Mock 股票報價
        mock_stocks = {"2330": Mock(close=580.0, bid_price=579.0, ask_price=581.0)}
        self.mock_account.get_stocks.return_value = mock_stocks

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.execute_orders(orders, best_price_limit=True)

        # 檢查最佳價格參數
        call_args = self.mock_account.create_order.call_args
        self.assertTrue(call_args.kwargs["best_price_limit"])

    def test_execute_orders_buy_only(self) -> None:
        """測試只執行買單"""
        orders = [
            {
                "stock_id": "2330",
                "quantity": 1,
                "order_condition": OrderCondition.CASH,
            },  # 買單
            {
                "stock_id": "2881",
                "quantity": -1,
                "order_condition": OrderCondition.CASH,
            },  # 賣單
        ]

        mock_stocks = {
            "2330": Mock(close=580.0, ask_price=581.0),
            "2881": Mock(close=66.0, bid_price=65.5),
        }
        self.mock_account.get_stocks.return_value = mock_stocks

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.execute_orders(orders, buy_only=True)

        # 只應該調用一次 create_order（買單）
        self.assertEqual(self.mock_account.create_order.call_count, 1)

        call_args = self.mock_account.create_order.call_args
        self.assertEqual(call_args.kwargs["action"], Action.BUY)
        self.assertEqual(call_args.kwargs["stock_id"], "2330")

    def test_execute_orders_buy_only_cancels_all_open_orders(self) -> None:
        """測試 buy_only 不會縮小取消委託範圍"""
        orders = [
            {"stock_id": "2330", "quantity": 1, "order_condition": OrderCondition.CASH}
        ]
        self.mock_account.get_orders.return_value = {
            "old_buy": Mock(status=OrderStatus.NEW, action=Action.BUY),
            "old_sell": Mock(status=OrderStatus.NEW, action=Action.SELL),
        }
        self.mock_account.get_stocks.return_value = {
            "2330": Mock(close=580.0, ask_price=581.0)
        }

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.execute_orders(orders, buy_only=True)

        cancelled = [c[0][0] for c in self.mock_account.cancel_order.call_args_list]
        self.assertEqual(sorted(cancelled), ["old_buy", "old_sell"])

    def test_execute_orders_sell_only(self) -> None:
        """測試只執行賣單"""
        orders = [
            {
                "stock_id": "2330",
                "quantity": 1,
                "order_condition": OrderCondition.CASH,
            },  # 買單
            {
                "stock_id": "2881",
                "quantity": -1,
                "order_condition": OrderCondition.CASH,
            },  # 賣單
        ]

        mock_stocks = {
            "2330": Mock(close=580.0, ask_price=581.0),
            "2881": Mock(close=66.0, bid_price=65.5),
        }
        self.mock_account.get_stocks.return_value = mock_stocks

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.execute_orders(orders, sell_only=True)

        # 只應該調用一次 create_order（賣單）
        self.assertEqual(self.mock_account.create_order.call_count, 1)

        call_args = self.mock_account.create_order.call_args
        self.assertEqual(call_args.kwargs["action"], Action.SELL)
        self.assertEqual(call_args.kwargs["stock_id"], "2881")

    def test_create_orders_integration(self) -> None:
        """測試 create_orders 完整流程"""
        # 設置現有持倉
        current_position = Position({"2330": 1})
        self.mock_account.get_position.return_value = current_position

        # 目標持倉
        target_position = Position({"2330": 2, "2881": 1})

        # Mock 股票報價
        mock_stocks = {
            "2330": Mock(close=580.0, ask_price=581.0),
            "2881": Mock(close=66.0, ask_price=66.5),
        }
        self.mock_account.get_stocks.return_value = mock_stocks

        oe = OrderExecutor(target_position, self.mock_account)

        # 先測試 view_only
        self.mock_account.get_orders.return_value = {
            "order1": Mock(status=OrderStatus.NEW, action=Action.BUY)
        }
        view_orders = oe.create_orders(view_only=True)
        self.assertEqual(len(view_orders), 2)  # 應該有 2 個訂單
        self.mock_account.cancel_order.assert_not_called()

        # 實際執行
        self.mock_account.get_orders.return_value = {}
        oe.create_orders()

        # 應該調用 create_order 兩次
        self.assertEqual(self.mock_account.create_order.call_count, 2)

    def test_create_orders_cancels_before_generating_orders(self) -> None:
        """測試實際執行會先取消委託，再讀取持倉產生訂單"""
        self.mock_account.get_position.return_value = Position({})
        self.mock_account.get_orders.return_value = {
            "old_sell": Mock(status=OrderStatus.NEW, action=Action.SELL)
        }
        self.mock_account.get_stocks.return_value = {
            "2330": Mock(close=580.0, ask_price=581.0)
        }

        oe = OrderExecutor(Position({"2330": 1}), self.mock_account)
        oe.create_orders()

        call_names = [call[0] for call in self.mock_account.mock_calls]
        self.assertLess(
            call_names.index("cancel_order"),
            call_names.index("get_position"),
        )

    @patch("finlab.online.order_executor.data")
    def test_update_order_price(self, mock_data: Mock) -> None:
        """測試更新委託單價格"""
        # Mock 價格數據
        mock_price_data = Mock()
        mock_price_data.loc = {"2330": 580.0, "2881": 66.0}
        mock_data.get.return_value = mock_price_data

        # 設置現有委託單
        mock_orders = {
            "order1": Mock(
                stock_id="2330", action=Action.BUY, price=575.0, status=OrderStatus.NEW
            ),
            "order2": Mock(
                stock_id="2881", action=Action.SELL, price=67.0, status=OrderStatus.NEW
            ),
        }
        self.mock_account.get_orders.return_value = mock_orders

        # Mock 股票數據
        mock_stocks = {"2330": Mock(close=580.0), "2881": Mock(close=66.0)}
        self.mock_account.get_stocks.return_value = mock_stocks

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.update_order_price(extra_bid_pct=0.05)

        # 應該調用 update_order 兩次
        self.assertEqual(self.mock_account.update_order.call_count, 2)

    @patch("finlab.online.order_executor.data")
    def test_update_order_price_buy_only_sell_only(self, mock_data: Mock) -> None:
        """測試 update_order_price 只更新買單或只更新賣單"""
        mock_price_data = Mock()
        mock_price_data.loc = {"2330": 580.0, "2881": 66.0}
        mock_data.get.return_value = mock_price_data

        mock_orders = {
            "buy1": Mock(
                stock_id="2330", action=Action.BUY, price=575.0, status=OrderStatus.NEW
            ),
            "sell1": Mock(
                stock_id="2881", action=Action.SELL, price=67.0, status=OrderStatus.NEW
            ),
        }
        self.mock_account.get_orders.return_value = mock_orders

        mock_stocks = {"2330": Mock(close=580.0), "2881": Mock(close=66.0)}
        self.mock_account.get_stocks.return_value = mock_stocks

        oe = OrderExecutor(Position({}), self.mock_account)
        oe.update_order_price(buy_only=True)
        updated = [c[0][0] for c in self.mock_account.update_order.call_args_list]
        self.assertEqual(updated, ["buy1"])

        self.mock_account.update_order.reset_mock()
        oe.update_order_price(sell_only=True)
        updated = [c[0][0] for c in self.mock_account.update_order.call_args_list]
        self.assertEqual(updated, ["sell1"])

        with self.assertRaises(ValueError):
            oe.update_order_price(buy_only=True, sell_only=True)


class TestCalculatePriceWithExtraBid(unittest.TestCase):
    """測試價格計算函數"""

    def test_calculate_price_with_extra_bid_positive(self) -> None:
        """測試正向額外競價"""
        from finlab.online.order_executor import calculate_price_with_extra_bid

        # 測試 5% 額外競價
        result = calculate_price_with_extra_bid(100.0, 0.05)
        self.assertAlmostEqual(result, 105.0, places=2)

    def test_calculate_price_with_extra_bid_negative(self) -> None:
        """測試負向額外競價（折扣）"""
        from finlab.online.order_executor import calculate_price_with_extra_bid

        # 測試 -3% 折扣  # noqa: ERA001
        result = calculate_price_with_extra_bid(100.0, -0.03)
        self.assertAlmostEqual(result, 97.0, places=2)

    def test_calculate_price_with_extra_bid_zero(self) -> None:
        """測試零額外競價"""
        from finlab.online.order_executor import calculate_price_with_extra_bid

        result = calculate_price_with_extra_bid(100.0, 0.0)
        self.assertAlmostEqual(result, 100.0, places=2)


if __name__ == "__main__":
    unittest.main()
