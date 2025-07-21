"""
測試配置和環境變數管理
"""
import os
import logging

class TestConfig:
    """測試配置類"""
    
    # 富邦證券測試配置
    FUBON_ENV_VARS = [
        "FUBON_NATIONAL_ID",
        "FUBON_ACCOUNT_PASS", 
        "FUBON_CERT_PATH"
    ]
    
    @classmethod
    def has_fubon_credentials(cls):
        """檢查是否具備富邦證券測試所需的環境變數"""
        return all(os.environ.get(var) for var in cls.FUBON_ENV_VARS)
    
    @classmethod
    def skip_if_no_fubon_credentials(cls):
        """如果缺少富邦證券憑證則跳過測試的裝飾器"""
        import pytest
        return pytest.mark.skipif(
            not cls.has_fubon_credentials(),
            reason="缺少富邦證券測試憑證環境變數"
        )
    
    @classmethod
    def setup_test_logging(cls, level=logging.INFO):
        """設置測試日誌"""
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # 可以選擇性地關閉某些模組的日誌
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('requests').setLevel(logging.WARNING)