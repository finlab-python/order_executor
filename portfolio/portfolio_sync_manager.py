from __future__ import annotations

import os
from typing import TYPE_CHECKING, ClassVar, cast

__all__ = ["PortfolioSyncManager"]

if TYPE_CHECKING:
    from collections.abc import Callable

    import pandas as pd
    import requests
    from finlab.portfolio.portfolio import Portfolio
    from finlab.schemas import PortfolioData, PositionEntryDict
    from typing_extensions import Unpack

    from ..core import OrderExecutor, Position
    from ..core.account import Account

from finlab.utils import get_tmp_dir

from .sync_execution import CreateOrderKwargs
from .sync_execution import create_order_executor as _create_order_executor_from_state
from .sync_execution import sync_portfolio as _sync_portfolio
from .sync_margin import margin_cash_position_combine
from .sync_market_data import (
    fetch_portfolio_market_snapshot as _fetch_portfolio_market_snapshot,
)
from .sync_reporting import (
    build_total_position_dataframe as _build_total_position_dataframe,
)
from .sync_reporting import format_portfolio_repr as _format_portfolio_repr
from .sync_state import clear_state as _clear_state
from .sync_state import get_last_market_timestamp as _get_last_market_timestamp
from .sync_state import get_position as _get_position
from .sync_state import get_strategy_position as _get_strategy_position
from .sync_storage import DataPayload
from .sync_storage import get_data_payload as _get_data_payload
from .sync_storage import get_data_typed as _get_data_typed
from .sync_storage import load_cloud_data as _load_cloud_data
from .sync_storage import load_local_data as _load_local_data
from .sync_storage import load_path_data as _load_path_data
from .sync_storage import normalize_and_check_payload as _normalize_and_check_payload
from .sync_storage import save_cloud_data as _save_cloud_data
from .sync_storage import save_local_data as _save_local_data
from .sync_storage import save_path_data as _save_path_data
from .sync_storage import set_data_payload as _set_data_payload
from .sync_storage import set_data_typed as _set_data_typed
from .sync_update import extract_saved_update_params as _extract_saved_update_params
from .sync_update import update_portfolio_state as _update_portfolio_state


class PortfolioSyncManager:
    """投資組合同步管理器 -- 設定、儲存並同步投資組合部位。

    See :meth:`update` for the main rebalancing entry point and
    :meth:`sync` / :meth:`create_order_executor` for order execution.
    """

    LOCAL_DIR: ClassVar[str] = os.path.join(get_tmp_dir(), "workspace")
    CLOUD_URL: ClassVar[str] = (
        "https://asia-east2-fdata-299302.cloudfunctions.net/auth_portfolio"
    )

    def __init__(
        self, data: DataPayload | None = None, start_with_empty: bool = False
    ) -> None:
        """建構投資組合。"""

        self.data: DataPayload = _normalize_and_check_payload(data)
        self._start_with_empty: bool = start_with_empty

    @classmethod
    def from_local(cls, name: str = "default") -> PortfolioSyncManager:
        """
        從本地檔案初始化投資組合。

        Args:
            path (str): 本地檔案的路徑。

        Returns:
            PortfolioSyncManager: 投資組合類別。
        """
        return cls(_load_local_data(name, cls.LOCAL_DIR))

    @classmethod
    def from_cloud(cls, name: str = "default") -> PortfolioSyncManager:
        """
        從雲端檔案初始化投資組合。

        Args:
            path (str, optional): 雲端檔案的路徑。預設為 'default'。

        Returns:
            PortfolioSyncManager: 投資組合類別。
        """
        return cls(_load_cloud_data(name, cls.CLOUD_URL))

    @classmethod
    def from_path(cls, path: str) -> PortfolioSyncManager:
        """
        從本地檔案初始化投資組合。

        Args:
            path (str): 本地檔案的路徑。

        Returns:
            PortfolioSyncManager: 投資組合類別。
        """
        return cls(_load_path_data(path))

    def to_local(self, name: str = "default") -> None:
        """
        將投資組合資訊存至本地檔案。

        Returns:
            None
        """
        _save_local_data(self.data, name, self.LOCAL_DIR)

    def to_cloud(self, name: str = "default") -> requests.Response:
        """
        將投資組合資訊存至雲端檔案。

        Returns:
            None
        """
        return _save_cloud_data(self.data, name, self.CLOUD_URL)

    def to_path(self, path: str) -> None:
        """
        將投資組合資訊存至本地檔案。

        Returns:
            None
        """
        _save_path_data(self.data, path)

    def get_data(self, typed: bool = False) -> DataPayload | PortfolioData:
        return _get_data_payload(self.data, typed=typed)

    def set_data(self, data: object, typed: bool = False) -> PortfolioSyncManager:
        self.data = _set_data_payload(data, typed=typed)
        return self

    def get_data_typed(self) -> PortfolioData:
        return _get_data_typed(self.data)

    def set_data_typed(self, data: object) -> PortfolioSyncManager:
        self.data = _set_data_typed(data)
        return self

    def update_same_config(self, portfolio: Portfolio) -> None:
        update = cast("Callable[..., None]", self.update)
        update(portfolio, **_extract_saved_update_params(self.data))

    def update(
        self,
        portfolio: Portfolio,
        total_balance: float = 0,
        rebalance_safety_weight: float = 0.2,
        smooth_transition: bool | None = None,
        force_override_difference: bool = False,
        custom_position: Position | dict[str, object] | None = None,
        excluded_stock_ids: list[str] | None = None,
        excluded_symbols: list[str] | None = None,
        **kwargs: object,
    ) -> None:
        """設定投資組合的函數。

        Args:
            portfolio: 包含投資組合資訊的 Portfolio 或 Report 物件。
            total_balance: 總資產。
            rebalance_safety_weight: 換股保留現金比例 (預設 0.2)。
            smooth_transition: 是否只在換股日才更新 (None 自動判斷)。
            force_override_difference: 是否強制覆蓋不同的部位。
            custom_position: 自定義部位 (不列入計算)。
            excluded_stock_ids: 排除的股票代碼列表。
            excluded_symbols: 排除的股票代碼列表 (同 excluded_stock_ids)。

        Raises:
            PortfolioError: 本次確實重建正權重 sleeve，且 total_balance 減去
                本次不更新 sleeve 的既有持股市值 <= 1e-6（絕對貨幣容差，
                遠小於 0.01，將等號與浮點微差一致視為無資金）。沒有重建、
                只移除或只停損停利時不受此檢查限制；總額與保留市值皆為 0
                的明確零預算沿用原行為。請依例外中的下限調高 total_balance，
                並預留目標股票與安全現金所需資金，再重跑 update()。拋錯時
                整次更新中止：不寫 config/history、不移除或重建部位，也不
                處理任何 sleeve（包括其他 sleeve）的停損停利。
        """
        self.data = _update_portfolio_state(
            self.data,
            portfolio,
            start_with_empty=self._start_with_empty,
            total_balance=total_balance,
            rebalance_safety_weight=rebalance_safety_weight,
            smooth_transition=smooth_transition,
            force_override_difference=force_override_difference,
            custom_position=custom_position,
            excluded_stock_ids=excluded_stock_ids,
            excluded_symbols=excluded_symbols,
            **kwargs,
        )

    def get_last_market_timestamp(self) -> str | None:
        return _get_last_market_timestamp(self.data)

    def get_strategy_position(
        self, strategy_name: str, at: str
    ) -> list[PositionEntryDict]:
        """
        獲取策略的開倉部位。

        Args:
            strategy_name (str): 策略名稱。

        Returns:
            dict: 開倉部位資訊。
        """

        return cast(
            "list[PositionEntryDict]",
            _get_strategy_position(self.data, strategy_name, at),
        )

    def get_position(
        self, at: str = "close", market_name: str | None = None
    ) -> Position:
        """
        獲取持倉資訊。

        Args:
            market_name (str, optional): 指定市場名稱。預設為 None，也就是獲取所有市場。

        Returns:
            dict or Position: 若 combined 為 True，則返回合併後的持倉資訊（Position 物件）；
                                若 combined 為 False，則返回原始持倉資訊（dict）。
        """
        return _get_position(self.data, at=at, market_name=market_name)

    def clear(self) -> None:
        """
        清除持倉資訊。

        Returns:
            None
        """
        self.data = _clear_state()

    def sync(
        self,
        account: Account,
        at: str = "close",
        consider_margin_as_asset: bool = True,
        market_name: str | None = None,
        **kwargs: Unpack[CreateOrderKwargs],
    ) -> OrderExecutor:
        """同步持倉資訊並建立委託單。

        Args:
            account: 交易帳戶。
            consider_margin_as_asset: 是否將保證金交易視為資產。
            market_name: 指定市場名稱，None 代表所有市場。
            **kwargs: 傳遞給 ``OrderExecutor.create_orders``
                (market_order, best_price_limit, view_only, extra_bid_pct 等)。
        """
        return _sync_portfolio(
            self.data,
            account,
            at=at,
            consider_margin_as_asset=consider_margin_as_asset,
            market_name=market_name,
            **kwargs,
        )

    def create_order_executor(
        self,
        account: Account,
        at: str = "close",
        consider_margin_as_asset: bool = False,
        market_name: str | None = None,
        **kwargs: object,
    ) -> OrderExecutor:
        """建立 OrderExecutor（不自動下單）。

        Args:
            account: 交易帳戶。
            consider_margin_as_asset: 是否將融資融券視為資產。
            market_name: 指定市場名稱，None 代表所有市場。
        """
        return _create_order_executor_from_state(
            self.data,
            account,
            at=at,
            consider_margin_as_asset=consider_margin_as_asset,
            market_name=market_name,
        )

    def _fetch_market_data(
        self,
    ) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
        """Fetch reference price, close price, and volume for strategy markets."""
        return _fetch_portfolio_market_snapshot(
            self.data["position"],
            include_tw=bool(self.data["config"].get("custom_position")),
        )

    def get_total_position(self) -> pd.DataFrame:
        """
        回傳目前持倉的 DataFrame（與 __repr__ 顯示的 df 相同）。

        Returns:
            pd.DataFrame: 持倉資訊的 DataFrame。
        """
        ref_price, close_price, volume = self._fetch_market_data()
        return _build_total_position_dataframe(
            self.data,
            self.get_position(),
            ref_price,
            close_price,
            volume,
        )

    def __repr__(self) -> str:
        ref_price, close_price, volume = self._fetch_market_data()
        return _format_portfolio_repr(
            self.data,
            self.get_position(),
            ref_price,
            close_price,
            volume,
        )

    margin_cash_position_combine = staticmethod(margin_cash_position_combine)

    def compare(self, account: Account) -> None:
        # compare stock assets
        self.get_position()
        account.get_position()
