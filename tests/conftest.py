"""
pytest global configuration and shared fixtures.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator

import pytest

# Fubon credential env vars required for integration tests.
FUBON_ENV_VARS = ["FUBON_NATIONAL_ID", "FUBON_ACCOUNT_PASS", "FUBON_CERT_PATH"]


def has_fubon_credentials() -> bool:
    return all(os.environ.get(var) for var in FUBON_ENV_VARS)


skip_if_no_fubon_credentials = pytest.mark.skipif(
    not has_fubon_credentials(), reason="Missing Fubon credentials env vars"
)


def pytest_configure() -> None:
    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
    warnings.filterwarnings(
        "ignore", message="Deprecated call to.*pkg_resources.declare_namespace"
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)

    logging.getLogger().handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)8s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)


@pytest.fixture(scope="session")
def test_config() -> dict[str, str]:
    """測試配置 fixture"""
    return {
        "project_root": parent_dir,
        "test_data_dir": os.path.join(project_root, "fixtures"),
    }


@pytest.fixture
def mock_env_vars() -> Generator[dict[str, str]]:
    """模擬環境變數的 fixture"""
    original_env = os.environ.copy()

    # 設置測試用環境變數
    test_env = {
        "FUBON_NATIONAL_ID": "A123456789",
        "FUBON_ACCOUNT_PASS": "test_password",
        "FUBON_CERT_PATH": "/test/path/cert.pfx",
        "FUBON_CERT_PASS": "cert_password",
        "FUBON_ACCOUNT": "test_account",
        "FUBON_BASE_URL": "https://test.fubon.com",
    }

    os.environ.update(test_env)

    yield test_env

    # 恢復原始環境變數
    os.environ.clear()
    os.environ.update(original_env)
