"""
測試基礎類
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch


class BaseTestCase(unittest.TestCase):
    """基礎測試類"""

    def setUp(self) -> None:
        """測試設置"""

    def tearDown(self) -> None:
        """測試清理"""


class MockTestCase(BaseTestCase):
    """使用 Mock 的測試基礎類"""

    def setUp(self) -> None:
        super().setUp()
        self.patches: list[Any] = []

    def tearDown(self) -> None:
        """清理所有 patches"""
        for patch_obj in self.patches:
            patch_obj.stop()
        super().tearDown()

    def add_patch(self, target: str, **kwargs: Any) -> MagicMock:
        """添加 patch 並自動清理"""
        patch_obj = patch(target, **kwargs)
        mock_obj = patch_obj.start()
        self.patches.append(patch_obj)
        return mock_obj


class IntegrationTestCase(BaseTestCase):
    """整合測試基礎類"""

    def setUp(self) -> None:
        super().setUp()
        # 整合測試的特定設置


class AccountTestMixin:
    """帳戶測試混合類"""

    def assert_order_structure(self, order: Any) -> None:
        """驗證 Order 物件結構"""
        required_attrs = [
            "order_id",
            "stock_id",
            "action",
            "price",
            "quantity",
            "filled_quantity",
            "status",
            "order_condition",
            "time",
        ]
        for attr in required_attrs:
            self.assertTrue(hasattr(order, attr), f"Order 缺少屬性: {attr}")

    def assert_stock_structure(self, stock: Any) -> None:
        """驗證 Stock 物件結構"""
        required_attrs = [
            "stock_id",
            "open",
            "high",
            "low",
            "close",
            "bid_price",
            "ask_price",
            "bid_volume",
            "ask_volume",
        ]
        for attr in required_attrs:
            self.assertTrue(hasattr(stock, attr), f"Stock 缺少屬性: {attr}")

    def assert_position_structure(self, position: Any) -> None:
        """驗證 Position 物件結構"""
        self.assertTrue(hasattr(position, "position"), "Position 缺少 position 屬性")
        self.assertTrue(
            callable(getattr(position, "from_list", None)),
            "Position 缺少 from_list 方法",
        )
