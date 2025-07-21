"""
pytest 全域配置和共用 fixtures
"""
import os
import sys
import pytest
import logging

# 將專案根目錄加入 Python 路徑
project_root = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(project_root)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 配置測試日誌和 warnings
def pytest_configure():
    """配置 pytest 日誌和警告"""
    import warnings
    
    # 忽略特定的 warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
    warnings.filterwarnings("ignore", message="Deprecated call to.*pkg_resources.declare_namespace")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)8s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 設定特定模組的日誌級別
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    
    # 確保 pytest 顯示日誌
    logging.getLogger().handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)8s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

@pytest.fixture(scope="session")
def test_config():
    """測試配置 fixture"""
    return {
        "project_root": parent_dir,
        "test_data_dir": os.path.join(project_root, "fixtures"),
    }

@pytest.fixture
def mock_env_vars():
    """模擬環境變數的 fixture"""
    original_env = os.environ.copy()
    
    # 設置測試用環境變數
    test_env = {
        "FUBON_NATIONAL_ID": "A123456789",
        "FUBON_ACCOUNT_PASS": "test_password",
        "FUBON_CERT_PATH": "/test/path/cert.pfx",
        "FUBON_CERT_PASS": "cert_password",
        "FUBON_ACCOUNT": "test_account",
        "FUBON_BASE_URL": "https://test.fubon.com"
    }
    
    os.environ.update(test_env)
    
    yield test_env
    
    # 恢復原始環境變數
    os.environ.clear()
    os.environ.update(original_env)