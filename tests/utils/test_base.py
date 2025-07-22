"""
測試基礎類
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from abc import ABC, abstractmethod

class BaseTestCase(unittest.TestCase):
    """基礎測試類"""
    
    def setUp(self):
        """測試設置"""
        pass
    
    def tearDown(self):
        """測試清理"""
        pass

class MockTestCase(BaseTestCase):
    """使用 Mock 的測試基礎類"""
    
    def setUp(self):
        super().setUp()
        self.patches = []
    
    def tearDown(self):
        """清理所有 patches"""
        for patch_obj in self.patches:
            patch_obj.stop()
        super().tearDown()
    
    def add_patch(self, target, **kwargs):
        """添加 patch 並自動清理"""
        patch_obj = patch(target, **kwargs)
        mock_obj = patch_obj.start()
        self.patches.append(patch_obj)
        return mock_obj

class IntegrationTestCase(BaseTestCase):
    """整合測試基礎類"""
    
    def setUp(self):
        super().setUp()
        # 整合測試的特定設置
        pass

class AccountTestMixin:
    """帳戶測試混合類"""
    
    def assert_order_structure(self, order):
        """驗證 Order 物件結構"""
        required_attrs = [
            'order_id', 'stock_id', 'action', 'price', 'quantity',
            'filled_quantity', 'status', 'order_condition', 'time'
        ]
        for attr in required_attrs:
            self.assertTrue(hasattr(order, attr), f"Order 缺少屬性: {attr}")
    
    def assert_stock_structure(self, stock):
        """驗證 Stock 物件結構"""
        required_attrs = [
            'stock_id', 'open', 'high', 'low', 'close',
            'bid_price', 'ask_price', 'bid_volume', 'ask_volume'
        ]
        for attr in required_attrs:
            self.assertTrue(hasattr(stock, attr), f"Stock 缺少屬性: {attr}")
    
    def assert_position_structure(self, position):
        """驗證 Position 物件結構"""
        self.assertTrue(hasattr(position, 'items'), "Position 缺少 items 屬性")
        self.assertTrue(callable(getattr(position, 'from_list', None)), "Position 缺少 from_list 方法")